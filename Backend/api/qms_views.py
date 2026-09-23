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
"""

from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access
from .concurrence_views import _full_payload, _load, can_see
from .generation.common import position_title
from .models import (
    AuditEvent, CustomUser, Position, Proposal, QmsDecision,
)
from .proposal_views import _current_assignments, _switch_off
from .views import reauth_failure


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
        waiting['custodian'] = [
            _queue_row(p) for p in base.filter(
                status__in=(Proposal.WITH_CUSTODIAN, Proposal.PACKAGE_RETURNED)
            )
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
    return Response(data)


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
