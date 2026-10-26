"""Deadline-first Proposals for the staff portal (spec §8.3).

    GET proposals/board/                       the sections with their counts (empty ones left out)
    GET proposals/board/?section=<key>&page=   one page of 50 of one section

Filters, on either: `deadline` (id), `series` (id), `manual` (title text),
`status` (a §7.2 word key, or `not_started`), `overdue=1`.

| Section | What it holds |
|---|---|
| due | Due for submission: every open deadline obligation of the viewer's offices, ranked overdue (most late first), due soonest (within the reminder window), priority, then the rest; with the office's request on that manual if it has one, or "Not started" |
| awaiting | Awaiting your office: concurrence requests the office has not decided on |
| returned | Returned to you: drafts back after a return, and packages the custodian returned |
| mine | From my office: everything else the office started, open first |
| involving | Other offices' requests the office concurs on, once they no longer wait on it |

**Each request appears once**: a request shown under Due for submission
or Returned is not repeated under From my office.

**One action per row**, the one that fits the viewer, and never one they
cannot take: it opens the request, where the step itself is done (or, for
Not started, starts one with the password).
"""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access, lists
from .deadline_tags import tag_rows
from .models import DeadlineObligation, Proposal, ProposalParticipant
from .monitoring_views import _proposal_rows, _returned

SECTIONS = [
    ('due', 'Due for submission'),
    ('awaiting', 'Awaiting your office'),
    ('returned', 'Returned to you'),
    ('mine', 'From my office'),
    ('involving', "Other offices' requests"),
]
STATUS_KEYS = {
    'drafting': (Proposal.DRAFT,), 'with_head': (Proposal.WITH_HEAD,),
    'in_concurrence': (Proposal.CONCURRENCE,),
    'awaiting_signatures': (Proposal.LOCKED, Proposal.AWAITING_SIGNATURE, Proposal.PACKAGE_RETURNED),
    'with_qms': (Proposal.READY_FOR_IMR, Proposal.AWAITING_APPROVAL, Proposal.WITH_CUSTODIAN),
    'closed': Proposal.CLOSED_STATUSES,
}
SOON_DAYS = 30      # within the longest usual reminder: "due soonest"


class Viewer:
    """The viewer's offices, and what they may do in each."""

    def __init__(self, user):
        from .concurrence_views import _encoder_of, _head_of
        self.user = user
        self.offices = access.current_offices(user)
        self.ids = [o.pk for o in self.offices]
        self.heads = {o.pk for o in self.offices if _head_of(user, o) is not None}
        self.encoders = {o.pk for o in self.offices if _encoder_of(user, o) is not None}


def _filters(params):
    f = {k: (params.get(k) or '').strip() for k in ('deadline', 'series', 'manual', 'status', 'overdue')}
    for key in ('deadline', 'series'):
        if f[key] and not f[key].isdigit():
            f[key] = ''
    if f['status'] not in tuple(STATUS_KEYS) + ('returned', 'not_started', ''):
        f['status'] = ''
    return f


def _obligation_q(f, today, prefix=''):
    q = Q(**{f'{prefix}state': DeadlineObligation.OPEN, f'{prefix}deadline__active': True})
    if f['deadline']:
        q &= Q(**{f'{prefix}deadline_id': int(f['deadline'])})
    if f['overdue']:
        q &= Q(**{f'{prefix}deadline__due_on__lt': today})
    return q


def _proposal_filter(query, f, viewer, today):
    if f['series']:
        query = query.filter(manual__series_id=int(f['series']))
    if f['manual']:
        query = query.filter(manual__title__icontains=f['manual'])
    if f['status'] == 'returned':
        query = query.filter(pk__in=_returned(query.filter(status=Proposal.DRAFT)).values('pk'))
    elif f['status'] == 'not_started':
        query = query.none()
    elif f['status']:
        query = query.filter(status__in=STATUS_KEYS[f['status']])
    if f['deadline'] or f['overdue']:
        owed = DeadlineObligation.objects.filter(_obligation_q(f, today), office_id__in=viewer.ids)
        query = query.filter(manual_id__in=owed.values('manual_id'),
                             initiating_office_id__in=owed.values('office_id'))
    return query


# ─── Sections ────────────────────────────────────────────────

def _due(viewer, f, today):
    """[(obligation, request or None)], ranked."""
    query = DeadlineObligation.objects.filter(_obligation_q(f, today), office_id__in=viewer.ids) \
        .select_related('deadline__type', 'manual__series', 'office')
    if f['series']:
        query = query.filter(manual__series_id=int(f['series']))
    if f['manual']:
        query = query.filter(manual__title__icontains=f['manual'])
    obligations = list(query)
    open_requests = {}
    for p in Proposal.objects.filter(
            initiating_office_id__in=viewer.ids,
            manual_id__in={ob.manual_id for ob in obligations if ob.manual_id},
    ).exclude(status__in=Proposal.CLOSED_STATUSES).select_related('manual__series', 'initiating_office'):
        open_requests[(p.manual_id, p.initiating_office_id)] = p
    pairs = [(ob, open_requests.get((ob.manual_id, ob.office_id))) for ob in obligations]
    if f['status'] == 'not_started':
        pairs = [(ob, p) for ob, p in pairs if p is None]
    elif f['status']:
        allowed = _proposal_filter(Proposal.objects.filter(
            pk__in=[p.pk for _, p in pairs if p]), f, viewer, today)
        keep = set(allowed.values_list('pk', flat=True))
        pairs = [(ob, p) for ob, p in pairs if p and p.pk in keep]

    def rank(pair):
        ob = pair[0]
        late = (today - ob.deadline.due_on).days
        if late > 0:
            return (0, -late, ob.pk)
        if ob.deadline.due_on <= today + timedelta(days=SOON_DAYS):
            return (1, ob.deadline.due_on, ob.pk)
        if ob.priority:
            return (2, ob.deadline.due_on, ob.pk)
        return (3, ob.deadline.due_on, ob.pk)
    # One row per manual: an office that owes a manual under two deadlines
    # sees it once, under the more urgent one.
    ranked, seen = [], set()
    for ob, p in sorted(pairs, key=rank):
        if ob.manual_id is not None:
            if (ob.manual_id, ob.office_id) in seen:
                continue
            seen.add((ob.manual_id, ob.office_id))
        ranked.append((ob, p))
    return ranked


def _section_query(key, viewer, f, today, shown_ids):
    """The proposals of a request section, filtered, or None for `due`."""
    from .action_views import awaiting_pairs
    mine = Proposal.objects.filter(initiating_office_id__in=viewer.ids)
    if key == 'awaiting':
        query = Proposal.objects.filter(pk__in=awaiting_pairs(viewer.ids).values('proposal'))
    elif key == 'returned':
        query = mine.filter(Q(pk__in=_returned(mine.filter(status=Proposal.DRAFT)).values('pk'))
                            | Q(status=Proposal.PACKAGE_RETURNED))
    elif key == 'mine':
        returned = mine.filter(Q(pk__in=_returned(mine.filter(status=Proposal.DRAFT)).values('pk'))
                               | Q(status=Proposal.PACKAGE_RETURNED))
        query = mine.exclude(pk__in=returned.values('pk'))
    else:   # involving
        query = Proposal.objects.filter(pk__in=ProposalParticipant.objects.filter(
            office_id__in=viewer.ids, role=ProposalParticipant.CONCURRING,
        ).values('proposal')).exclude(pk__in=awaiting_pairs(viewer.ids).values('proposal'))
    query = query.exclude(pk__in=shown_ids)
    return _proposal_filter(query, f, viewer, today)


# ─── Rows ────────────────────────────────────────────────────

def _action(viewer, p, status_word):
    """(key, label) of the one action that fits the viewer, or None."""
    from .concurrence_views import head_may_submit_draft
    office = p.initiating_office_id
    head, encoder = office in viewer.heads, office in viewer.encoders
    if p.status == Proposal.DRAFT:
        if status_word.startswith('Returned'):
            if status_word == 'Returned by the Head' and head and not encoder:
                return None
            return ('open', 'Redraft') if head or encoder else None
        if encoder:
            return ('open', 'Continue')
        if head:
            return ('open', 'Submit' if head_may_submit_draft(viewer.user, p) else 'Continue')
        return None
    if p.status == Proposal.WITH_HEAD:
        if head:
            return ('open', 'Submit or return')
        return ('open', 'Recall') if encoder else None
    if p.status in (Proposal.AWAITING_SIGNATURE, Proposal.PACKAGE_RETURNED):
        return ('open', 'Upload scans') if head or encoder else None
    return None


def _rows(viewer, proposals, obligation_for=None):
    """Rows for requests: status, holder and days as Monitoring shows them,
    the deadline the office owes on that manual, and the action."""
    now = timezone.now()
    today = timezone.localdate(now)
    base = {r['proposal_id']: r for r in _proposal_rows(proposals, now)}
    owed = obligation_for or {}
    if obligation_for is None and proposals:
        for ob in DeadlineObligation.objects.filter(
                state=DeadlineObligation.OPEN, deadline__active=True,
                manual_id__in={p.manual_id for p in proposals},
                office_id__in={p.initiating_office_id for p in proposals},
        ).select_related('deadline__type').order_by('deadline__due_on'):
            owed.setdefault((ob.manual_id, ob.office_id), ob)
    rows = []
    for p in proposals:
        r = base[p.pk]
        ob = owed.get((p.manual_id, p.initiating_office_id))
        if p.status in Proposal.CLOSED_STATUSES:
            r = {**r, 'status': p.get_status_display(), 'holder': '—', 'waiting_on': ''}
        # The concurring office's own view: its Head decides.
        mine_to_decide = (p.status == Proposal.CONCURRENCE
                          and any(o in viewer.heads for o in _undecided_ids(p)))
        action = ('open', 'Concur or return') if mine_to_decide else _action(viewer, p, r['status'])
        rows.append({
            'proposal_id': p.pk, 'obligation_id': ob.pk if ob else None,
            'manual_id': p.manual_id, 'manual': p.manual.title,
            'series': p.manual.series.code if p.manual.series_id else None,
            'office': p.initiating_office.name,
            'due': _deadline(ob, today), 'status': r['status'], 'holder': r['holder'],
            'days': r['days'], 'waiting_on': r['waiting_on'], 'stalled': r['stalled'],
            'action': {'kind': action[0], 'label': action[1]} if action else None,
        })
    return rows


def _undecided_ids(p):
    return getattr(p, '_undecided', [])


def _deadline(ob, today):
    if ob is None:
        return None
    late = (today - ob.deadline.due_on).days
    return {'title': ob.deadline.title, 'type': ob.deadline.type.name,
            'due_on': ob.deadline.due_on, 'days_late': max(late, 0),
            'days_left': max(-late, 0), 'priority': ob.priority}


def _due_rows(viewer, pairs, today):
    requests = [p for _, p in pairs if p is not None]
    _mark_undecided(requests, viewer)
    by_pk = {r['proposal_id']: r for r in _rows(
        viewer, requests, {(p.manual_id, p.initiating_office_id): ob for ob, p in pairs if p})}
    rows = []
    for ob, p in pairs:
        if p is not None:
            rows.append(by_pk[p.pk])
            continue
        can_start = ob.office_id in viewer.heads or ob.office_id in viewer.encoders
        rows.append({
            'proposal_id': None, 'obligation_id': ob.pk,
            'manual_id': ob.manual_id, 'manual': ob.manual.title if ob.manual_id else None,
            'series': ob.manual.series.code if ob.manual_id and ob.manual.series_id else None,
            'office': ob.office.name, 'due': _deadline(ob, today),
            'status': 'Not started', 'holder': ob.office.name, 'days': None,
            'waiting_on': ('' if ob.manual_id else 'Any proposal your office submits meets it'),
            'stalled': False,
            'action': ({'kind': 'start', 'label': 'Start'} if can_start and ob.manual_id else None),
        })
    return rows


def _mark_undecided(proposals, viewer):
    """For requests in concurrence: which of the viewer's offices still
    have to decide (from the same aggregate as Needs your action)."""
    from .action_views import awaiting_pairs
    ids = [p.pk for p in proposals if p.status == Proposal.CONCURRENCE]
    pending = {}
    if ids:
        for proposal_id, office_id in awaiting_pairs(viewer.ids).filter(
                proposal_id__in=ids).values_list('proposal_id', 'office_id'):
            pending.setdefault(proposal_id, []).append(office_id)
    for p in proposals:
        p._undecided = pending.get(p.pk, [])


def _options(viewer):
    """The filter choices: the deadlines the viewer's offices owe, and
    the series of the manuals they owe or have proposed on."""
    from .models import ManualSeries
    deadlines = (DeadlineObligation.objects.filter(
        office_id__in=viewer.ids, deadline__active=True,
    ).values_list('deadline_id', 'deadline__title').distinct().order_by('deadline__due_on'))
    series = ManualSeries.objects.filter(
        Q(documents__obligations__office_id__in=viewer.ids)
        | Q(documents__proposals__initiating_office_id__in=viewer.ids),
    ).values_list('pk', 'code').distinct().order_by('code')
    return {'deadlines': [{'id': pk, 'title': t} for pk, t in deadlines],
            'series': [{'id': pk, 'code': c} for pk, c in series]}


# ─── The endpoint ────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def board(request):
    viewer = Viewer(request.user)
    if not viewer.ids:
        return Response({'sections': [], 'reason': 'no_office'})
    today = timezone.localdate()
    f = _filters(request.query_params)
    key = request.query_params.get('section')
    page = lists.page_number(request.query_params) or 1
    due = _due(viewer, f, today)
    due_ids = [p.pk for _, p in due if p is not None]

    if key is None:
        counts = {'due': len(due)}
        shown = list(due_ids)
        for name, _ in SECTIONS[1:]:
            query = _section_query(name, viewer, f, today, shown)
            counts[name] = query.count()
            if name in ('returned',):
                shown += list(query.values_list('pk', flat=True))
        sections = [{'key': k, 'title': t, 'count': counts[k]} for k, t in SECTIONS if counts[k]]
        overdue = sum(1 for ob, _ in due if ob.deadline.due_on < today)
        return Response({'sections': sections, 'overdue': overdue,
                         'open': sections[0]['key'] if sections else None,
                         'options': _options(viewer)})

    if key not in dict(SECTIONS):
        return lists.refuse('Unknown section.', 'invalid_section')
    if key == 'due':
        start = (page - 1) * lists.PAGE_SIZE
        rows = _due_rows(viewer, due[start:start + lists.PAGE_SIZE], today)
        total = len(due)
        paging = {'count': total, 'page': page, 'page_size': lists.PAGE_SIZE,
                  'pages': max(1, -(-total // lists.PAGE_SIZE))}
        return Response({**paging, 'rows': tag_rows(request.user, rows)})

    shown = list(due_ids)
    if key in ('mine', 'involving'):
        shown += list(_section_query('returned', viewer, f, today, due_ids).values_list('pk', flat=True))
    query = _section_query(key, viewer, f, today, shown).select_related(
        'manual__series', 'initiating_office')
    order = ('-updated_at', '-pk')
    if key == 'mine':
        from django.db.models import Case, IntegerField, Value, When
        query = query.annotate(closed=Case(When(status__in=Proposal.CLOSED_STATUSES, then=Value(1)),
                                           default=Value(0), output_field=IntegerField()))
        order = ('closed', '-updated_at', '-pk')
    proposals, paging = lists.page_of(query.order_by(*order), page)
    _mark_undecided(proposals, viewer)
    return Response({**paging, 'rows': tag_rows(request.user, _rows(viewer, proposals))})
