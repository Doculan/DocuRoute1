"""Delegation while a Head is away (spec §5.5; 3C-2): the endpoints.

    GET  offices/<id>/delegations/    the office's delegations and who may be one
    POST offices/<id>/delegations/    {delegate_id, starts_on, ends_on, reason}
    POST delegations/<id>/end/        end it early

Made and ended by the office's Head - in their own post, never by a
delegate - or by the system admin, with the password: it changes who can
commit the office. See `api.delegation` for what a delegation does.
"""

from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import delegation, notifications, system_log
from .generation.common import position_title
from .models import (
    CustomUser, HeadDelegation, Notification, Office, Position, PositionAssignment, SystemEvent,
)
from .notifications import INFO, Recipient

REASON_LIMIT = 300


def _refuse(message, reason, status=400):
    return Response({'error': message, 'reason': reason}, status=status)


def _is_admin(user):
    return user.system_role == CustomUser.SYSTEM_ADMIN


def _head_assignment(office, today=None):
    """The office's Head in their own post today, or None."""
    today = today or timezone.localdate()
    return PositionAssignment.objects.filter(
        position__office=office, position__kind=Position.HEAD, position__is_active=True,
        starts_on__lte=today,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today)).select_related('user').first()


def _may_manage(user, office):
    head = _head_assignment(office)
    return _is_admin(user) or (head is not None and head.user_id == user.pk)


def _name(user):
    return user.get_full_name().strip() or user.username


def _row(d, today):
    status = ('ended' if d.ended_at else 'current' if d.starts_on <= today <= d.ends_on
              else 'upcoming' if d.starts_on > today else 'past')
    return {
        'id': d.pk, 'delegate_id': d.delegate_id, 'delegate': _name(d.delegate),
        'starts_on': d.starts_on, 'ends_on': d.ends_on, 'reason': d.reason, 'status': status,
        'ended_at': d.ended_at,
    }


def _candidates(office, head):
    """Who may be named (Q-6): a current post holder in the office, or the
    Head of the office above - not the Head being covered."""
    today = timezone.localdate()
    current = PositionAssignment.objects.filter(starts_on__lte=today).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=today)).filter(
        position__is_active=True, user__is_active=True).select_related('user', 'position')
    rows = list(current.filter(position__office=office))
    if office.parent_id:
        rows += list(current.filter(position__office_id=office.parent_id,
                                    position__kind=Position.HEAD))
    seen, found = set(), []
    for a in rows:
        if a.user_id in seen or (head is not None and a.user_id == head.user_id):
            continue
        seen.add(a.user_id)
        found.append({'id': a.user_id, 'name': _name(a.user),
                      'post': position_title(a.position.office.name, a.position.kind)
                      if a.position.office_id != office.pk else
                      position_title(office.name, a.position.kind)})
    return found


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def office_delegations(request, office_id):
    from .views import reauth_failure
    office = Office.objects.filter(pk=office_id, is_active=True).first()
    if office is None:
        return _refuse('Office not found.', 'not_found', 404)
    if not _may_manage(request.user, office):
        return _refuse("Only the office's Head, or the system admin, delegates its Head.",
                       'not_head', 403)
    head = _head_assignment(office)
    today = timezone.localdate()

    if request.method == 'GET':
        rows = HeadDelegation.objects.filter(office=office).select_related('delegate')
        shown = [d for d in rows if d.ended_at is None and d.ends_on >= today]
        return Response({
            'office': office.name,
            'head': _name(head.user) if head else None,
            'delegations': [_row(d, today) for d in shown],
            'recent': [_row(d, today) for d in rows if d not in shown][:5],
            'candidates': _candidates(office, head),
        })

    if head is None:
        return _refuse(f'{office.name} has no Head in post to delegate for.', 'no_head', 409)
    delegate = CustomUser.objects.filter(pk=request.data.get('delegate_id'), is_active=True,
                                         is_approved=True).first() \
        if str(request.data.get('delegate_id') or '').isdigit() else None
    if delegate is None or delegate.pk == head.user_id:
        return _refuse('Choose someone from the list.', 'invalid_delegate')
    if not delegation.eligible(office, delegate):
        return _refuse(f'{_name(delegate)} holds no post in {office.name} and is not the '
                       f'Head of the office above it.', 'not_eligible')
    try:
        starts_on = date.fromisoformat(str(request.data.get('starts_on')))
        ends_on = date.fromisoformat(str(request.data.get('ends_on')))
    except ValueError:
        return _refuse('Give both dates as YYYY-MM-DD.', 'invalid_dates')
    if starts_on < today or ends_on < starts_on:
        return _refuse('The period starts today or later, and ends on or after it starts.',
                       'invalid_dates')
    reason = (request.data.get('reason') or '').strip()
    if not reason or len(reason) > REASON_LIMIT:
        return _refuse(f'Give a reason, under {REASON_LIMIT} characters.', 'reason_required')
    failure = reauth_failure(request)
    if failure:
        return failure

    now = timezone.now()
    with transaction.atomic():
        # Inside the transaction: SQLite's immediate transactions mean a
        # second request waits here, then sees this one.
        if delegation.overlapping(office, starts_on, ends_on):
            return _refuse(f'{office.name} already has a delegation in that period. End it '
                           f'first, or choose other dates.', 'delegation_overlaps', 409)
        made = HeadDelegation.objects.create(
            office=office, head_assignment=head, delegate=delegate, starts_on=starts_on,
            ends_on=ends_on, reason=reason, created_by=request.user, created_at=now)
        title = position_title(office.name, Position.HEAD)
        event = system_log.record(
            SystemEvent.DELEGATION_STARTED, user=request.user, office=office, at=now,
            position=head.position,
            detail={'delegation': made.pk, 'delegate': delegate.pk, 'acting_for': head.user_id,
                    'starts_on': starts_on.isoformat(), 'ends_on': ends_on.isoformat(),
                    'reason': reason},
        )
        notifications.create(
            Notification.DELEGATED,
            [Recipient(delegate.pk, office, head.position, f'{title} (delegated)', INFO)],
            title=f'You act for the {title} from {starts_on:%d %b} to {ends_on:%d %b %Y}',
            body=reason, dedupe_key=f'delegation:{made.pk}', office_level=True,
            target=('office', office.pk), system_event=event, now=now,
        )
    return Response(_row(made, today), status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def end_delegation(request, delegation_id):
    from .views import reauth_failure
    made = HeadDelegation.objects.filter(pk=delegation_id).select_related(
        'office', 'head_assignment__position', 'delegate').first()
    if made is None:
        return _refuse('Delegation not found.', 'not_found', 404)
    if not (_is_admin(request.user) or made.head_assignment.user_id == request.user.pk):
        return _refuse('Only the Head who delegated, or the system admin, ends it.',
                       'not_head', 403)
    if made.ended_at is not None or made.ends_on < timezone.localdate():
        return _refuse('This delegation has already ended.', 'already_ended', 409)
    failure = reauth_failure(request)
    if failure:
        return failure
    now = timezone.now()
    with transaction.atomic():
        HeadDelegation.objects.filter(pk=made.pk).update(ended_at=now, ended_by=request.user)
        system_log.record(
            SystemEvent.DELEGATION_ENDED, user=request.user, office=made.office, at=now,
            position=made.head_assignment.position,
            detail={'delegation': made.pk, 'delegate': made.delegate_id,
                    'acting_for': made.head_assignment.user_id},
        )
    made.refresh_from_db()
    return Response(_row(made, timezone.localdate()))
