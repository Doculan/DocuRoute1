"""The expanded audit block (spec §10, without the hash chain).

    GET  proposals/<id>/trail/           the summary and the timeline, grouped by version
    POST proposals/<id>/trail/export/    {format: csv|pdf, reason?, filters}

**Who may read it:** whoever may open the proposal (`can_see`). **Who may
export it:** as for the audit trail report (`trail_views.report_access`):
the offices in the request, the IMR and the Custodian; the system admin
with a reason. Each export is logged as a trail report, with its own
serial (`AT-…-CSV` / `AT-…-PDF`) and the file's SHA-256.

**What it shows:** every recorded step, position first with the person's
full name and the office as it was named then; the stage each step moved
the request from and to, and how long it sat in the one before; feedback,
notes, reasons and comments verbatim; and each AI check from its stored
result, never re-run. Not shown: individual section edits (they are not
recorded as steps) and notices read or acted on.

The trail is **not tamper-evident**: proposal events carry no hash chain.
"""

import csv
import hashlib
import io
import secrets
from datetime import datetime

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .concurrence_views import _load, _who, can_see
from .generation.common import position_title
from .models import (
    AuditEvent, Concurrence, DeadlineObligation, Position, PositionAssignment, Proposal,
    SectionChange, TrailReport,
)

# The stage a step leaves the request in (§7.2 words); None: no change.
STAGE_AFTER = {
    AuditEvent.CREATED: 'Drafting', AuditEvent.SENT_TO_HEAD: 'With Head',
    AuditEvent.RECALLED: 'Drafting', AuditEvent.RETURNED_TO_ENCODER: 'Returned by the Head',
    AuditEvent.SUBMITTED: 'In concurrence', AuditEvent.RETURNED: 'Returned by an office',
    AuditEvent.REDRAFTED: 'Drafting', AuditEvent.LOCKED: 'Locked',
    AuditEvent.DOCUMENTS_GENERATED: 'Awaiting signatures',
    AuditEvent.PACKAGE_COMPLETE: None,    # to the IMR, or back to the custodian - see below
    AuditEvent.IMR_ACCEPTED: 'With IMR (approving authority)',
    AuditEvent.IMR_DENIED: 'Denied', AuditEvent.APPROVAL_UPLOADED: 'With custodian',
    AuditEvent.PACKAGE_RETURNED: 'Returned for package defects',
    AuditEvent.MADE_EFFECTIVE: 'Effective', AuditEvent.WITHDRAWN: 'Withdrawn',
}
CLOSED_WORDS = {Proposal.EFFECTIVE: 'Effective', Proposal.DENIED: 'Denied by the IMR',
                Proposal.WITHDRAWN: 'Withdrawn'}
CHECK = 'ai_check'


def _days(delta):
    """'3 days', '5 hours', 'under an hour'."""
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return 'under an hour'
    if hours < 48:
        return f'{int(hours)} hour{"s" if int(hours) != 1 else ""}'
    return f'{int(hours // 24)} days'


def _checker(user, office_id, cache):
    """The position a person held in the requesting office, for an AI check
    (checks are not steps, so they carry no position of their own)."""
    if user is None:
        return {'position': 'AI check', 'name': None}
    key = (user.pk, office_id)
    if key not in cache:
        post = (PositionAssignment.objects.filter(user=user, position__office_id=office_id)
                .select_related('position__office').order_by('-starts_on').first())
        cache[key] = _who(user, post.position.office.name if post else '',
                          kind=post.position.kind if post else None)
    return cache[key]


def build(proposal):
    """{summary, versions: [{number, submitted_at, items: [...]}]}."""
    events = list(proposal.events.select_related('actor', 'position', 'version', 'acting_for')
                  .order_by('at', 'pk'))
    versions = list(proposal.versions.order_by('number'))
    returns = {(c.version_id, c.office_id): c for c in Concurrence.objects.filter(
        version__proposal=proposal, decision=Concurrence.RETURN).select_related('section')}

    items, stage, entered = [], None, proposal.created_at
    for e in events:
        after = STAGE_AFTER.get(e.event)
        if e.event == AuditEvent.PACKAGE_COMPLETE:
            after = 'With custodian' if stage == 'Returned for package defects' else 'With IMR'
        moved = after is not None and after != stage
        detail = e.detail
        if e.event == AuditEvent.RETURNED:
            c = returns.get((e.version_id, e.office_id))
            if c and c.section_id:
                detail = f'{detail}\n(Section: {c.section.subtitle})'
        items.append({
            'kind': 'event', 'event': e.event, 'label': e.get_event_display(),
            'version': e.version.number if e.version else None,
            'at': e.at, 'office': e.office_name_at_time,
            'by': _who(e.actor, e.office_name_at_time, e.position,
                       delegated=e.acting_for_id is not None),
            'detail': detail,
            'from': stage if moved else None, 'to': after if moved else None,
            'time_in_previous': _days(e.at - entered) if moved and stage else None,
        })
        if moved:
            stage, entered = after, e.at

    # The AI checks, from the stored results: one per changed section per
    # version, at the time it ran, by whoever ran it.
    cache = {}
    for change in SectionChange.objects.filter(
            version__proposal=proposal, assessment__isnull=False,
    ).select_related('version', 'section', 'assessment', 'assessment__submitted_by'):
        a = change.assessment
        items.append({
            'kind': CHECK, 'event': CHECK, 'label': 'AI check',
            'version': change.version.number, 'at': a.assessed_at,
            'office': proposal.initiating_office.name,
            'by': _checker(a.submitted_by, proposal.initiating_office_id, cache),
            'detail': f'{change.section.subtitle}: '
                      f'{(a.explanation_staff or "").strip() or "checked"}',
            'from': None, 'to': None, 'time_in_previous': None,
        })
    items.sort(key=lambda i: (i['at'], i['kind'] != 'event'))

    grouped = []
    for v in versions:
        grouped.append({'number': v.number, 'submitted_at': v.submitted_at,
                        'reason': v.overall_reason,
                        'items': [i for i in items if i['version'] == v.number]})
    loose = [i for i in items if i['version'] is None]
    if loose:      # steps recorded without a version: shown with the first
        if grouped:
            grouped[0]['items'] = sorted(loose + grouped[0]['items'], key=lambda i: i['at'])
        else:
            grouped.append({'number': 1, 'submitted_at': None, 'reason': '', 'items': loose})
    return {'summary': _summary(proposal, events, stage), 'versions': grouped}


def _summary(proposal, events, stage):
    created = next((e for e in events if e.event == AuditEvent.CREATED), None)
    closed_at = (proposal.withdrawn_at if proposal.status == Proposal.WITHDRAWN else
                 next((e.at for e in reversed(events) if e.event in (
                     AuditEvent.MADE_EFFECTIVE, AuditEvent.IMR_DENIED)), None))
    end = closed_at or timezone.now()
    returned = [{'by': (e.office_name_at_time if e.event == AuditEvent.RETURNED
                        else f'{e.office_name_at_time} — Head'), 'at': e.at}
                for e in events if e.event in (AuditEvent.RETURNED, AuditEvent.RETURNED_TO_ENCODER)]
    holder = None
    if proposal.status not in Proposal.CLOSED_STATUSES:
        from .monitoring_views import _proposal_rows
        row = _proposal_rows([proposal], timezone.now())[0]
        holder = {'who': row['holder'], 'days': row['days'], 'waiting_on': row['waiting_on']}
    deadline = (DeadlineObligation.objects.filter(met_by_proposal=proposal)
                .select_related('deadline__type').first()
                or DeadlineObligation.objects.filter(
                    manual=proposal.manual, office=proposal.initiating_office,
                    deadline__active=True).select_related('deadline__type')
                .order_by('deadline__due_on').first())
    return {
        'dcr_number': proposal.dcr_number, 'manual': proposal.manual.title,
        'office': proposal.initiating_office.name,
        'initiated_by': (_who(created.actor, created.office_name_at_time, created.position)
                         if created else _who(proposal.created_by, proposal.initiating_office.name)),
        'initiated_at': proposal.created_at,
        'closed_at': closed_at,
        'days_open': (end - proposal.created_at).days,
        'stage': CLOSED_WORDS.get(proposal.status, stage or proposal.get_status_display()),
        'holder': holder,
        'versions': proposal.versions.count(),
        'times_returned': len(returned), 'returned_by': returned,
        'deadline': {'title': deadline.deadline.title, 'type': deadline.deadline.type.name,
                     'due_on': deadline.deadline.due_on} if deadline else None,
    }


def _filtered(data, filters):
    """The same filters as the screen: action, office, version, from, to."""
    action, office = filters.get('action') or '', filters.get('office') or ''
    version = str(filters.get('version') or '')
    start, end = filters.get('from') or '', filters.get('to') or ''
    out = []
    for v in data['versions']:
        if version and str(v['number']) != version:
            continue
        for i in v['items']:
            day = timezone.localtime(i['at']).date().isoformat()
            if ((action and i['event'] != action) or (office and i['office'] != office)
                    or (start and day < start) or (end and day > end)):
                continue
            out.append({**i, 'version': v['number']})
    return out


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def trail(request, proposal_id):
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    if not can_see(request.user, proposal):
        return Response({'error': 'Access denied', 'reason': 'not_visible'}, status=403)
    return Response(build(proposal))


# ─── Export ──────────────────────────────────────────────────

FORMULA_START = ('=', '+', '-', '@', '\t', '\r')


def _cell(value):
    """Formula-safe: a cell that a spreadsheet would run as a formula is
    kept as text."""
    text = '' if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def _line(i):
    who = i['by']['position'] + (f" · {i['by']['name']}" if i['by'].get('name') else '')
    moved = f"{i['from'] or 'start'} → {i['to']}" if i['to'] else ''
    return who, moved


def to_csv(proposal, items, heading):
    out = io.StringIO()
    out.write('﻿')    # UTF-8 marker, so spreadsheets read accented names
    w = csv.writer(out)
    for label, value in heading:
        w.writerow([_cell(label), _cell(value)])
    w.writerow([])
    w.writerow(['Version', 'Time', 'Step', 'Position · name', 'Office', 'Stage moved',
                'Time in previous stage', 'Detail'])
    for i in items:
        who, moved = _line(i)
        w.writerow([_cell(c) for c in (
            i['version'], timezone.localtime(i['at']).strftime('%Y-%m-%d %H:%M'), i['label'],
            who, i['office'], moved, i['time_in_previous'] or '', i['detail'])])
    return out.getvalue().encode('utf-8')


def _esc(text):
    return (str(text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('\n', '<br/>'))


def to_pdf(proposal, items, heading, footer):
    import fitz
    html = ['<h2 style="font-size:13px">Audit trail</h2><table style="font-size:9px">']
    html += [f'<tr><td><b>{_esc(k)}</b></td><td>{_esc(v)}</td></tr>' for k, v in heading]
    html.append('</table><br/><table style="font-size:8px;border-collapse:collapse">')
    html.append('<tr><th>V</th><th>Time</th><th>Step</th><th>Who</th><th>Stage</th><th>Detail</th></tr>')
    for i in items:
        who, moved = _line(i)
        stage = moved + (f' (after {i["time_in_previous"]})' if i['time_in_previous'] else '')
        html.append(
            f'<tr><td>{i["version"]}</td>'
            f'<td>{timezone.localtime(i["at"]):%d %b %Y %H:%M}</td>'
            f'<td>{_esc(i["label"])}</td><td>{_esc(who)}<br/>{_esc(i["office"])}</td>'
            f'<td>{_esc(stage)}</td><td>{_esc(i["detail"])}</td></tr>')
    html.append('</table>')
    css = 'td, th { border-bottom: 0.5px solid #999; padding: 2px; vertical-align: top; text-align: left; }'
    story = fitz.Story(html=''.join(html), user_css=css)
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    page_rect = fitz.paper_rect('a4')
    body = page_rect + (36, 36, -36, -54)
    more = True
    while more:
        device = writer.begin_page(page_rect)
        more, _ = story.place(body)
        story.draw(device)
        writer.end_page()
    writer.close()
    document = fitz.open('pdf', buffer.getvalue())
    total = document.page_count
    for number, page in enumerate(document, 1):
        page.insert_text((36, page_rect.height - 30), f'{footer} · Page {number} of {total}',
                         fontsize=7)
    return document.tobytes()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def export(request, proposal_id):
    from .trail_views import report_access
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    kind, generated_as = report_access(request.user, proposal)
    if kind is None:
        return Response({'error': 'Only the offices in this request, the IMR, the Document '
                                  'Custodian and the system admin can export its audit trail.',
                         'reason': 'not_in_trail'}, status=403)
    form = request.data.get('format')
    if form not in ('csv', 'pdf'):
        return Response({'error': 'Export as CSV or PDF.', 'reason': 'invalid_format'}, status=400)
    reason = (request.data.get('reason') or '').strip()
    if kind == 'admin' and not reason:
        return Response({'error': 'Say why you are exporting this. It is recorded with the export.',
                         'reason': 'reason_required'}, status=400)
    filters = request.data.get('filters') or {}
    items = _filtered(build(proposal), filters)
    now = timezone.localtime()
    shown = ', '.join(f'{k} {v}' for k, v in filters.items() if v) or 'none'
    for _ in range(5):
        serial = f'AT-{now:%Y}-{secrets.token_hex(4).upper()}-{form.upper()}'
        heading = [('Request', proposal.dcr_number or f'Proposal {proposal.pk}'),
                   ('Manual', proposal.manual.title), ('Office', proposal.initiating_office.name),
                   ('Filters', shown), ('Exported as', generated_as),
                   ('Exported at', f'{now:%d %b %Y %H:%M}'), ('Serial', serial),
                   ('Note', 'The proposal trail is not hash-chained; it is not tamper-evident.')]
        try:
            with transaction.atomic():
                report = TrailReport.objects.create(
                    serial=serial, proposal=proposal, generated_by=request.user,
                    generated_as=generated_as, reason=reason if kind == 'admin' else '',
                    status_at_time=proposal.status)
                data = (to_csv(proposal, items, heading) if form == 'csv' else
                        to_pdf(proposal, items, heading, f'{serial} · exported {now:%d %b %Y %H:%M}'))
                report.sha256 = hashlib.sha256(data).hexdigest()
                report.save(update_fields=['sha256'])
            break
        except IntegrityError:
            continue
    else:
        return Response({'error': 'Could not number the export. Try again.'}, status=500)
    name = f'{(proposal.dcr_number or f"proposal-{proposal.pk}")}-trail-{serial}.{form}'
    response = HttpResponse(data, content_type='text/csv; charset=utf-8' if form == 'csv'
                            else 'application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{name}"'
    response['X-Report-Serial'] = serial
    response['Access-Control-Expose-Headers'] = 'X-Report-Serial, Content-Disposition'
    return response
