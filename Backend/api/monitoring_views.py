"""Monitoring (v4.2 Phase 4, step 2): read-only, scoped, counted live.

    GET monitoring/overview/                       counts for the viewer's scope, and the offices chart
    GET monitoring/offices/?parent=<id>&page=      one level of the office tree, rolled up from beneath
    GET monitoring/items/?bucket=&office=&subtree=&page=   the rows behind a count, 50 a page
    GET monitoring/offices-chart/?mode=pending|approved&period=month|year|last_year

**Scope** is `access.monitoring_scope`: the admin and QMS everything, a
Head (or delegate) their office and everything beneath it, an Encoder
their own office. An office outside it is refused (`out_of_scope`).

**Counted live, never from a stored table.** A handful of grouped queries
over the scope, whatever its size:

| Count | Meaning |
|---|---|
| drafting | Draft, not after a return |
| with_head | With the Head |
| in_concurrence | Out for concurrence |
| returned | Draft after a return, by an office or by the Head |
| awaiting_signatures | Locked, awaiting signature, or returned for package defects |
| with_qms | Ready for the IMR, awaiting the approving authority, with the custodian |
| stalled | open requests in their current stage longer than its stall limit - computed now, from when they entered it, with the limits `run_monitoring` uses; never from its notices |
| owed / unmet / overdue | deadline obligations on active deadlines: all, still open, and open past their due date |
| advised | advised revisions still open: obligations that name a manual (the admin advised the office to revise it) |

Requests count under the office that made them; obligations under the
office that owes them.
"""

from collections import Counter
from datetime import datetime, time, timedelta

from django.db.models import Count, F, Max, Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access, lists
from .deadline_tags import tag_rows
from .models import (
    AuditEvent, DeadlineObligation, MonitoringSetting, Office, Proposal,
)
from .monitoring import STAGES, STAGE_LABEL, _entered, _undecided

PROPOSAL_BUCKETS = {
    'drafting': (Proposal.DRAFT,),
    'with_head': (Proposal.WITH_HEAD,),
    'in_concurrence': (Proposal.CONCURRENCE,),
    'returned': (Proposal.DRAFT,),
    'awaiting_signatures': (Proposal.LOCKED, Proposal.AWAITING_SIGNATURE,
                            Proposal.PACKAGE_RETURNED),
    'with_qms': (Proposal.READY_FOR_IMR, Proposal.AWAITING_APPROVAL, Proposal.WITH_CUSTODIAN),
}
OBLIGATION_BUCKETS = ('owed', 'unmet', 'overdue')
BUCKETS = tuple(PROPOSAL_BUCKETS) + ('stalled',) + OBLIGATION_BUCKETS + ('advised',)

# The events that move a draft, and those that mean it came back.
MOVES = (AuditEvent.SENT_TO_HEAD, AuditEvent.RECALLED, AuditEvent.RETURNED_TO_ENCODER,
         AuditEvent.SUBMITTED, AuditEvent.RETURNED, AuditEvent.REDRAFTED)
RETURNS = (AuditEvent.RETURNED_TO_ENCODER, AuditEvent.RETURNED, AuditEvent.REDRAFTED)

# One vocabulary (spec §7.2).
STATUS_WORDS = {
    Proposal.DRAFT: 'Drafting', Proposal.WITH_HEAD: 'With Head',
    Proposal.CONCURRENCE: 'In concurrence', Proposal.LOCKED: 'Awaiting signatures',
    Proposal.AWAITING_SIGNATURE: 'Awaiting signatures',
    Proposal.PACKAGE_RETURNED: 'Awaiting signatures',
    Proposal.READY_FOR_IMR: 'With IMR', Proposal.AWAITING_APPROVAL: 'With IMR',
    Proposal.WITH_CUSTODIAN: 'With custodian',
}



def _refuse(message, reason, status=400):
    return Response({'error': message, 'reason': reason}, status=status)


class Scope:
    """The viewer's offices and the tree, read once per request."""

    def __init__(self, user):
        self.tree = access.office_tree()
        found = access.monitoring_scope(user, self.tree)
        self.everything = found == access.MONITOR_ALL
        self.ids = set(self.tree) if self.everything else found

    def allows(self, office_id):
        return office_id in self.ids

    def roots(self):
        """The top offices of the scope: those whose parent is outside it."""
        return [pk for pk in self.ids if self.tree.get(pk) not in self.ids]

    def subtree(self, office_id):
        return access.descendants(office_id, self.tree) & self.ids

    def proposals(self):
        query = Proposal.objects.all()
        return query if self.everything else query.filter(initiating_office_id__in=self.ids)

    def obligations(self):
        query = DeadlineObligation.objects.filter(deadline__active=True)
        return query if self.everything else query.filter(office_id__in=self.ids)


def _returned(drafts):
    """Drafts whose last move was a return."""
    return drafts.annotate(
        last_move=Max('events__at', filter=Q(events__event__in=MOVES)),
        last_return=Max('events__at', filter=Q(events__event__in=RETURNS)),
    ).filter(last_return__isnull=False, last_return=F('last_move'))


def _stalled(proposals, now):
    """{status: queryset of proposals past their stage's limit}, live."""
    thresholds = MonitoringSetting.thresholds()
    return {status: _entered(proposals.filter(status=status), status)
            .filter(entered__lte=now - timedelta(days=thresholds[stage]))
            for status, (stage, _) in STAGES.items()}


def office_counts(scope, now=None):
    """{office id: Counter of every bucket} for the offices in scope, each
    office its own (not rolled up). About a dozen grouped queries."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    counts = {}

    def add(office_id, bucket, n):
        counts.setdefault(office_id, Counter())[bucket] += n

    proposals = scope.proposals()
    by_status = proposals.values('initiating_office_id', 'status').annotate(n=Count('id'))
    for row in by_status:
        for bucket, statuses in PROPOSAL_BUCKETS.items():
            if bucket != 'returned' and row['status'] in statuses:
                add(row['initiating_office_id'], bucket, row['n'])
    # Chosen per proposal first, then grouped: grouping the annotated query
    # directly would compare the office's latest events, not each draft's.
    returned = proposals.filter(pk__in=_returned(proposals.filter(status=Proposal.DRAFT)).values('pk'))
    for row in returned.values('initiating_office_id').annotate(n=Count('id')):
        add(row['initiating_office_id'], 'returned', row['n'])
        add(row['initiating_office_id'], 'drafting', -row['n'])
    for query in _stalled(proposals, now).values():
        stalled = proposals.filter(pk__in=query.values('pk'))
        for row in stalled.values('initiating_office_id').annotate(n=Count('id')):
            add(row['initiating_office_id'], 'stalled', row['n'])
    for row in scope.obligations().values('office_id').annotate(
            owed=Count('id'),
            unmet=Count('id', filter=Q(state=DeadlineObligation.OPEN)),
            overdue=Count('id', filter=Q(state=DeadlineObligation.OPEN,
                                         deadline__due_on__lt=today)),
            advised=Count('id', filter=Q(state=DeadlineObligation.OPEN, manual__isnull=False))):
        for bucket in OBLIGATION_BUCKETS + ('advised',):
            add(row['office_id'], bucket, row[bucket])
    return counts


def _summed(counts, office_ids):
    total = Counter()
    for pk in office_ids:
        total.update(counts.get(pk, Counter()))
    return {bucket: total.get(bucket, 0) for bucket in BUCKETS}


def _open_total(c):
    return sum(c.get(b, 0) for b in PROPOSAL_BUCKETS)


def chart(scope, counts=None, mode='pending', period='month', now=None):
    """Bars per office in scope, highest first: open requests by stage
    (pending), or changes made effective in the period (approved), counted
    by the office that made them. Offices with none are counted, not
    listed."""
    names = dict(Office.objects.filter(pk__in=scope.ids).values_list('pk', 'name'))
    if mode == 'approved':
        start, end = period_bounds(period, now)
        events = AuditEvent.objects.filter(event=AuditEvent.MADE_EFFECTIVE, at__gte=start, at__lt=end)
        if not scope.everything:
            events = events.filter(proposal__initiating_office_id__in=scope.ids)
        values = dict(events.values('proposal__initiating_office_id')
                      .annotate(n=Count('proposal', distinct=True))
                      .values_list('proposal__initiating_office_id', 'n'))
        bars = [{'office_id': pk, 'office': names.get(pk, '?'), 'value': n, 'stages': {}}
                for pk, n in values.items() if n]
    else:
        counts = counts if counts is not None else office_counts(scope, now)
        bars = [{'office_id': pk, 'office': names.get(pk, '?'), 'value': _open_total(c),
                 'stages': {b: c.get(b, 0) for b in PROPOSAL_BUCKETS}}
                for pk, c in counts.items() if _open_total(c)]
    bars.sort(key=lambda b: (-b['value'], b['office']))
    return {'mode': mode, 'bars': bars, 'none': len(scope.ids) - len(bars)}


PERIODS = ('month', 'year', 'last_year')


def period_bounds(period, now=None):
    """[start, end) in local time: this month, this year, or last year."""
    today = timezone.localdate(now)
    if period == 'year':
        first, after = today.replace(month=1, day=1), today.replace(year=today.year + 1, month=1, day=1)
    elif period == 'last_year':
        first, after = today.replace(year=today.year - 1, month=1, day=1), today.replace(month=1, day=1)
    else:
        first = today.replace(day=1)
        after = (first + timedelta(days=32)).replace(day=1)
    zone = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(first, time.min), zone),
            timezone.make_aware(datetime.combine(after, time.min), zone))


# ─── Endpoints ───────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def overview(request):
    """Counts first; every count opens its list. The offices chart is
    `offices_chart`, loaded beside it."""
    scope = Scope(request.user)
    if not scope.ids:
        return Response({'scope': 'none', 'counts': None, 'chart': None})
    counts = office_counts(scope)
    return Response({
        'scope': 'all' if scope.everything else 'offices',
        'offices_in_scope': len(scope.ids),
        'counts': _summed(counts, scope.ids),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def offices_chart(request):
    """The offices bar chart on its own: `mode=pending` (default) or
    `approved`, with `period=month|year|last_year` for approved."""
    scope = Scope(request.user)
    mode = request.query_params.get('mode') or 'pending'
    period = request.query_params.get('period') or 'month'
    if mode not in ('pending', 'approved') or period not in PERIODS:
        return _refuse('Choose pending or approved, and this month, this year or last year.',
                       'invalid_filter')
    if not scope.ids:
        return Response({'mode': mode, 'bars': [], 'none': 0, 'period': period})
    return Response({**chart(scope, mode=mode, period=period), 'period': period})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def offices(request):
    """One level of the tree: the children of `parent` in scope (or the
    scope's top offices), each rolled up from everything beneath it in
    scope, most overdue first, then most stalled, then by name."""
    scope = Scope(request.user)
    raw = request.query_params.get('parent')
    if raw:
        if not raw.isdigit() or not scope.allows(int(raw)):
            return _refuse('That office is outside what you can monitor.', 'out_of_scope', 403)
        level = [pk for pk in scope.ids if scope.tree.get(pk) == int(raw)]
    else:
        level = scope.roots()
    counts = office_counts(scope)
    rows = []
    offices_by_id = Office.objects.in_bulk(level)
    for pk in level:
        below = scope.subtree(pk)
        rows.append({
            'id': pk, 'name': offices_by_id[pk].name, 'active': offices_by_id[pk].is_active,
            'has_children': len(below) > 1,
            'own': _summed(counts, [pk]),
            'counts': _summed(counts, below),
        })
    rows.sort(key=lambda r: (-r['counts']['overdue'], -r['counts']['stalled'], r['name']))
    page = lists.page_number(request.query_params)
    start = (page - 1) * lists.PAGE_SIZE
    return Response({'offices': rows[start:start + lists.PAGE_SIZE], 'count': len(rows),
                     'page': page, 'pages': max(1, -(-len(rows) // lists.PAGE_SIZE))})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def items(request):
    """The rows behind a count: requests, or deadline obligations, for the
    whole scope or one office (with `subtree=1`, and everything beneath)."""
    scope = Scope(request.user)
    bucket = request.query_params.get('bucket') or 'open'
    if bucket not in BUCKETS + ('open',):
        return _refuse('Unknown list.', 'unknown_bucket')
    office_ids = scope.ids
    raw = request.query_params.get('office')
    if raw:
        if not raw.isdigit() or not scope.allows(int(raw)):
            return _refuse('That office is outside what you can monitor.', 'out_of_scope', 403)
        office_ids = (scope.subtree(int(raw)) if request.query_params.get('subtree') == '1'
                      else {int(raw)})
    page = lists.page_number(request.query_params)
    if bucket == 'advised':
        result = _advised_page(office_ids, page)
    elif bucket in OBLIGATION_BUCKETS:
        result = _obligation_page(office_ids, bucket, page)
    else:
        result = _proposal_page(office_ids, bucket, page)
    # Every row naming a manual carries its deadline tag (spec §6.7),
    # computed for the page at once.
    tag_rows(request.user, result['rows'])
    return Response(result)


def _proposal_page(office_ids, bucket, page):
    now = timezone.now()
    query = Proposal.objects.filter(initiating_office_id__in=office_ids).exclude(
        status__in=Proposal.CLOSED_STATUSES)
    if bucket == 'stalled':
        ids = set()
        for q in _stalled(query, now).values():
            ids |= set(q.values_list('pk', flat=True))
        query = query.filter(pk__in=ids)
    elif bucket in PROPOSAL_BUCKETS:
        query = query.filter(status__in=PROPOSAL_BUCKETS[bucket])
        returned = _returned(query.filter(status=Proposal.DRAFT)).values('pk')
        if bucket == 'returned':
            query = query.filter(pk__in=returned)
        elif bucket == 'drafting':
            query = query.exclude(pk__in=returned)
    query = query.select_related('manual', 'initiating_office').order_by('updated_at', 'pk')
    rows, paging = lists.page_of(query, page)
    return {**paging, 'kind': 'proposals', 'rows': _proposal_rows(rows, now)}


def _proposal_rows(proposals, now):
    """Who holds each request now, for how long, and what it waits on."""
    thresholds = MonitoringSetting.thresholds()
    entered = {}
    by_status = {}
    for p in proposals:
        by_status.setdefault(p.status, []).append(p.pk)
    for status, ids in by_status.items():
        if status in STAGES:
            entered.update(_entered(Proposal.objects.filter(pk__in=ids), status)
                           .values_list('pk', 'entered'))
        else:
            entered.update(Proposal.objects.filter(pk__in=ids).annotate(
                entered=Max('events__at', filter=Q(events__event__in=MOVES + (AuditEvent.CREATED,)))
            ).values_list('pk', 'entered'))
    waiting = _undecided([p for p in proposals if p.status == Proposal.CONCURRENCE])
    returned_by = dict(
        AuditEvent.objects.filter(proposal__in=[p for p in proposals if p.status == Proposal.DRAFT],
                                  event__in=(AuditEvent.RETURNED, AuditEvent.RETURNED_TO_ENCODER))
        .order_by('proposal_id', 'at').values_list('proposal_id', 'office_name_at_time'))
    rows = []
    for p in proposals:
        since = entered.get(p.pk) or p.updated_at
        days = (now - since).days
        office = p.initiating_office.name
        if p.status == Proposal.CONCURRENCE:
            names = [o.name for o in waiting.get(p.pk, [])]
            holder, waits = ', '.join(names) or '—', f'Concurrence: {", ".join(names)}'
        elif p.status == Proposal.WITH_HEAD:
            holder, waits = f'{office} — Head', 'The Head to submit or return it'
        elif p.status == Proposal.DRAFT:
            holder, waits = office, 'The office to send it'
        elif p.status in (Proposal.LOCKED, Proposal.AWAITING_SIGNATURE, Proposal.PACKAGE_RETURNED):
            holder, waits = office, 'Signed copies'
        elif p.status == Proposal.READY_FOR_IMR:
            holder, waits = 'IMR', 'The IMR to accept or deny'
        elif p.status == Proposal.AWAITING_APPROVAL:
            holder, waits = 'IMR', 'The approving authority to sign'
        else:
            holder, waits = 'Document Custodian', 'The custodian to make it effective'
        word = STATUS_WORDS.get(p.status, p.get_status_display())
        if p.status == Proposal.DRAFT and p.pk in returned_by:
            word = f'Returned by {returned_by[p.pk]}'
        stage = STAGES.get(p.status, (None,))[0]
        rows.append({
            'proposal_id': p.pk, 'manual_id': p.manual_id, 'manual': p.manual.title,
            'office': office,
            'status': word, 'holder': holder, 'days': days, 'waiting_on': waits,
            'stalled': bool(stage and days >= thresholds[stage]),
            'limit': thresholds.get(stage) if stage else None,
            'stage': STAGE_LABEL.get(stage),
        })
    return rows


def _obligation_page(office_ids, bucket, page):
    today = timezone.localdate()
    query = DeadlineObligation.objects.filter(deadline__active=True, office_id__in=office_ids)
    if bucket in ('unmet', 'overdue'):
        query = query.filter(state=DeadlineObligation.OPEN)
    if bucket == 'overdue':
        query = query.filter(deadline__due_on__lt=today)
    query = query.select_related('deadline__type', 'office', 'manual').order_by(
        'deadline__due_on', 'office__name', 'pk')
    rows, paging = lists.page_of(query, page)
    return {**paging, 'kind': 'obligations', 'rows': [{
        'obligation_id': ob.pk, 'deadline': ob.deadline.title, 'type': ob.deadline.type.name,
        'due_on': ob.deadline.due_on, 'office': ob.office.name,
        'manual': ob.manual.title if ob.manual_id else None,
        'manual_id': ob.manual_id,
        'state': ob.get_state_display(), 'met': ob.state != DeadlineObligation.OPEN,
        'days_late': max((today - ob.deadline.due_on).days, 0)
        if ob.state == DeadlineObligation.OPEN else 0,
    } for ob in rows]}


def _advised_page(office_ids, page):
    """Advised revisions (spec §7.3.6): manuals the admin has advised an
    office to revise - obligations that name a manual - still open first,
    then by due date. Each row says where the office has got: not started,
    its request's stage and holder, or met."""
    now = timezone.now()
    today = timezone.localdate(now)
    query = DeadlineObligation.objects.filter(
        deadline__active=True, manual__isnull=False, office_id__in=office_ids,
    ).select_related('deadline__type', 'office', 'manual').annotate(
        still_open=Count('id', filter=Q(state=DeadlineObligation.OPEN)),
    ).order_by('-still_open', 'deadline__due_on', 'office__name', 'pk')
    rows, paging = lists.page_of(query, page)
    pairs = {(ob.manual_id, ob.office_id) for ob in rows if ob.state == DeadlineObligation.OPEN}
    working = {}
    if pairs:
        open_requests = Proposal.objects.filter(
            manual_id__in={m for m, _ in pairs}, initiating_office_id__in={o for _, o in pairs},
        ).exclude(status__in=Proposal.CLOSED_STATUSES).select_related('manual', 'initiating_office')
        found = [p for p in open_requests if (p.manual_id, p.initiating_office_id) in pairs]
        by_id = {r['proposal_id']: r for r in _proposal_rows(found, now)}
        working = {(p.manual_id, p.initiating_office_id): by_id[p.pk] for p in found}
    out = []
    for ob in rows:
        is_open = ob.state == DeadlineObligation.OPEN
        request_row = working.get((ob.manual_id, ob.office_id))
        if not is_open:
            status, holder = ob.get_state_display(), '—'
        elif request_row:
            status, holder = request_row['status'], request_row['holder']
        else:
            status, holder = 'Not started', ob.office.name
        out.append({
            'obligation_id': ob.pk, 'manual_id': ob.manual_id, 'manual': ob.manual.title,
            'office': ob.office.name,
            'deadline': ob.deadline.title, 'type': ob.deadline.type.name,
            'due_on': ob.deadline.due_on, 'priority': ob.priority,
            'status': status, 'holder': holder, 'met': not is_open,
            'days_late': max((today - ob.deadline.due_on).days, 0) if is_open else 0,
            'proposal_id': request_row['proposal_id'] if request_row else None,
        })
    return {**paging, 'kind': 'advised', 'rows': out}
