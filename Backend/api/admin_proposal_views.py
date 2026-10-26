"""The admin's Proposals list: every proposal, paged and filtered.

A stop-gap until the Phase 5 rebuild (MONITORING_UPDATE_SPEC.md §8). The
screen used to read the dashboard's six most recent proposals, so the
seventh was invisible to the admin and "All" meant "the last six".

Filtered and paged on the server, and built in a fixed number of queries
whatever the page holds - the version and concurrence counts come from
subqueries, not from a loop over the rows (§9).
"""

from datetime import timedelta

from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone

from .deadline_tags import tag_rows
from .models import (
    Concurrence, DeadlineObligation, Proposal, ProposalParticipant, ProposalVersion,
)
from .monitoring_views import _proposal_rows, _stalled
from .views import IsAdminRole

PAGE_SIZE = 50

# Groups the screen offers besides the single statuses. "open" is every
# status still on its way, frozen ones included - the paperwork is still
# to come.
STATUS_GROUPS = {
    'open': Proposal.HOLDING_STATUSES,
    'closed': Proposal.CLOSED_STATUSES,
    'all': None,
}
STATUSES = {value for value, _ in Proposal.STATUS_CHOICES}


def _refuse(message, reason):
    return Response({'error': message, 'reason': reason}, status=400)


def _whole_number(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _count(queryset, key):
    """A per-proposal count as a subquery, so it costs no query per row."""
    return Coalesce(
        Subquery(
            queryset.values(key).annotate(n=Count('pk')).values('n')[:1],
            output_field=IntegerField(),
        ),
        0,
    )


@api_view(['GET'])
@permission_classes([IsAdminRole])
def admin_proposals(request):
    """`?status=open|closed|all|<status>&office=<id>&series=<id>&page=<n>`"""
    params = request.query_params
    queryset = Proposal.objects.all()

    status = params.get('status') or 'open'
    if status in STATUS_GROUPS:
        if STATUS_GROUPS[status] is not None:
            queryset = queryset.filter(status__in=STATUS_GROUPS[status])
    elif status in STATUSES:
        queryset = queryset.filter(status=status)
    else:
        return _refuse('Unknown status.', 'invalid_status')

    for name, field in (('office', 'initiating_office_id'),
                        ('series', 'manual__series_id')):
        if params.get(name):
            value = _whole_number(params[name])
            if value is None:
                return _refuse(f'Choose a {name} from the list.', f'invalid_{name}')
            queryset = queryset.filter(**{field: value})

    page = _whole_number(params.get('page', 1))
    if page is None or page < 1:
        return _refuse('Pages are numbered from 1.', 'invalid_page')

    total = queryset.count()
    latest = ProposalVersion.objects.filter(
        proposal=OuterRef('pk')).order_by('-number')
    rows = (
        queryset
        .select_related('manual', 'manual__series', 'initiating_office')
        .annotate(
            latest_version_id=Subquery(latest.values('pk')[:1]),
            version_number=Subquery(latest.values('number')[:1]),
            concurring_total=_count(ProposalParticipant.objects.filter(
                proposal=OuterRef('pk'), role=ProposalParticipant.CONCURRING,
            ), 'proposal'),
        )
        .annotate(concurred_total=_count(Concurrence.objects.filter(
            version=OuterRef('latest_version_id'), decision=Concurrence.CONCUR,
        ), 'version'))
        .order_by('-updated_at', '-id')
    )[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    return Response({
        'count': total,
        'page': page,
        'page_size': PAGE_SIZE,
        'pages': max(1, -(-total // PAGE_SIZE)),
        'results': tag_rows(request.user, [{
            'id': p.id,
            'manual_id': p.manual_id,
            'manual': p.manual.title,
            'series': p.manual.series.code if p.manual.series_id else None,
            'office_id': p.initiating_office_id,
            'office': str(p.initiating_office),
            'status': p.status,
            'status_label': p.get_status_display(),
            # Which request this is: one document can have several from one
            # office (withdrawn, then made effective), and without these
            # they read as one row shown twice.
            'dcr_number': p.dcr_number,
            'created_at': p.created_at,
            'version': p.version_number,
            'concurred': p.concurred_total,
            'of': p.concurring_total,
            'updated_at': p.updated_at,
        } for p in rows]),
    })


# ─── Needs attention (spec §8.2) ─────────────────────────────

NEAR_DAYS = 30
GROUPS = ('priority_or_near', 'overdue', 'stalled')
GROUP_TOP = 10      # rows each part shows before "Show more"


@api_view(['GET'])
@permission_classes([IsAdminRole])
def admin_attention(request):
    """`?status=&office=&series=` - the block on top of the list, under
    the same filters. In order: manuals marked priority or due within 30
    days, then overdue, then stalled requests. A request appears once, in
    the first group it belongs to; a manual not yet started appears once
    per office. Each part shows its first 10 rows and its count;
    `?group=<part>&page=` pages through one part, 50 at a time."""
    params = request.query_params
    status = params.get('status') or 'open'
    if status not in STATUS_GROUPS and status not in STATUSES:
        return _refuse('Unknown status.', 'invalid_status')
    filters = {}
    for name in ('office', 'series'):
        if params.get(name):
            value = _whole_number(params[name])
            if value is None:
                return _refuse(f'Choose a {name} from the list.', f'invalid_{name}')
            filters[name] = value
    page = _whole_number(params.get('page', 1))
    if page is None or page < 1:
        return _refuse('Pages are numbered from 1.', 'invalid_page')

    now = timezone.now()
    today = timezone.localdate(now)
    open_requests = Proposal.objects.exclude(status__in=Proposal.CLOSED_STATUSES)
    if status in STATUSES:
        open_requests = open_requests.filter(status=status)
    elif status == 'closed':
        open_requests = open_requests.none()
    if 'office' in filters:
        open_requests = open_requests.filter(initiating_office_id=filters['office'])
    if 'series' in filters:
        open_requests = open_requests.filter(manual__series_id=filters['series'])
    not_started_shown = status in ('open', 'all')

    obligations = DeadlineObligation.objects.filter(
        state=DeadlineObligation.OPEN, deadline__active=True, manual__isnull=False,
    ).filter(Q(priority=True) | Q(deadline__due_on__lte=today + timedelta(days=NEAR_DAYS)))
    if 'office' in filters:
        obligations = obligations.filter(office_id=filters['office'])
    if 'series' in filters:
        obligations = obligations.filter(manual__series_id=filters['series'])
    requests_by_pair = {(m, o): pk for pk, m, o in open_requests.filter(
        manual_id__in=obligations.values('manual_id'),
    ).values_list('pk', 'manual_id', 'initiating_office_id')}

    entries, seen_requests, seen_pairs = [], set(), set()
    owed_rows = sorted(obligations.values_list(
        'pk', 'manual_id', 'office_id', 'priority', 'deadline__due_on'), key=lambda r: (r[4], r[0]))
    for group in GROUPS[:2]:
        for pk, manual_id, office_id, priority, due_on in owed_rows:
            overdue = due_on < today
            belongs = (priority or not overdue) if group == 'priority_or_near' else overdue
            if not belongs or (manual_id, office_id) in seen_pairs:
                continue
            request_pk = requests_by_pair.get((manual_id, office_id))
            if request_pk is None and not not_started_shown:
                continue
            if request_pk is not None and request_pk in seen_requests:
                continue
            seen_pairs.add((manual_id, office_id))
            if request_pk is not None:
                seen_requests.add(request_pk)
            rank = (due_on - today).days if group == 'priority_or_near' else (due_on - today).days
            entries.append((group, rank, request_pk, pk))
    stalled = []
    for query in _stalled(open_requests, now).values():
        stalled += list(query.values_list('pk', 'entered'))
    for request_pk, _ in sorted(stalled, key=lambda r: (r[1], r[0])):
        if request_pk not in seen_requests:
            seen_requests.add(request_pk)
            entries.append(('stalled', 0, request_pk, None))
    # Overdue: most days late first.
    entries = ([e for e in entries if e[0] == 'priority_or_near']
               + sorted((e for e in entries if e[0] == 'overdue'), key=lambda e: (e[1], e[3]))
               + [e for e in entries if e[0] == 'stalled'])

    counts = {g: sum(1 for e in entries if e[0] == g) for g in GROUPS}
    group = params.get('group')
    if group:
        if group not in GROUPS:
            return _refuse('Unknown part.', 'invalid_group')
        entries = [e for e in entries if e[0] == group]
        total = len(entries)
        chosen = entries[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        pages = max(1, -(-total // PAGE_SIZE))
    else:
        total = len(entries)
        chosen = [e for g in GROUPS for e in [x for x in entries if x[0] == g][:GROUP_TOP]]
        pages = 1
    proposals = {p.pk: p for p in Proposal.objects.filter(
        pk__in=[e[2] for e in chosen if e[2]]).select_related('manual__series', 'initiating_office')}
    base = {r['proposal_id']: r for r in _proposal_rows(list(proposals.values()), now)}
    named = {ob.pk: ob for ob in DeadlineObligation.objects.filter(
        pk__in=[e[3] for e in chosen if e[3]]).select_related('deadline__type', 'manual__series', 'office')}
    owed = {}
    for ob in DeadlineObligation.objects.filter(
            state=DeadlineObligation.OPEN, deadline__active=True,
            manual_id__in={p.manual_id for p in proposals.values()},
            office_id__in={p.initiating_office_id for p in proposals.values()},
    ).select_related('deadline__type').order_by('deadline__due_on'):
        owed.setdefault((ob.manual_id, ob.office_id), ob)

    def deadline(ob):
        if ob is None:
            return None
        late = (today - ob.deadline.due_on).days
        return {'id': ob.deadline_id, 'title': ob.deadline.title, 'type': ob.deadline.type.name,
                'due_on': ob.deadline.due_on, 'days_late': max(late, 0), 'priority': ob.priority}

    rows = []
    for group, _, request_pk, obligation_pk in chosen:
        ob = named.get(obligation_pk)
        if request_pk:
            p, r = proposals[request_pk], base[request_pk]
            ob = ob or owed.get((p.manual_id, p.initiating_office_id))
            rows.append({'group': group, 'proposal_id': p.pk, 'manual_id': p.manual_id,
                         'manual': p.manual.title,
                         'series': p.manual.series.code if p.manual.series_id else None,
                         'office': p.initiating_office.name, 'due': deadline(ob),
                         'status': r['status'], 'holder': r['holder'], 'days': r['days'],
                         'waiting_on': r['waiting_on'], 'stalled': r['stalled'],
                         'action': {'kind': 'open', 'label': 'Open'}})
        else:
            rows.append({'group': group, 'proposal_id': None, 'manual_id': ob.manual_id,
                         'manual': ob.manual.title,
                         'series': ob.manual.series.code if ob.manual.series_id else None,
                         'office': ob.office.name, 'due': deadline(ob),
                         'status': 'Not started', 'holder': ob.office.name, 'days': None,
                         'waiting_on': '', 'stalled': False,
                         'action': {'kind': 'deadline', 'label': 'Open deadline'}})
    return Response({'count': total, 'page': page, 'page_size': PAGE_SIZE,
                     'pages': pages, 'groups': counts, 'top': GROUP_TOP,
                     'rows': tag_rows(request.user, rows)})
