"""The change freeze (spec §6.6, 3D): the admin's endpoints and notices.

    GET  admin/freezes/                      in force, and the last few lifted
    POST admin/freezes/                      {reason, expected_end_on, scope, office_ids | series_ids}
    POST admin/freezes/<id>/lift/
    POST admin/freezes/<id>/extend/          {expected_end_on}
    POST admin/freezes/<id>/exceptions/      {proposal_id | manual_id, reason}

The system admin only, with the password on each POST. Affected offices
are told at start and at lift (info, office-level); the admin is told
when a freeze passes its expected end (action, cleared by lifting or
extending) and, once per deadline, when a deadline falls inside it.
See `api.freeze` for what a freeze blocks.
"""

from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import notifications, system_log
from .freeze import payload
from .models import (
    CustomUser, Deadline, DeadlineObligation, Freeze, FreezeException, FreezeTarget, Manual,
    ManualSeries, Notification, Office, Proposal, SystemEvent,
)
from .notifications import ACTION, INFO, Recipient
from .views import IsAdminRole, reauth_failure

REASON_LIMIT = 300


def _refuse(message, reason, status=400):
    return Response({'error': message, 'reason': reason}, status=status)


def _ids(raw):
    if not isinstance(raw, list) or not raw or not all(str(x).isdigit() for x in raw):
        return None
    return sorted({int(x) for x in raw})


def _admins(severity):
    return [Recipient(u.pk, None, None, 'System administrator', severity)
            for u in CustomUser.objects.filter(system_role=CustomUser.SYSTEM_ADMIN, is_active=True)]


def affected_offices(freeze_obj):
    """The offices whose work a freeze stops: every active office, the
    selected ones, or those that concur on a selected series' documents."""
    if freeze_obj.scope == Freeze.ALL:
        return list(Office.objects.filter(is_active=True).values_list('pk', flat=True))
    targets = FreezeTarget.objects.filter(freeze=freeze_obj)
    if freeze_obj.scope == Freeze.OFFICES:
        return list(targets.values_list('office_id', flat=True))
    from .org_tree import concurring_offices_of
    manuals = Manual.objects.filter(series__in=targets.values('series_id')).values_list('pk', flat=True)
    return sorted({o for offices in concurring_offices_of(manuals).values() for o in offices})


def _tell_offices(freeze_obj, event, started, now):
    offices = affected_offices(freeze_obj)
    if not offices:
        return
    recipients = notifications.office_recipients(offices, head=INFO, encoder=INFO)
    until = f'{freeze_obj.expected_end_on:%d %b %Y}'
    notifications.create_batch(
        Notification.FREEZE, [{
            'recipients': recipients,
            'title': (f'Frozen for audit until {until}' if started
                      else 'The change freeze is lifted'),
            'body': (f'{freeze_obj.reason}. New proposals, sending to the Head, submitting '
                     f'and making effective wait; drafts can still be edited.' if started
                     else f'{freeze_obj.reason}. Proposals can be started and submitted again.'),
            'manual_id': None,
        }],
        dedupe_key=f'freeze:{freeze_obj.pk}:{"started" if started else "lifted"}',
        system_event=event, target=('freeze', freeze_obj.pk), now=now,
    )


def _row(f):
    return {
        **payload(f), 'started_at': f.started_at, 'lifted_at': f.lifted_at,
        'offices': [t.office.name for t in f.targets.all() if t.office_id],
        'series': [t.series.code for t in f.targets.all() if t.series_id],
        'exceptions': [{
            'proposal': (e.proposal.dcr_number or f'{e.proposal.manual.title}') if e.proposal_id else None,
            'manual': e.manual.title if e.manual_id else None, 'reason': e.reason,
        } for e in f.exceptions.all()],
        'past_expected_end': f.lifted_at is None and f.expected_end_on < timezone.localdate(),
    }


def _date(raw):
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
def freezes(request):
    if request.method == 'GET':
        rows = Freeze.objects.prefetch_related(
            'targets__office', 'targets__series', 'exceptions__proposal__manual',
            'exceptions__manual')
        in_force = [f for f in rows if f.lifted_at is None]
        lifted = [f for f in rows if f.lifted_at is not None][:5]
        return Response({'in_force': [_row(f) for f in in_force],
                         'lifted': [_row(f) for f in lifted]})

    reason = (request.data.get('reason') or '').strip()
    if not reason or len(reason) > REASON_LIMIT:
        return _refuse(f'Give a reason, under {REASON_LIMIT} characters.', 'reason_required')
    expected = _date(request.data.get('expected_end_on'))
    if expected is None or expected < timezone.localdate():
        return _refuse('Give the expected end as a date, today or later.', 'invalid_date')
    scope = request.data.get('scope')
    if scope not in (Freeze.ALL, Freeze.OFFICES, Freeze.SERIES):
        return _refuse('Freeze everything, selected offices or selected series.', 'invalid_scope')
    targets = []
    if scope == Freeze.OFFICES:
        ids = _ids(request.data.get('office_ids'))
        if ids is None or Office.objects.filter(pk__in=ids, is_active=True).count() != len(ids):
            return _refuse('Choose the offices from the list.', 'invalid_offices')
        targets = [FreezeTarget(office_id=pk) for pk in ids]
    elif scope == Freeze.SERIES:
        ids = _ids(request.data.get('series_ids'))
        if ids is None or ManualSeries.objects.filter(pk__in=ids).count() != len(ids):
            return _refuse('Choose the series from the list.', 'invalid_series')
        targets = [FreezeTarget(series_id=pk) for pk in ids]
    failure = reauth_failure(request)
    if failure:
        return failure

    now = timezone.now()
    with transaction.atomic():
        made = Freeze.objects.create(reason=reason, expected_end_on=expected, scope=scope,
                                     started_by=request.user, started_at=now)
        for target in targets:
            target.freeze = made
        FreezeTarget.objects.bulk_create(targets)
        event = system_log.record(
            SystemEvent.FREEZE_STARTED, user=request.user, label='System administrator', at=now,
            detail={'freeze': made.pk, 'reason': reason, 'expected_end_on': expected.isoformat(),
                    'scope': scope, 'targets': [t.office_id or t.series_id for t in targets]},
        )
        _tell_offices(made, event, True, now)
        deadlines_inside(made, now)
    made = Freeze.objects.prefetch_related('targets__office', 'targets__series').get(pk=made.pk)
    return Response(_row(made), status=201)


def _in_force(freeze_id):
    return Freeze.objects.filter(pk=freeze_id, lifted_at__isnull=True).first()


@api_view(['POST'])
@permission_classes([IsAdminRole])
def lift(request, freeze_id):
    made = _in_force(freeze_id)
    if made is None:
        return _refuse('No freeze in force by that number.', 'not_in_force', 404)
    failure = reauth_failure(request)
    if failure:
        return failure
    now = timezone.now()
    with transaction.atomic():
        Freeze.objects.filter(pk=made.pk).update(lifted_at=now, lifted_by=request.user)
        made.refresh_from_db()
        event = system_log.record(
            SystemEvent.FREEZE_LIFTED, user=request.user, label='System administrator', at=now,
            detail={'freeze': made.pk})
        _tell_offices(made, event, False, now)
        notifications.resolve(Notification.objects.filter(
            dedupe_key__startswith=f'freeze:{made.pk}:'), by=request.user, now=now,
            reason='freeze lifted')
    return Response({'lifted': True})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def extend(request, freeze_id):
    made = _in_force(freeze_id)
    if made is None:
        return _refuse('No freeze in force by that number.', 'not_in_force', 404)
    expected = _date(request.data.get('expected_end_on'))
    if expected is None or expected < timezone.localdate():
        return _refuse('Give the new expected end as a date, today or later.', 'invalid_date')
    failure = reauth_failure(request)
    if failure:
        return failure
    now = timezone.now()
    with transaction.atomic():
        Freeze.objects.filter(pk=made.pk).update(expected_end_on=expected)
        system_log.record(SystemEvent.FREEZE_EXTENDED, user=request.user,
                          label='System administrator', at=now,
                          detail={'freeze': made.pk, 'extended_to': expected.isoformat()})
        notifications.resolve(Notification.objects.filter(
            dedupe_key__startswith=f'freeze:{made.pk}:past_end'), by=request.user, now=now,
            reason='freeze extended')
    return Response({'expected_end_on': expected})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def grant_exception(request, freeze_id):
    made = _in_force(freeze_id)
    if made is None:
        return _refuse('No freeze in force by that number.', 'not_in_force', 404)
    proposal = manual = None
    if str(request.data.get('proposal_id') or '').isdigit():
        proposal = Proposal.objects.filter(pk=request.data['proposal_id']).first()
    elif str(request.data.get('manual_id') or '').isdigit():
        manual = Manual.objects.filter(pk=request.data['manual_id']).first()
    if proposal is None and manual is None:
        return _refuse('Name one proposal or one manual.', 'invalid_exception')
    reason = (request.data.get('reason') or '').strip()
    if not reason or len(reason) > REASON_LIMIT:
        return _refuse(f'Give a reason, under {REASON_LIMIT} characters.', 'reason_required')
    failure = reauth_failure(request)
    if failure:
        return failure
    now = timezone.now()
    with transaction.atomic():
        granted = FreezeException.objects.create(freeze=made, proposal=proposal, manual=manual,
                                                 reason=reason, granted_by=request.user,
                                                 granted_at=now)
        system_log.record(
            SystemEvent.FREEZE_EXCEPTION_GRANTED, user=request.user, label='System administrator',
            proposal=proposal, manual=manual or (proposal.manual if proposal else None), at=now,
            detail={'freeze': made.pk, 'exception': granted.pk, 'reason': reason})
    return Response({'exception': granted.pk}, status=201)


# ─── From run_monitoring ─────────────────────────────────────

def deadlines_inside(freeze_obj, now=None):
    """The admin, once per deadline: one falls inside the freeze - extend
    it? Deadlines due between the freeze's start and expected end, still
    owed by an office it covers. Returns how many were raised."""
    now = now or timezone.now()
    start = timezone.localtime(freeze_obj.started_at).date()
    offices = affected_offices(freeze_obj)
    inside = Deadline.objects.filter(
        active=True, due_on__gte=start, due_on__lte=freeze_obj.expected_end_on,
        pk__in=DeadlineObligation.objects.filter(
            state=DeadlineObligation.OPEN, office_id__in=offices).values('deadline_id'),
    )
    raised = 0
    admins = _admins(INFO)
    for deadline in inside:
        key = f'freeze:{freeze_obj.pk}:deadline:{deadline.pk}'
        if Notification.objects.filter(dedupe_key=key).exists():
            continue
        event = system_log.record(SystemEvent.FREEZE_REMINDER, at=now,
                                  detail={'freeze': freeze_obj.pk, 'deadline_inside': deadline.pk})
        notifications.create(
            Notification.FREEZE, admins,
            title=f'{deadline.title} falls inside the audit freeze — extend it?',
            body=(f'Due {deadline.due_on:%d %b %Y}; the freeze runs to '
                  f'{freeze_obj.expected_end_on:%d %b %Y}. Its overdue notices are paused.'),
            dedupe_key=key, office_level=True, target=('deadline', deadline.pk),
            system_event=event, now=now)
        raised += 1
    return raised


def monitor(now=None):
    """The step in `run_monitoring`: a freeze past its expected end tells
    the admin (once; action, cleared by lifting or extending), and
    deadlines that have come to fall inside one are raised."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    counts = {'past_end': 0, 'deadlines_inside': 0}
    for made in Freeze.objects.filter(lifted_at__isnull=True):
        counts['deadlines_inside'] += deadlines_inside(made, now)
        if made.expected_end_on >= today:
            continue
        key = f'freeze:{made.pk}:past_end:{made.expected_end_on:%Y%m%d}'
        if Notification.objects.filter(dedupe_key=key).exists():
            continue
        event = system_log.record(SystemEvent.FREEZE_REMINDER, at=now,
                                  detail={'freeze': made.pk, 'past_expected_end': True})
        notifications.create(
            Notification.FREEZE, _admins(ACTION),
            title=f'The freeze "{made.reason}" is still in force',
            body=(f'It was expected to end on {made.expected_end_on:%d %b %Y}. '
                  f'Lift it, or extend it.'),
            dedupe_key=key, office_level=True, target=('freeze', made.pk),
            system_event=event, now=now)
        counts['past_end'] += 1
    return counts
