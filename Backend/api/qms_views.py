"""The QMS stages: the IMR's decision, and who the signed-in person is.

Phase 4a. Two rules shape it.

**The portal is the server's answer.** Which portal someone lands in used
to be read from browser storage, where anyone can edit it. `me` answers
from the account itself; the browser only follows.

**Deciding is a position's act, and never on one's own request.** Only a
current IMR decides, with the password again - and not on a request from
an office where they also hold a position. The same rule will apply to the
custodian making a change effective. Seeing a request is broader: QMS staff
see every request, as the system admin does.

Phase 4c adds the last stage: **the custodian records section 5 and the
change becomes effective** - the locked text written into the document,
in one transaction, or not at all.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access
from .concurrence_views import _full_payload, _load, can_see
from .document_status import read_status_fields, status_payload, suggested_status
from .generation.common import position_title
from .models import (
    Attachment, AuditEvent, CustomUser, DocumentStatus, Manual, ManualSection,
    Position, Proposal, QmsDecision, SectionHistory,
)
from .proposal_views import _current_assignments, _switch_off
from .views import predict_section, reauth_failure


# --- who is signed in ----------------------------------------

def portal_for(user):
    """Which portal this account belongs in."""
    if user.system_role == CustomUser.SYSTEM_ADMIN or user.role == 'admin':
        return 'admin'
    if user.system_role == CustomUser.QMS_STAFF:
        return 'qms'
    return 'staff'


def qms_position(user, kind):
    """The IMR or Custodian position this person holds today, or None."""
    held = _current_assignments(user, kinds=[kind])
    return held[0].position if held else None


def conflicting_office(user, proposal):
    """The requesting office, if this person holds any position in it.

    Deciding on a request from one's own office is deciding on one's own
    request, whatever the position held there.
    """
    for assignment in _current_assignments(user):
        if assignment.position.office_id == proposal.initiating_office_id:
            return proposal.initiating_office
    return None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    user = request.user
    imr = qms_position(user, Position.IMR)
    custodian = qms_position(user, Position.DOCUMENT_CUSTODIAN)
    return Response({
        'username': user.username,
        'name': user.get_full_name().strip() or None,
        'system_role': user.system_role,
        'portal': portal_for(user),
        'is_imr': imr is not None,
        'is_custodian': custodian is not None,
        'positions': [
            position_title(a.position.office.name, a.position.kind)
            for a in _current_assignments(user)
        ],
    })


# --- the queue -----------------------------------------------

def _queue_row(proposal):
    last = proposal.events.order_by('-at').first()
    return {
        'id': proposal.id,
        'manual': proposal.manual.title,
        'dcr_number': proposal.dcr_number,
        'office': proposal.initiating_office.name,
        'status': proposal.status,
        'status_label': proposal.get_status_display(),
        'since': last.at if last else proposal.updated_at,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def queue(request):
    """What is waiting on this person's QMS positions. Empty lists, not
    an error, for someone who holds neither - the screen then shows
    nothing rather than a queue that can never fill."""
    if not access.by_position():
        return _switch_off()
    user = request.user
    waiting = {'imr': [], 'custodian': []}
    base = Proposal.objects.select_related('manual', 'initiating_office')
    if qms_position(user, Position.IMR):
        waiting['imr'] = [
            _queue_row(p) for p in base.filter(status=Proposal.READY_FOR_IMR)
        ]
    if qms_position(user, Position.DOCUMENT_CUSTODIAN):
        # Not a returned package: that waits on the requesting office.
        waiting['custodian'] = [
            _queue_row(p) for p in base.filter(status=Proposal.WITH_CUSTODIAN)
        ]
    return Response(waiting)


# --- the IMR's decision --------------------------------------

def can_imr_decide(user, proposal):
    return bool(
        proposal.status == Proposal.READY_FOR_IMR
        and qms_position(user, Position.IMR) is not None
        and conflicting_office(user, proposal) is None
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def imr_decide(request, proposal_id):
    """Accept or deny, with comments; the password again.

    Deny closes the request. Its content was frozen at the lock, so a
    different change is a new request, not an edit of this one - and the
    reason is shown to every office involved.
    """
    if not access.by_position():
        return _switch_off()
    proposal, error = _load(request, proposal_id)
    if error:
        return error

    position = qms_position(request.user, Position.IMR)
    if position is None:
        return Response({
            'error': 'Only the Integrated Management Representative decides requests.',
            'reason': 'not_imr',
        }, status=403)
    conflict = conflicting_office(request.user, proposal)
    if conflict is not None:
        return Response({
            'error': (
                f'You hold a position in {conflict.name}, which made this '
                f'request. Another IMR must decide it.'
            ),
            'reason': 'conflict_of_interest',
        }, status=403)
    if proposal.status != Proposal.READY_FOR_IMR:
        return Response({
            'error': 'This request is not waiting for the IMR.',
            'reason': 'not_ready_for_imr',
        }, status=409)

    decision = request.data.get('decision')
    if decision not in (QmsDecision.ACCEPT, QmsDecision.DENY):
        return Response({
            'error': 'Accept or deny.', 'reason': 'unknown_decision',
        }, status=400)
    comments = (request.data.get('comments') or '').strip()
    if decision == QmsDecision.DENY and not comments:
        return Response({
            'error': 'Say why it is denied. Every office involved will see it.',
            'reason': 'comments_required',
        }, status=400)

    failure = reauth_failure(request)
    if failure is not None:
        return failure

    version = proposal.current_version()
    office = position.office
    with transaction.atomic():
        QmsDecision.objects.create(
            proposal=proposal, version=version, stage=QmsDecision.IMR,
            outcome=decision, comments=comments, decided_by=request.user,
            decided_as=position_title(office.name, position.kind),
        )
        if decision == QmsDecision.ACCEPT:
            proposal.status = Proposal.AWAITING_APPROVAL
            event = AuditEvent.IMR_ACCEPTED
        else:
            proposal.status = Proposal.DENIED
            event = AuditEvent.IMR_DENIED
        proposal.save(update_fields=['status'])
        AuditEvent.objects.create(
            proposal=proposal, version=version, event=event,
            actor=request.user, position=position, office=office,
            office_name_at_time=office.name, detail=comments,
        )
        # A denial releases the sections; an acceptance keeps them held.
        proposal.refresh_open_changes()

    proposal.refresh_from_db()
    data = _full_payload(proposal)
    data['can_imr_decide'] = False
    data['can_custodian_return'] = False
    data['can_make_effective'] = False
    return Response(data)


# --- the custodian's return ----------------------------------

def can_custodian_return(user, proposal):
    return bool(
        proposal.status == Proposal.WITH_CUSTODIAN
        and qms_position(user, Position.DOCUMENT_CUSTODIAN) is not None
        and conflicting_office(user, proposal) is None
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def custodian_return(request, proposal_id):
    """Send the package back for defects in it - never for its content.

    The custodian names which signed copies are defective and says why. The
    content was frozen at the lock and the IMR has judged it; what can be
    wrong now is the paperwork - a missing signature, an unreadable scan -
    so only the named copies may be replaced, and nothing else changes.

    No password: a return commits no office and changes no document. It is
    not in the table of actions that ask for one.
    """
    if not access.by_position():
        return _switch_off()
    proposal, error = _load(request, proposal_id)
    if error:
        return error

    position = qms_position(request.user, Position.DOCUMENT_CUSTODIAN)
    if position is None:
        return Response({
            'error': 'Only the Document Custodian returns a package.',
            'reason': 'not_custodian',
        }, status=403)
    conflict = conflicting_office(request.user, proposal)
    if conflict is not None:
        return Response({
            'error': (
                f'You hold a position in {conflict.name}, which made this '
                f'request. Another custodian must handle it.'
            ),
            'reason': 'conflict_of_interest',
        }, status=403)
    if proposal.status != Proposal.WITH_CUSTODIAN:
        return Response({
            'error': 'This package is not with the Document Custodian.',
            'reason': 'not_with_custodian',
        }, status=409)

    kinds = request.data.get('kinds') or []
    if not isinstance(kinds, list) or not kinds:
        return Response({
            'error': 'Name the signed copies that are defective.',
            'reason': 'no_defect_named',
        }, status=400)
    if any(kind not in Attachment.SCAN_KINDS for kind in kinds):
        return Response({
            'error': 'Only signed copies can be returned. The generated documents come '
                     'from the locked content, which does not change here.',
            'reason': 'unknown_kind',
        }, status=400)
    comments = (request.data.get('comments') or '').strip()
    if not comments:
        return Response({
            'error': 'Say what is wrong, so the office knows what to fix.',
            'reason': 'comments_required',
        }, status=400)

    version = proposal.current_version()
    office = position.office
    kinds = [k for k in Attachment.SCAN_KINDS if k in kinds]   # canonical order, no repeats
    with transaction.atomic():
        QmsDecision.objects.create(
            proposal=proposal, version=version, stage=QmsDecision.CUSTODIAN,
            outcome=QmsDecision.RETURN, comments=comments, returned_kinds=kinds,
            decided_by=request.user,
            decided_as=position_title(office.name, position.kind),
        )
        proposal.status = Proposal.PACKAGE_RETURNED
        proposal.save(update_fields=['status'])
        AuditEvent.objects.create(
            proposal=proposal, version=version, event=AuditEvent.PACKAGE_RETURNED,
            actor=request.user, position=position, office=office,
            office_name_at_time=office.name, detail=comments,
        )

    proposal.refresh_from_db()
    data = _full_payload(proposal)
    data['can_imr_decide'] = False
    data['can_custodian_return'] = False
    data['can_make_effective'] = False
    return Response(data)


# --- making it effective -------------------------------------

def can_make_effective(user, proposal):
    return can_custodian_return(user, proposal)


class _SectionMoved(Exception):
    """A changed section no longer reads as the offices saw it."""

    def __init__(self, section):
        super().__init__(section.subtitle)
        self.section = section


def _not_with_custodian():
    return Response({
        'error': 'This package is not with the Document Custodian.',
        'reason': 'not_with_custodian',
    }, status=409)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def make_effective(request, proposal_id):
    """Record DCR section 5 and write the locked text into the document.

    GET gives the form's starting values - the document's current entry,
    with the revision one higher. POST, with the password again, does it,
    in one transaction:

    1. every changed section must still read as the offices saw it; if
       anything has touched one since, nothing is written and the section
       is named, rather than overwriting words nobody on the request saw;
    2. section 5 becomes the document's current status;
    3. each changed section keeps its old text in its history, linked to
       this request, takes the locked text, and is tagged again;
    4. the request is Effective, and its sections are free.

    An effectivity date in the future is refused: readers would see text
    that is not yet in force. The custodian makes it effective on the day.
    """
    if not access.by_position():
        return _switch_off()
    proposal, error = _load(request, proposal_id)
    if error:
        return error

    position = qms_position(request.user, Position.DOCUMENT_CUSTODIAN)
    if position is None:
        return Response({
            'error': 'Only the Document Custodian makes a change effective.',
            'reason': 'not_custodian',
        }, status=403)
    conflict = conflicting_office(request.user, proposal)
    if conflict is not None:
        return Response({
            'error': (
                f'You hold a position in {conflict.name}, which made this '
                f'request. Another custodian must make it effective.'
            ),
            'reason': 'conflict_of_interest',
        }, status=403)
    if proposal.status != Proposal.WITH_CUSTODIAN:
        return _not_with_custodian()

    if request.method == 'GET':
        return Response({
            'current': status_payload(proposal.manual.current_status),
            'suggested': suggested_status(proposal.manual),
        })

    fields, refusal = read_status_fields(request.data, proposal.manual, with_ids_date=True)
    if refusal:
        return refusal

    failure = reauth_failure(request)
    if failure is not None:
        return failure

    office = position.office
    recorded_as = position_title(office.name, position.kind)
    try:
        with transaction.atomic():
            # Again inside the transaction: two custodians pressing at once
            # must not make one request effective twice.
            proposal = Proposal.objects.select_for_update().get(pk=proposal.pk)
            if proposal.status != Proposal.WITH_CUSTODIAN:
                return _not_with_custodian()
            manual = Manual.objects.select_for_update().get(pk=proposal.manual_id)
            version = proposal.current_version()
            changes = [c for c in version.changes.all() if c.has_changed]

            status = DocumentStatus.objects.create(
                manual=manual, proposal=proposal, recorded_by=request.user,
                recorded_as=recorded_as, **fields,
            )
            reason = (version.overall_reason or '').strip()
            for change in changes:
                section = ManualSection.objects.select_for_update().get(pk=change.section_id)
                if (section.content or '') != (change.old_text or ''):
                    raise _SectionMoved(section)
                note = (change.note or '').strip()
                SectionHistory.objects.create(
                    section=section, version=section.version,
                    subtitle=section.subtitle, content=section.content, tag=section.tag,
                    edited_by=request.user, source='proposal', proposal=proposal,
                    change_reason=f'{reason}\n\n{note}' if note else reason,
                )
                section.content = change.new_text
                try:
                    section.tag = predict_section(change.new_text)
                except Exception:
                    section.tag = 'UNTAGGED'
                section.version += 1
                section.status_changed = status
                section.save()

            # v3's counter keeps counting, for what still reads it; readers
            # see the recorded status instead.
            manual.revision += 1
            manual.current_status = status
            manual.save(update_fields=['revision', 'current_status'])

            QmsDecision.objects.create(
                proposal=proposal, version=version, stage=QmsDecision.CUSTODIAN,
                outcome=QmsDecision.EFFECTIVE,
                comments=(request.data.get('comments') or '').strip(),
                decided_by=request.user, decided_as=recorded_as,
            )
            proposal.status = Proposal.EFFECTIVE
            proposal.save(update_fields=['status'])
            AuditEvent.objects.create(
                proposal=proposal, version=version, event=AuditEvent.MADE_EFFECTIVE,
                actor=request.user, position=position, office=office,
                office_name_at_time=office.name,
                detail=(f'{status.document_number}, version {status.version}, '
                        f'revision {status.revision}, '
                        f'effective {status.effective_on:%Y-%m-%d}'),
            )
            proposal.refresh_open_changes()
    except _SectionMoved as moved:
        return Response({
            'error': (
                f'{moved.section.subtitle} no longer reads as the offices saw it: '
                f'it was changed after this request was drafted. Nothing was '
                f'made effective.'
            ),
            'reason': 'section_changed',
            'section_id': moved.section.pk,
        }, status=409)

    proposal.refresh_from_db()
    data = _full_payload(proposal)
    data['can_imr_decide'] = False
    data['can_custodian_return'] = False
    data['can_make_effective'] = False
    return Response(data)


# --- a document's starting status ----------------------------

def can_record_baseline(user, manual):
    return bool(
        access.by_position()
        and not manual.statuses.exists()
        and qms_position(user, Position.DOCUMENT_CUSTODIAN) is not None
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_baseline(request, manual_id):
    """Where a document stands before any request touches it.

    The manuals already carry real revisions on paper; without this, the
    first request made effective would be the first status readers could
    see. Once, and only while the document has no status at all: after
    that, its status changes through requests. The password again -
    readers take this as the document's official standing.
    """
    if not access.by_position():
        return _switch_off()
    try:
        manual = Manual.objects.get(pk=manual_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Document not found.'}, status=404)

    position = qms_position(request.user, Position.DOCUMENT_CUSTODIAN)
    if position is None:
        return Response({
            'error': "Only the Document Custodian records a document's status.",
            'reason': 'not_custodian',
        }, status=403)
    already = Response({
        'error': 'This document already has a recorded status. It changes through requests now.',
        'reason': 'status_exists',
    }, status=409)
    if manual.statuses.exists():
        return already

    fields, refusal = read_status_fields(request.data, manual, with_ids_date=False)
    if refusal:
        return refusal

    failure = reauth_failure(request)
    if failure is not None:
        return failure

    office = position.office
    with transaction.atomic():
        manual = Manual.objects.select_for_update().get(pk=manual.pk)
        if manual.statuses.exists():
            return already
        status = DocumentStatus.objects.create(
            manual=manual, proposal=None, recorded_by=request.user,
            recorded_as=position_title(office.name, position.kind), **fields,
        )
        manual.current_status = status
        manual.save(update_fields=['current_status'])
    return Response(status_payload(status), status=201)


def _correctable_baseline(manual):
    """The baseline that may still be corrected, or None.

    Only while no request has been made effective on the document: after
    that, readers have seen a status that rests on a signed DCR, and the
    baseline beneath it is history.
    """
    current = manual.current_status
    if current is None:
        return None
    # Until then the current status can only be a baseline.
    if manual.statuses.filter(proposal__isnull=False).exists():
        return None
    return current


def can_correct_baseline(user, manual):
    return bool(
        access.by_position()
        and _correctable_baseline(manual) is not None
        and qms_position(user, Position.DOCUMENT_CUSTODIAN) is not None
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def correct_baseline(request, manual_id):
    """Correct a starting status the custodian recorded wrongly.

    The mistaken row is kept and marked superseded by the new one, never
    overwritten. A reason, and the password: readers take the status as
    the document's official standing.
    """
    if not access.by_position():
        return _switch_off()
    try:
        manual = Manual.objects.get(pk=manual_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Document not found.'}, status=404)

    position = qms_position(request.user, Position.DOCUMENT_CUSTODIAN)
    if position is None:
        return Response({
            'error': "Only the Document Custodian corrects a document's status.",
            'reason': 'not_custodian',
        }, status=403)
    not_correctable = Response({
        'error': (
            'Only a starting status can be corrected, and only until a change '
            'has been made effective on the document.'
        ),
        'reason': 'not_correctable',
    }, status=409)
    if _correctable_baseline(manual) is None:
        return not_correctable

    fields, refusal = read_status_fields(
        request.data, manual, with_ids_date=False, compare=False)
    if refusal:
        return refusal
    reason = (request.data.get('reason') or '').strip()
    if not reason:
        return Response({
            'error': 'Say what was wrong with the recorded status.',
            'reason': 'reason_required',
        }, status=400)

    failure = reauth_failure(request)
    if failure is not None:
        return failure

    office = position.office
    with transaction.atomic():
        manual = Manual.objects.select_for_update().get(pk=manual.pk)
        old = _correctable_baseline(manual)
        if old is None:
            return not_correctable
        new = DocumentStatus.objects.create(
            manual=manual, proposal=None, recorded_by=request.user,
            recorded_as=position_title(office.name, position.kind),
            correction_reason=reason, **fields,
        )
        old.superseded_by = new
        old.superseded_at = timezone.now()
        old.save(update_fields=['superseded_by', 'superseded_at'])
        manual.current_status = new
        manual.save(update_fields=['current_status'])
    return Response(status_payload(new), status=201)


def decisions_payload(proposal):
    """The QMS decisions on a request, for everyone who can see it."""
    return [
        {
            'stage': d.stage,
            'outcome': d.outcome,
            'outcome_label': d.get_outcome_display(),
            'comments': d.comments,
            'by': {
                'position': d.decided_as,
                'name': d.decided_by.get_full_name().strip() or None,
            },
            'at': d.decided_at,
        }
        for d in proposal.qms_decisions.select_related('decided_by').order_by('decided_at')
    ]
