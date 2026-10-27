"""Announcements and deadlines (Phase 3A, spec §6.1-6.3).

Two kinds, one admin screen. **Announcements** are information: always a
banner, dismissible per person, deactivated rather than deleted.
**Deadlines** are obligations: tracked office by office through
`DeadlineObligation`, shown in the pinned action row until met.

Lists are paged at 50 and counted with aggregates or the deadline's own
counts - never a query per row (spec §9).
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access, deadlines, system_log
from .deadline_tags import tag_rows
from .models import (
    Announcement, AnnouncementDismissal, AnnouncementOffice, Deadline, DeadlineObligation,
    DeadlineTarget, DeadlineType, Manual, ManualSeries, Office, Position, Proposal, SystemEvent,
)
from .org_tree import Tree, concurring_office_ids, concurring_offices_of, expand_offices
from .views import IsAdminRole


class AdminOrQmsReading(IsAdminRole):
    """The system admin, or QMS staff reading (GET only): the QMS portal's
    Deadlines tab is read-only. Setting, changing and deactivating stay
    the admin's."""

    def has_permission(self, request, view):
        from . import access
        if super().has_permission(request, view):
            return True
        return request.method in ('GET', 'HEAD', 'OPTIONS') and access.is_qms_staff(request.user)

PAGE_SIZE = 50
BANNER_SHOWN = 5


def _refuse(message, reason, status=400, **extra):
    return Response({'error': message, 'reason': reason, **extra}, status=status)


def _page(request):
    try:
        page = int(request.query_params.get('page') or 1)
    except (TypeError, ValueError):
        page = 0
    return page if page >= 1 else None


def _paged(queryset, page):
    total = queryset.count()
    return total, max(1, -(-total // PAGE_SIZE)), queryset[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]


def _truthy(value):
    return value is True or str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _date(raw):
    if raw in (None, '', 'null'):
        return None, False
    parsed = parse_date(str(raw))
    return parsed, parsed is None


def _office_targets(raw):
    """[{office_id, include_descendants}] -> [(Office, bool)], or a refusal."""
    if not isinstance(raw, list) or not raw:
        return None, _refuse('Choose at least one office.', 'no_offices')
    ids = []
    for item in raw:
        try:
            ids.append((int(item.get('office_id')), _truthy(item.get('include_descendants'))))
        except (AttributeError, TypeError, ValueError):
            return None, _refuse('Choose offices from the list.', 'invalid_office')
    offices = Office.objects.in_bulk([pk for pk, _ in ids])
    if len(offices) != len({pk for pk, _ in ids}) or not all(o.is_active for o in offices.values()):
        return None, _refuse('Choose active offices from the list.', 'invalid_office')
    return [(offices[pk], below) for pk, below in ids], None


# ─── Announcements ───────────────────────────────────────────

def visible_announcements(user, today=None):
    """Live announcements this person sees: everyone's, and those aimed at
    an office where they hold a post - directly, or beneath a target that
    includes everything below it."""
    today = today or timezone.localdate()
    mine = {o.pk for o in access.current_offices(user)}
    live = list(Announcement.objects.filter(active=True).filter(
        Q(expires_on__isnull=True) | Q(expires_on__gte=today),
    ).prefetch_related('targets').order_by('-created_at', '-pk'))
    tree = concurring = None
    shown = []
    for announcement in live:
        if announcement.audience == Announcement.ALL:
            shown.append(announcement)
            continue
        targets = list(announcement.targets.all())
        if any(t.include_descendants for t in targets) and tree is None:
            tree, concurring = Tree(), concurring_office_ids()
        reached = (expand_offices([(t.office_id, t.include_descendants) for t in targets],
                                  tree, concurring) if tree else {t.office_id for t in targets})
        if mine & reached:
            shown.append(announcement)
    return shown


def _announcement_payload(announcement, today, dismissals=None):
    targets = list(announcement.targets.select_related('office'))
    return {
        'id': announcement.id,
        'title': announcement.title,
        'body': announcement.body,
        'audience': announcement.audience,
        'targets': [{'office_id': t.office_id, 'office': t.office.name,
                     'include_descendants': t.include_descendants} for t in targets],
        'expires_on': announcement.expires_on,
        'expired': bool(announcement.expires_on and announcement.expires_on < today),
        'active': announcement.active,
        'created_by': announcement.created_by.username if announcement.created_by else None,
        'created_at': announcement.created_at,
        'dismissals': dismissals if dismissals is not None else announcement.dismissals.count(),
    }


def _clean_announcement(data, partial):
    fields, targets = {}, None
    if 'title' in data or not partial:
        title = (data.get('title') or '').strip()
        if not title:
            return None, None, _refuse('A title is required.', 'title_required')
        fields['title'] = title[:200]
    if 'body' in data or not partial:
        fields['body'] = (data.get('body') or '').strip()
    if 'expires_on' in data or not partial:
        expires, bad = _date(data.get('expires_on'))
        if bad:
            return None, None, _refuse('Use a date like 2026-11-12.', 'invalid_date')
        fields['expires_on'] = expires
    if 'audience' in data or not partial:
        audience = data.get('audience') or Announcement.ALL
        if audience not in (Announcement.ALL, Announcement.OFFICES):
            return None, None, _refuse('Choose everyone or selected offices.', 'invalid_audience')
        fields['audience'] = audience
        if audience == Announcement.OFFICES:
            targets, refusal = _office_targets(data.get('targets'))
            if refusal:
                return None, None, refusal
    if 'active' in data:
        fields['active'] = _truthy(data.get('active'))
    return fields, targets, None


@api_view(['GET', 'POST'])
@permission_classes([IsAdminRole])
def admin_announcements(request):
    """`?status=live|expired|inactive|all&page=`. No DELETE route exists:
    deactivating is how an announcement is removed."""
    today = timezone.localdate()
    if request.method == 'GET':
        page = _page(request)
        if page is None:
            return _refuse('Pages are numbered from 1.', 'invalid_page')
        status = request.query_params.get('status', 'all')
        rows = Announcement.objects.all()
        live = Q(expires_on__isnull=True) | Q(expires_on__gte=today)
        rows = {'live': rows.filter(live, active=True),
                'expired': rows.filter(active=True, expires_on__lt=today),
                'inactive': rows.filter(active=False)}.get(status, rows)
        rows = rows.select_related('created_by').annotate(n_dismissed=Count('dismissals')) \
                   .order_by('-active', '-created_at', '-pk')
        total, pages, rows = _paged(rows, page)
        return Response({'count': total, 'page': page, 'pages': pages,
                         'announcements': [_announcement_payload(a, today, a.n_dismissed)
                                           for a in rows]})

    fields, targets, refusal = _clean_announcement(request.data, partial=False)
    if refusal:
        return refusal
    with transaction.atomic():
        announcement = Announcement.objects.create(created_by=request.user, **fields)
        for office, below in targets or []:
            AnnouncementOffice.objects.create(announcement=announcement, office=office,
                                              include_descendants=below)
    return Response(_announcement_payload(announcement, today), status=201)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminRole])
def admin_announcement_detail(request, announcement_id):
    today = timezone.localdate()
    announcement = Announcement.objects.filter(pk=announcement_id).first()
    if announcement is None:
        return _refuse('Announcement not found', 'not_found', status=404)
    if request.method == 'GET':
        return Response(_announcement_payload(announcement, today))
    fields, targets, refusal = _clean_announcement(request.data, partial=True)
    if refusal:
        return refusal
    with transaction.atomic():
        if fields.get('active') is False and announcement.active:
            announcement.deactivated_by, announcement.deactivated_at = request.user, timezone.now()
        for name, value in fields.items():
            setattr(announcement, name, value)
        announcement.save()
        if 'audience' in fields:
            announcement.targets.all().delete()
            for office, below in targets or []:
                AnnouncementOffice.objects.create(announcement=announcement, office=office,
                                                  include_descendants=below)
    return Response(_announcement_payload(announcement, today))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def announcement_banner(request):
    """The announcement row: newest first, without the ones this person
    dismissed. It sits beneath the pinned action row."""
    dismissed = set(AnnouncementDismissal.objects.filter(user=request.user)
                    .values_list('announcement_id', flat=True))
    rows = [a for a in visible_announcements(request.user) if a.pk not in dismissed]
    return Response({'total': len(rows), 'items': [
        {'id': a.pk, 'title': a.title, 'body': a.body} for a in rows[:BANNER_SHOWN]]})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def dismiss_announcement(request, announcement_id):
    """Close one announcement for this person only."""
    announcement = Announcement.objects.filter(pk=announcement_id).first()
    if announcement is None:
        return _refuse('Announcement not found', 'not_found', status=404)
    AnnouncementDismissal.objects.get_or_create(announcement=announcement, user=request.user)
    return Response({'dismissed': True})


# ─── Deadline types ──────────────────────────────────────────

def _type_payload(t):
    return {'id': t.pk, 'name': t.name, 'basis': t.basis, 'is_preset': t.is_preset,
            'confirm_with_qms': t.confirm_with_qms}


def _new_type(name, user):
    name = (name or '').strip()[:120]
    if not name:
        return None, _refuse('Name the new type.', 'type_name_required')
    if DeadlineType.objects.filter(name__iexact=name).exists():
        return None, _refuse(f'"{name}" is already a type.', 'type_exists')
    return DeadlineType.objects.create(name=name, created_by=user), None


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def deadline_types(request):
    if request.method == 'GET':
        return Response({'types': [_type_payload(t) for t in DeadlineType.objects.filter(active=True)]})
    if not IsAdminRole().has_permission(request, None):
        return _refuse('Only the admin adds deadline types.', 'not_admin', status=403)
    created, refusal = _new_type(request.data.get('name'), request.user)
    if refusal:
        return refusal
    return Response(_type_payload(created), status=201)


# ─── Deadlines ───────────────────────────────────────────────

def _deadline_payload(deadline, today):
    level, days = deadlines.urgency(deadline, today)
    return {
        'id': deadline.pk, 'title': deadline.title,
        'type': deadline.type.name, 'type_id': deadline.type_id,
        'due_on': deadline.due_on, 'urgency': level, 'days': days,
        'note': deadline.note, 'reminder_days': deadline.reminder_days,
        'active': deadline.active,
        'obligations_total': deadline.obligations_total,
        'obligations_open': deadline.obligations_open,
        'obligations_met': deadline.obligations_met,
        'unmet': f'{deadline.obligations_open} of {deadline.obligations_total} not yet met',
        'created_at': deadline.created_at,
    }


def _clean_targets(raw):
    """[{kind, office_id, include_descendants, series_id, manual_id}] ->
    unsaved DeadlineTarget rows, or a refusal."""
    if not isinstance(raw, list) or not raw:
        return None, _refuse('Choose who the deadline is for.', 'no_targets')
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            return None, _refuse('Choose targets from the lists.', 'invalid_target')
        kind = item.get('kind')
        try:
            if kind == DeadlineTarget.ALL:
                rows.append(DeadlineTarget(kind=kind))
            elif kind == DeadlineTarget.OFFICE:
                office = Office.objects.get(pk=int(item.get('office_id')), is_active=True)
                rows.append(DeadlineTarget(kind=kind, office=office,
                                           include_descendants=_truthy(item.get('include_descendants'))))
            elif kind == DeadlineTarget.SERIES:
                rows.append(DeadlineTarget(kind=kind, series=ManualSeries.objects.get(
                    pk=int(item.get('series_id')))))
            elif kind == DeadlineTarget.MANUAL:
                rows.append(DeadlineTarget(kind=kind, manual=Manual.objects.get(
                    pk=int(item.get('manual_id')))))
            else:
                return None, _refuse('Choose targets from the lists.', 'invalid_target')
        except (Office.DoesNotExist, ManualSeries.DoesNotExist, Manual.DoesNotExist,
                TypeError, ValueError):
            return None, _refuse('Choose targets from the lists.', 'invalid_target')
    return rows, None


def _clean_deadline(data, user, partial, deadline=None):
    fields = {}
    if 'title' in data or not partial:
        title = (data.get('title') or '').strip()
        if not title:
            return None, None, _refuse('A title is required.', 'title_required')
        fields['title'] = title[:200]
    if 'type_id' in data or 'new_type' in data or not partial:
        if data.get('new_type'):
            fields['new_type'] = data.get('new_type')
        else:
            dtype = DeadlineType.objects.filter(pk=data.get('type_id') or 0, active=True).first()
            if dtype is None:
                return None, None, _refuse('Choose a type, or add your own.', 'invalid_type')
            fields['type'] = dtype
    if 'due_on' in data or not partial:
        due, bad = _date(data.get('due_on'))
        if bad or due is None:
            return None, None, _refuse('Use a date like 2026-11-12.', 'invalid_date')
        # An edit may keep a date that has passed; it may not set one.
        if due < timezone.localdate() and (deadline is None or due != deadline.due_on):
            return None, None, _refuse('The due date has passed.', 'due_in_past')
        fields['due_on'] = due
    if 'note' in data or not partial:
        fields['note'] = (data.get('note') or '').strip()
    if 'reminder_days' in data:
        days = data.get('reminder_days')
        if (not isinstance(days, list)
                or not all(isinstance(d, int) and 0 < d <= 365 for d in days)):
            return None, None, _refuse('Reminders are days before, from 1 to 365.',
                                       'invalid_reminders')
        fields['reminder_days'] = sorted(set(days), reverse=True)
    if 'active' in data:
        fields['active'] = _truthy(data.get('active'))
    targets = None
    if 'targets' in data or not partial:
        if deadline is not None and deadline.due_on < timezone.localdate():
            return None, None, _refuse('Targets cannot change after the due date.', 'past_due')
        targets, refusal = _clean_targets(data.get('targets'))
        if refusal:
            return None, None, refusal
    return fields, targets, None


@api_view(['GET', 'POST'])
@permission_classes([AdminOrQmsReading])
def admin_deadlines(request):
    """GET: counts first, then deadlines paged (`?status=open|past|inactive|all`).
    POST: create - or, with `preview`, say what saving would do, saving
    nothing. No password: setting a deadline commits no office."""
    today = timezone.localdate()
    if request.method == 'GET':
        page = _page(request)
        if page is None:
            return _refuse('Pages are numbered from 1.', 'invalid_page')
        active = Deadline.objects.filter(active=True)
        window_end = today + timedelta(days=max(Deadline().reminder_days))
        summary = active.aggregate(
            open=Count('pk', filter=Q(obligations_open__gt=0, due_on__gte=today)),
            due_soon=Count('pk', filter=Q(obligations_open__gt=0, due_on__gte=today,
                                          due_on__lte=window_end)),
            overdue=Count('pk', filter=Q(obligations_open__gt=0, due_on__lt=today)),
        )
        status = request.query_params.get('status', 'open')
        rows = {'open': active.filter(Q(due_on__gte=today) | Q(obligations_open__gt=0)),
                'past': active.filter(due_on__lt=today, obligations_open=0),
                'inactive': Deadline.objects.filter(active=False)}.get(
                    status, Deadline.objects.all())
        total, pages, rows = _paged(rows.select_related('type').order_by('due_on', 'pk'), page)
        return Response({'summary': summary, 'count': total, 'page': page, 'pages': pages,
                         'deadlines': [_deadline_payload(d, today) for d in rows]})

    fields, targets, refusal = _clean_deadline(request.data, request.user, partial=False)
    if refusal:
        return refusal
    if _truthy(request.query_params.get('preview')) or _truthy(request.data.get('preview')):
        return Response(deadlines.preview(targets))
    with transaction.atomic():
        if 'new_type' in fields:
            fields['type'], refusal = _new_type(fields.pop('new_type'), request.user)
            if refusal:
                transaction.set_rollback(True)
                return refusal
        deadline = Deadline.objects.create(created_by=request.user, **fields)
        for target in targets:
            target.deadline = deadline
            target.save()
        deadlines.materialise(deadline, request.user)
        deadline.refresh_from_db()
    return Response(_deadline_payload(deadline, today), status=201)


@api_view(['GET', 'PATCH'])
@permission_classes([AdminOrQmsReading])
def admin_deadline_detail(request, deadline_id):
    today = timezone.localdate()
    deadline = Deadline.objects.select_related('type').filter(pk=deadline_id).first()
    if deadline is None:
        return _refuse('Deadline not found', 'not_found', status=404)
    if request.method == 'GET':
        data = _deadline_payload(deadline, today)
        data['targets'] = [{
            'kind': t.kind, 'office_id': t.office_id,
            'office': t.office.name if t.office_id else None,
            'include_descendants': t.include_descendants,
            'series_id': t.series_id, 'series': t.series.code if t.series_id else None,
            'manual_id': t.manual_id, 'manual': t.manual.title if t.manual_id else None,
        } for t in deadline.targets.select_related('office', 'series', 'manual')]
        tree = Tree()
        by_branch = {}
        for office_id, state, n in (deadline.obligations.exclude(
                state=DeadlineObligation.CANCELLED).values_list('office_id', 'state')
                                    .annotate(n=Count('pk'))):
            branch = tree.branch(office_id)
            row = by_branch.setdefault(branch, {'branch_id': branch, 'branch': tree.name[branch],
                                                'open': 0, 'met': 0})
            row['open' if state == DeadlineObligation.OPEN else 'met'] += n
        data['by_branch'] = sorted(by_branch.values(), key=lambda r: (-r['open'], r['branch']))
        return Response(data)

    fields, targets, refusal = _clean_deadline(request.data, request.user, partial=True,
                                                deadline=deadline)
    if refusal:
        return refusal
    moved = deadlines.changes(deadline, targets) if targets is not None else None
    if _truthy(request.query_params.get('preview')) or _truthy(request.data.get('preview')):
        # What saving would do, saving nothing: who is told, and who is
        # added or taken off.
        told = deadlines.preview(targets) if targets is not None else {}
        names = dict(Office.objects.filter(pk__in=sum((moved or {}).values(), []))
                     .values_list('pk', 'name'))
        for key in ('offices_added', 'offices_removed'):
            told[key] = sorted(names[o] for o in (moved or {}).get(key, []))
        return Response(told)
    with transaction.atomic():
        if 'new_type' in fields:
            fields['type'], refusal = _new_type(fields.pop('new_type'), request.user)
            if refusal:
                transaction.set_rollback(True)
                return refusal
        before = {name: _shown(getattr(deadline, name)) for name in fields}
        if targets is not None:
            before['targets'] = _targets_shown(deadline.targets.select_related(
                'office', 'series', 'manual'))
        for name, value in fields.items():
            setattr(deadline, name, value)
        deadline.save()
        after = {name: _shown(value) for name, value in fields.items()}
        if targets is not None:
            after['targets'] = _targets_shown(targets)
        changed = sorted(name for name in after if after[name] != before[name])
        detail = {'deadline': deadline.pk, 'fields': changed,
                  'old': {n: before[n] for n in changed}, 'new': {n: after[n] for n in changed}}
        if moved:
            detail.update(moved)
        event = system_log.record(SystemEvent.DEADLINE_CHANGED, user=request.user,
                                  label='System administrator', detail=detail)
        if targets is not None:
            deadline.targets.all().delete()
            for target in targets:
                target.deadline = deadline
                target.save()
            deadlines.materialise(deadline, request.user, event=event)
        deadline.refresh_from_db()
    return Response(_deadline_payload(deadline, today))


def _shown(value):
    """A field's value as the audit entry keeps it."""
    if isinstance(value, DeadlineType):
        return value.name
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


def _targets_shown(targets):
    """Targets in words, for the audit entry's before and after."""
    words = []
    for t in targets:
        if t.kind == DeadlineTarget.ALL:
            words.append('All offices')
        elif t.kind == DeadlineTarget.OFFICE:
            words.append(t.office.name + (' and the offices under it'
                                          if t.include_descendants else ''))
        elif t.kind == DeadlineTarget.SERIES:
            words.append(f'Series {t.series.code}')
        else:
            words.append(f'Manual {t.manual.title}')
    return sorted(words)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def admin_deadline_priority(request, deadline_id):
    """`{office_id, manual_ids}`: these manuals are priority for this office
    under the deadline (spec §6.4). The office must concur on each. No
    password: like setting the deadline (Q-2), it asks work of an office
    but commits nobody."""
    deadline = Deadline.objects.filter(pk=deadline_id, active=True).first()
    if deadline is None:
        return _refuse('Deadline not found', 'not_found', status=404)
    office = Office.objects.filter(pk=request.data.get('office_id'), is_active=True).first()         if str(request.data.get('office_id') or '').isdigit() else None
    if office is None:
        return _refuse('Choose an office from the list.', 'invalid_office')
    raw = request.data.get('manual_ids')
    if not isinstance(raw, list) or not raw or not all(str(m).isdigit() for m in raw):
        return _refuse('Choose at least one manual.', 'invalid_manuals')
    manuals = list(Manual.objects.filter(pk__in=[int(m) for m in raw]))
    if len(manuals) != len(set(int(m) for m in raw)):
        return _refuse('Choose manuals from the list.', 'invalid_manuals')
    concurring = concurring_offices_of([m.pk for m in manuals])
    strangers = sorted(m.title for m in manuals if office.pk not in concurring.get(m.pk, []))
    if strangers:
        return _refuse(f'{office.name} does not concur on {", ".join(strangers)}.',
                       'not_concurring')
    if 'priority' in request.data and not _truthy(request.data.get('priority')):
        with transaction.atomic():
            unflagged = deadlines.unset_priority(deadline, office, manuals, request.user)
        return Response({'unset': len(unflagged)})
    with transaction.atomic():
        flagged = deadlines.set_priority(deadline, office, manuals, request.user)
    return Response({'priority': len(flagged), 'open': sum(
        ob.state == DeadlineObligation.OPEN for ob in flagged)})


@api_view(['GET'])
@permission_classes([AdminOrQmsReading])
def admin_deadline_obligations(request, deadline_id):
    """`?state=open|met|all&branch=<office id>&page=`, unmet first."""
    deadline = Deadline.objects.filter(pk=deadline_id).first()
    if deadline is None:
        return _refuse('Deadline not found', 'not_found', status=404)
    page = _page(request)
    if page is None:
        return _refuse('Pages are numbered from 1.', 'invalid_page')
    rows = deadline.obligations.exclude(state=DeadlineObligation.CANCELLED).select_related(
        'office', 'manual', 'met_by_proposal')
    state = request.query_params.get('state', 'all')
    if state == 'open':
        rows = rows.filter(state=DeadlineObligation.OPEN)
    elif state == 'met':
        rows = rows.exclude(state=DeadlineObligation.OPEN)
    tree = Tree()
    branch = request.query_params.get('branch')
    if branch:
        try:
            branch = int(branch)
        except ValueError:
            return _refuse('Choose a branch from the list.', 'invalid_branch')
        rows = rows.filter(office_id__in=[branch] + tree.descendants(branch))
    unmet_first = Case(When(state=DeadlineObligation.OPEN, then=Value(0)), default=Value(1),
                       output_field=IntegerField())
    total, pages, rows = _paged(rows.order_by(unmet_first, '-priority', 'office__name',
                                              'manual__title'), page)
    return Response({'count': total, 'page': page, 'pages': pages, 'obligations': [{
        'id': ob.pk, 'office_id': ob.office_id, 'office': ob.office.name,
        'branch': tree.name[tree.branch(ob.office_id)],
        'manual_id': ob.manual_id, 'manual': ob.manual.title if ob.manual_id else None,
        'state': ob.state, 'state_label': ob.get_state_display(), 'priority': ob.priority,
        'office_met_at': ob.office_met_at, 'effective_at': ob.effective_at,
        'met_by': ({'proposal_id': ob.met_by_proposal_id,
                    'dcr_number': ob.met_by_proposal.dcr_number}
                   if ob.met_by_proposal_id else None),
    } for ob in rows]})


def _offices_owing(user):
    """Offices where this person is Head or Encoder: who sees deadlines."""
    from .proposal_views import _current_assignments
    return {a.position.office_id for a in _current_assignments(
        user, [Position.HEAD, Position.ENCODER])}


def deadline_groups(user, today=None):
    """This person's offices' open obligations, one entry per deadline and
    office, most urgent first. One query."""
    today = today or timezone.localdate()
    groups = {}
    for ob in deadlines.open_for(_offices_owing(user)):
        key = (ob.deadline_id, ob.office_id)
        level, days = deadlines.urgency(ob.deadline, today)
        group = groups.setdefault(key, {
            'deadline_id': ob.deadline_id, 'title': ob.deadline.title,
            'type': ob.deadline.type.name, 'due_on': ob.deadline.due_on,
            'urgency': level, 'days': days, 'office': ob.office.name,
            'office_id': ob.office_id, 'manuals': [],
            'office_level': False, 'note': ob.deadline.note,
        })
        if ob.manual_id:
            group['manuals'].append({'id': ob.manual_id, 'title': ob.manual.title,
                                     'priority': ob.priority})
            group['priority'] = group.get('priority', False) or ob.priority
        else:
            group['office_level'] = True
    for group in groups.values():
        # Priority manuals first (spec §6.4).
        group['manuals'].sort(key=lambda m: (not m['priority'], m['title']))
        group.setdefault('priority', False)
    return sorted(groups.values(), key=lambda g: (deadlines.URGENCY_ORDER[g['urgency']],
                                                  not g['priority'], g['due_on'], g['title']))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_deadlines(request):
    """The Deadlines panel and page: what this person's offices still owe."""
    page = _page(request)
    if page is None:
        return _refuse('Pages are numbered from 1.', 'invalid_page')
    groups = deadline_groups(request.user)
    start = (page - 1) * PAGE_SIZE
    shown = groups[start:start + PAGE_SIZE]
    _with_status(shown)
    return Response({'count': len(groups), 'page': page,
                     'pages': max(1, -(-len(groups) // PAGE_SIZE)),
                     'deadlines': shown})


def _with_status(groups):
    """Each manual owed, with where the office has got: Not started, or
    its request's stage in the §7.2 words. One query for the page."""
    from .monitoring_views import STATUS_WORDS
    pairs = {(m['id'], g['office_id']) for g in groups for m in g['manuals']}
    stage = {}
    if pairs:
        for manual_id, office_id, pk, status in Proposal.objects.filter(
                manual_id__in={m for m, _ in pairs}, initiating_office_id__in={o for _, o in pairs},
        ).exclude(status__in=Proposal.CLOSED_STATUSES).values_list(
                'manual_id', 'initiating_office_id', 'pk', 'status'):
            stage[(manual_id, office_id)] = (pk, STATUS_WORDS.get(status, status))
    for g in groups:
        for m in g['manuals']:
            pk, word = stage.get((m['id'], g['office_id']), (None, 'Not started'))
            m['status'], m['proposal_id'] = word, pk


@api_view(['GET'])
@permission_classes([IsAdminRole])
def manual_search(request):
    """For the target picker: the first 20 documents matching a title or
    series code. Not the 3,000-row list."""
    q = (request.query_params.get('q') or '').strip()
    rows = Manual.objects.select_related('series')
    if q:
        rows = rows.filter(Q(title__icontains=q) | Q(series__code__icontains=q))
    return Response({'manuals': tag_rows(request.user, [
        {'id': m.pk, 'title': m.title, 'series': m.series.code if m.series_id else None}
        for m in rows.order_by('title')[:20]], key='id')})
