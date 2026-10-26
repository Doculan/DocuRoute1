"""History (spec §8.4): what is done, read-only.

    GET  history/                          the groups: years, and the months of each, with counts by outcome
    GET  history/?year=&month=&page=       one month's rows, 50 a page
    POST history/export/                   {format: csv|pdf, ...the same filters}

**What it holds:** every closed request - Effective, Denied, Withdrawn -
and every "Reviewed, no change". Superseded versions live in each
request's audit trail, not here.

**Filters:** `date_on` = `closed` (default) or `submitted`, with `from`
and `to`; `outcome` (effective, denied, withdrawn, reviewed); `office`;
`series`; `dcr` (part of the number).

**Scope** (the same rule as Monitoring, `access.monitoring_scope`): the
admin and QMS see everything; a Head (or delegate) the office and every
office beneath it; an Encoder their own office. `view=mine` (default) is
what those offices initiated or reviewed; `view=participated` is what
they concurred on or sign for, initiated elsewhere. An office outside
scope is refused (`out_of_scope`).

**Exports** reuse the audit block's writers (UTF-8 marker, formula-safe
cells; PDF with page numbers). They print their filters, scope, the
exporter's position and the time; they are not logged, because the
report log records one request per row.
"""

from collections import Counter
from datetime import date, datetime, time, timedelta

from django.db.models import Count, F, Max, Min, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access, lists
from .models import AuditEvent, ManualReview, Office, Proposal, ProposalParticipant

OUTCOMES = {
    Proposal.EFFECTIVE: 'effective', Proposal.DENIED: 'denied', Proposal.WITHDRAWN: 'withdrawn',
}
OUTCOME_WORDS = {'effective': 'Effective', 'denied': 'Denied', 'withdrawn': 'Withdrawn',
                 'reviewed': 'Reviewed, no change'}
CLOSING = (AuditEvent.MADE_EFFECTIVE, AuditEvent.IMR_DENIED, AuditEvent.WITHDRAWN)
RETURNS = (AuditEvent.RETURNED, AuditEvent.RETURNED_TO_ENCODER)
EXPORT_CAP = 5000


def _refuse(message, reason, status=400):
    return Response({'error': message, 'reason': reason}, status=status)


def _day(raw):
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


class Query:
    """The viewer's scope and filters, turned into two querysets: closed
    requests and reviews, each with the date it is grouped by."""

    def __init__(self, request, data=None):
        params = data if data is not None else request.query_params
        self.user = request.user
        found = access.monitoring_scope(request.user)
        self.everything = found == access.MONITOR_ALL
        self.scope = None if self.everything else set(found)
        self.view = params.get('view') if params.get('view') in ('mine', 'participated') else 'mine'
        self.date_on = 'submitted' if params.get('date_on') == 'submitted' else 'closed'
        self.start, self.end = _day(params.get('from') or ''), _day(params.get('to') or '')
        self.outcome = params.get('outcome') if params.get('outcome') in OUTCOME_WORDS else ''
        self.series = int(params['series']) if str(params.get('series') or '').isdigit() else None
        self.dcr = (params.get('dcr') or '').strip()
        self.error = None
        office = str(params.get('office') or '')
        self.office = int(office) if office.isdigit() else None
        if self.office is not None and self.scope is not None and self.office not in self.scope:
            self.error = _refuse('That office is outside what you can see.', 'out_of_scope', 403)
        if self.scope is not None and not self.scope:
            self.error = _refuse('You hold no post in an office.', 'no_office', 403)

    def _bounds(self, field):
        q = Q()
        zone = timezone.get_current_timezone()
        if self.start:
            q &= Q(**{f'{field}__gte': timezone.make_aware(datetime.combine(self.start, time.min), zone)})
        if self.end:
            q &= Q(**{f'{field}__lt': timezone.make_aware(
                datetime.combine(self.end, time.min), zone) + timedelta(days=1)})
        return q

    def requests(self):
        query = Proposal.objects.filter(status__in=OUTCOMES).annotate(
            closed_at=Max('events__at', filter=Q(events__event__in=CLOSING)),
            submitted_at=Min('versions__submitted_at'),
        )
        offices = {self.office} if self.office else self.scope
        if offices is not None:
            if self.view == 'mine':
                query = query.filter(initiating_office_id__in=offices)
            else:
                query = query.filter(pk__in=ProposalParticipant.objects.filter(
                    office_id__in=offices).values('proposal')).exclude(
                    initiating_office_id__in=offices)
        if self.outcome:
            if self.outcome == 'reviewed':
                return query.none()
            query = query.filter(status=[k for k, v in OUTCOMES.items() if v == self.outcome][0])
        if self.series:
            query = query.filter(manual__series_id=self.series)
        if self.dcr:
            query = query.filter(dcr_number__icontains=self.dcr)
        field = 'closed_at' if self.date_on == 'closed' else 'submitted_at'
        query = query.filter(self._bounds(field)).annotate(on=F(field))
        return query.filter(on__isnull=False)

    def reviews(self):
        if (self.outcome and self.outcome != 'reviewed') or self.view == 'participated' or self.dcr:
            return ManualReview.objects.none().annotate(on=F('at'))
        query = ManualReview.objects.all()
        offices = {self.office} if self.office else self.scope
        if offices is not None:
            query = query.filter(office_id__in=offices)
        if self.series:
            query = query.filter(manual__series_id=self.series)
        return query.filter(self._bounds('at')).annotate(on=F('at'))


def _bucket(moment):
    local = timezone.localtime(moment)
    return local.year, local.month


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def history(request):
    q = Query(request)
    if q.error:
        return q.error
    year, month = request.query_params.get('year'), request.query_params.get('month')
    if year and month:
        if not (year.isdigit() and month.isdigit()):
            return _refuse('Choose a year and a month.', 'invalid_month')
        return Response(_month(q, int(year), int(month), lists.page_number(request.query_params) or 1))

    counts = {}
    for moment, status in q.requests().values_list('on', 'status'):
        counts.setdefault(_bucket(moment), Counter())[OUTCOMES[status]] += 1
    for (moment,) in q.reviews().values_list('on'):
        counts.setdefault(_bucket(moment), Counter())['reviewed'] += 1
    years = {}
    for (y, m), c in counts.items():
        entry = years.setdefault(y, {'year': y, 'total': 0, 'outcomes': Counter(), 'months': []})
        entry['total'] += sum(c.values())
        entry['outcomes'].update(c)
        entry['months'].append({'month': m, 'total': sum(c.values()), 'outcomes': dict(c)})
    for entry in years.values():
        entry['outcomes'] = dict(entry['outcomes'])
        entry['months'].sort(key=lambda e: -e['month'])
    return Response({
        'scope': 'all' if q.everything else 'offices', 'view': q.view, 'date_on': q.date_on,
        'years': sorted(years.values(), key=lambda e: -e['year']),
        'options': _options(q),
    })


def _options(q):
    offices = Office.objects.all() if q.everything else Office.objects.filter(pk__in=q.scope)
    from .models import ManualSeries
    return {'offices': [{'id': o.pk, 'name': o.name} for o in offices.order_by('name')],
            'series': [{'id': s.pk, 'code': s.code} for s in ManualSeries.objects.order_by('code')]}


def _month_rows(q, year, month):
    """Every entry of one month, newest first, as rows."""
    zone = timezone.get_current_timezone()
    start = timezone.make_aware(datetime(year, month, 1), zone)
    end = timezone.make_aware(datetime(year + (month == 12), month % 12 + 1, 1), zone)
    requests = list(q.requests().filter(on__gte=start, on__lt=end).select_related(
        'manual', 'initiating_office').annotate(
        returned=Count('events', filter=Q(events__event__in=RETURNS), distinct=True),
    ))
    changed = dict(Proposal.objects.filter(pk__in=[p.pk for p in requests]).annotate(
        n=Count('versions__changes', distinct=True)).values_list('pk', 'n'))
    rows = [{
        'kind': 'request', 'proposal_id': p.pk, 'outcome': OUTCOMES[p.status],
        'outcome_label': OUTCOME_WORDS[OUTCOMES[p.status]], 'dcr_number': p.dcr_number,
        'manual': p.manual.title, 'sections': changed.get(p.pk, 0),
        'office': p.initiating_office.name, 'opened': p.created_at, 'closed': p.closed_at,
        'submitted': p.submitted_at,
        'days_open': ((p.closed_at or p.created_at) - p.created_at).days,
        'times_returned': p.returned, 'on': p.on,
    } for p in requests]
    rows += [{
        'kind': 'review', 'proposal_id': None, 'outcome': 'reviewed',
        'outcome_label': OUTCOME_WORDS['reviewed'], 'dcr_number': '',
        'manual': r.manual.title, 'sections': 0, 'office': r.office_name_at_time,
        'opened': r.at, 'closed': r.at, 'submitted': None, 'days_open': 0,
        'times_returned': 0, 'on': r.on,
    } for r in q.reviews().filter(on__gte=start, on__lt=end).select_related('manual')]
    rows.sort(key=lambda r: r['on'], reverse=True)
    return rows


def _month(q, year, month, page):
    rows = _month_rows(q, year, month)
    start = (page - 1) * lists.PAGE_SIZE
    return {'count': len(rows), 'page': page, 'page_size': lists.PAGE_SIZE,
            'pages': max(1, -(-len(rows) // lists.PAGE_SIZE)), 'rows': rows[start:start + lists.PAGE_SIZE]}


# ─── Export ──────────────────────────────────────────────────

COLUMNS = ['Outcome', 'DCR', 'Manual', 'Sections', 'Office', 'Opened', 'Closed',
           'Days open', 'Times returned']


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def export(request):
    from .audit_trail import write_csv, write_pdf
    q = Query(request, request.data)
    if q.error:
        return q.error
    form = request.data.get('format')
    if form not in ('csv', 'pdf'):
        return _refuse('Export as CSV or PDF.', 'invalid_format')
    months = set()
    for (moment,) in q.requests().values_list('on'):
        months.add(_bucket(moment))
    for (moment,) in q.reviews().values_list('on'):
        months.add(_bucket(moment))
    rows = []
    for year, month in sorted(months, reverse=True):
        rows += _month_rows(q, year, month)
        if len(rows) >= EXPORT_CAP:
            break
    cut = len(rows) > EXPORT_CAP
    rows = rows[:EXPORT_CAP]

    def day(value):
        return timezone.localtime(value).strftime('%Y-%m-%d') if value else ''

    table = [(r['outcome_label'], r['dcr_number'], r['manual'], r['sections'] or '', r['office'],
              day(r['opened']), day(r['closed']), r['days_open'], r['times_returned']) for r in rows]
    from .trail_views import SYSTEM_ADMIN_TITLE
    posts = access.current_offices(request.user)
    who = (SYSTEM_ADMIN_TITLE if access.is_admin(request.user)
           else 'QMS staff' if access.is_qms_staff(request.user)
           else ', '.join(o.name for o in posts))
    now = timezone.localtime()
    shown = {k: v for k, v in {'view': q.view, 'date on': q.date_on, 'from': q.start, 'to': q.end,
                                'outcome': q.outcome, 'office': q.office, 'series': q.series,
                                'dcr': q.dcr}.items() if v}
    heading = [('Scope', 'the whole institution' if q.everything else f'{len(q.scope)} office(s)'),
               ('Filters', ', '.join(f'{k} {v}' for k, v in shown.items()) or 'none'),
               ('Exported by', who), ('Exported at', f'{now:%d %b %Y %H:%M}'),
               ('Rows', f'{len(rows)}' + (f' (cut at {EXPORT_CAP})' if cut else ''))]
    data = (write_csv(heading, COLUMNS, table) if form == 'csv' else
            write_pdf('History', heading, COLUMNS, table, f'History · exported {now:%d %b %Y %H:%M}'))
    response = HttpResponse(data, content_type='text/csv; charset=utf-8' if form == 'csv'
                            else 'application/pdf')
    response['Content-Disposition'] = f'attachment; filename="history-{now:%Y%m%d-%H%M}.{form}"'
    response['Access-Control-Expose-Headers'] = 'Content-Disposition'
    return response
