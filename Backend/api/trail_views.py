"""The audit trail report: who may generate it, and the log of who did.

| Who | May generate |
|---|---|
| The IMR or Document Custodian | Any request |
| An office in the request's trail - the requester, a concurring office, an approving office | That request |
| The system admin | Any request, **with a reason**, which is logged |
| Anyone else | No |

The system admin is a technical role: an examiner may fairly ask why the
person who manages accounts holds document records. The reason they give
answers that, one line per report.

Every report is logged with a serial printed on each of its pages, so a
copy found later can be checked against this record.
"""

import hashlib
import secrets

from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .concurrence_views import _load
from .generation import trail
from .generation.common import DOCX_TYPE, position_title
from .models import CustomUser, Position, TrailReport
from .proposal_views import _current_assignments


SYSTEM_ADMIN_TITLE = 'System administrator'


def report_access(user, proposal):
    """How this person may generate the report: `(kind, generated_as)`.

    `kind` is 'office', 'qms', 'admin', or None for no access. Checked in
    that order, so a system admin who also holds a post in the trail
    generates under that post and is not asked for a reason.
    """
    assignments = _current_assignments(user)
    involved = {proposal.initiating_office_id} | set(
        proposal.participants.values_list('office_id', flat=True)
    )
    in_trail = [a for a in assignments if a.position.office_id in involved]
    if in_trail:
        # The requesting office first: that is the role most people hold.
        in_trail.sort(key=lambda a: a.position.office_id != proposal.initiating_office_id)
        position = in_trail[0].position
        return 'office', position_title(position.office.name, position.kind)

    for assignment in assignments:
        if assignment.position.kind in (Position.IMR, Position.DOCUMENT_CUSTODIAN):
            position = assignment.position
            return 'qms', position_title(position.office.name, position.kind)

    if user.system_role == CustomUser.SYSTEM_ADMIN or user.role == 'admin':
        return 'admin', SYSTEM_ADMIN_TITLE
    return None, None


def _serial(now):
    return f'AT-{now:%Y}-{secrets.token_hex(4).upper()}'


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate(request, proposal_id):
    proposal, error = _load(request, proposal_id)
    if error:
        return error

    kind, generated_as = report_access(request.user, proposal)
    if kind is None:
        return Response({
            'error': 'Only the offices in this request, the IMR, the Document '
                     'Custodian and the system admin can generate its audit trail.',
            'reason': 'not_in_trail',
        }, status=403)

    reason = (request.data.get('reason') or '').strip()
    if kind == 'admin' and not reason:
        return Response({
            'error': 'Say why you are generating this. It is recorded with the report.',
            'reason': 'reason_required',
        }, status=400)

    # The log row and the file together: a report that fails to build
    # leaves no row claiming it was issued.
    for _ in range(5):
        try:
            with transaction.atomic():
                report = TrailReport.objects.create(
                    serial=_serial(timezone.localtime()),
                    proposal=proposal, generated_by=request.user,
                    generated_as=generated_as,
                    reason=reason if kind == 'admin' else '',
                    status_at_time=proposal.status,
                )
                data = trail.build(proposal, report.serial,
                                   report.generated_at, generated_as)
                report.sha256 = hashlib.sha256(data).hexdigest()
                report.save(update_fields=['sha256'])
            break
        except IntegrityError:
            continue        # a serial collision; draw another
    else:
        return Response({'error': 'Could not number the report. Try again.'},
                        status=500)

    response = HttpResponse(data, content_type=DOCX_TYPE)
    response['Content-Disposition'] = (
        f'attachment; filename="{trail.filename(proposal, report.serial)}"'
    )
    response['X-Report-Serial'] = report.serial
    response['Access-Control-Expose-Headers'] = 'X-Report-Serial, Content-Disposition'
    return response


def _log_row(report):
    return {
        'serial': report.serial,
        'proposal_id': report.proposal_id,
        'generated_as': report.generated_as,
        'reason': report.reason,
        'status_at_time': report.status_at_time,
        'stamp': trail.STAMPS.get(report.status_at_time, trail.IN_PROGRESS),
        'sha256': report.sha256,
        'generated_at': report.generated_at,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def log(request, proposal_id):
    """Every report generated for this request. For anyone who may
    generate one - the log of a record is part of the record."""
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    kind, _ = report_access(request.user, proposal)
    if kind is None:
        return Response({'error': 'Access denied'}, status=403)
    return Response({
        'reports': [_log_row(r) for r in proposal.trail_reports.all()],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def verify(request, serial):
    """Look up a printed report by its serial.

    For checking a copy found on paper: when it was issued, by which
    position, and what the request's status was then. The IMR, the
    Custodian and the system admin may look up any serial; an office only
    those for requests in its own trail.
    """
    try:
        report = TrailReport.objects.select_related('proposal').get(
            serial=serial.strip().upper()
        )
    except TrailReport.DoesNotExist:
        return Response({'error': 'No report has that serial.'}, status=404)
    kind, _ = report_access(request.user, report.proposal)
    if kind is None:
        return Response({'error': 'No report has that serial.'}, status=404)
    row = _log_row(report)
    row['status_now'] = report.proposal.status
    row['status_now_label'] = report.proposal.get_status_display()
    return Response(row)
