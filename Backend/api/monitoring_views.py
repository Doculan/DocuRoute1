"""Monitoring (v4.2 Phase 4, step 2): read-only, scoped, counted live.

    GET monitoring/overview/                       counts for the viewer's scope, and the offices chart
    GET monitoring/offices/?parent=<id>&page=      one level of the office tree, rolled up from beneath
    GET monitoring/items/?bucket=&office=&subtree=&page=   the rows behind a count, 50 a page

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

Requests count under the office that made them; obligations under the
office that owes them.
"""

from collections import Counter
from datetime import timedelta

from django.db.models import Count, F, Max, Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access, lists
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
BUCKETS = tuple(PROPOSAL_BUCKETS) + ('stalled',) + OBLIGATION_BUCKETS

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

CHART_TOP = 15


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
                                         deadline__due_on__lt=today))):
        for bucket in OBLIGATION_BUCKETS:
            add(row['office_id'], bucket, row[bucket])
    return counts


def _summed(counts, office_ids):
    total = Counter()
    for pk in office_ids:
        total.update(counts.get(pk, Counter()))
    return {bucket: total.get(bucket, 0) for bucket in BUCKETS}


def _open_total(c):
    return sum(c.get(b, 0) for b in PROPOSAL_BUCKETS)


# ─── Endpoints ───────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def overview(request):
    """Counts first; every count opens its list. The offices chart: open
    requests per office in scope, highest first, top 15, the rest counted."""
    scope = Scope(request.user)
    if not scope.ids:
        return Response({'scope': 'none', 'counts': None, 'chart': None})
    counts = office_counts(scope)
    names = dict(Office.objects.filter(pk__in=scope.ids).values_list('pk', 'name'))
    bars = sorted(((names.get(pk, '?'), pk, _open_total(c)) for pk, c in counts.items()
                   if _open_total(c)), key=lambda b: (-b[2], b[0]))
    return Response({
        'scope': 'all' if scope.everything else 'offices',
        'offices_in_scope': len(scope.ids),
        'counts': _summed(counts, scope.ids),
        'chart': {
            'bars': [{'office_id': pk, 'office': name, 'open': n,
                      'stages': {b: counts[pk].get(b, 0) for b in PROPOSAL_BUCKETS}}
                     for name, pk, n in bars[:CHART_TOP]],
            'more': max(len(bars) - CHART_TOP, 0),
            'none': len(scope.ids) - len(bars),
        },
    })


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
    if bucket in OBLIGATION_BUCKETS:
        return Response(_obligation_page(office_ids, bucket, page))
    return Response(_proposal_page(office_ids, bucket, page))


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
            'proposal_id': p.pk, 'manual': p.manual.title, 'office': office,
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
        'state': ob.get_state_display(), 'met': ob.state != DeadlineObligation.OPEN,
        'days_late': max((today - ob.deadline.due_on).days, 0)
        if ob.state == DeadlineObligation.OPEN else 0,
    } for ob in rows]}
