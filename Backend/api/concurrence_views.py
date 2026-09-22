"""Submission, concurrence, versions, locking and withdrawal.

Phase 2b: everything between a finished draft and full agreement.

Three rules shape the whole of it.

**Participants freeze at submission.** A reorganisation mid-request must
never change who has to agree to it, so the list is written once and read
afterwards - including each office's name at the time, because an office
renamed next year must still read correctly on this request.

**An office concurs with particular text.** Any return makes a new
version, and every concurrence resets, because agreement to text that no
longer exists is not agreement.

**Only a Head commits an office**, with re-authentication. Without
e-signatures that confirmation is the nearest thing the system has to a
signature on the office's position.

**Until P4 a locked proposal does not change the manual.** Locking freezes
what was agreed; applying it is the custodian's act.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access
from .models import (
    AuditEvent, Concurrence, OfficeLink, Position, Proposal,
    ProposalParticipant, ProposalVersion, SectionChange,
)
from .proposal_views import (
    _change_payload, _held_position, _proposal_payload, _submission_blockers,
    _switch_off,
)
from .views import reauth_failure
from ml.revision_pipeline.change_reason import blocks_submission, classify_reason


def _record(proposal, version, event, user, office, detail=''):
    return AuditEvent.objects.create(
        proposal=proposal, version=version, event=event, actor=user,
        position=_held_position(user, office), office=office,
        office_name_at_time=office.name, detail=detail,
    )


def _participants_payload(proposal):
    """Who must agree, who signs, and where each has got to.

    Read from the frozen rows, not recomputed from the current
    organisation - that is the whole point of freezing them.
    """
    version = proposal.current_version()
    decisions = {
        c.office_id: c for c in
        Concurrence.objects.filter(version=version).select_related(
            'office', 'recorded_by'
        )
    } if version else {}

    rows = []
    for participant in proposal.participants.select_related('office'):
        decision = decisions.get(participant.office_id)
        rows.append({
            'office_id': participant.office_id,
            'office': participant.office_name_at_time,
            'role': participant.role,
            'route_order': participant.route_order,
            'decision': decision.decision if decision else None,
            'feedback': decision.feedback if decision else '',
            'feedback_section': (
                decision.section.subtitle
                if decision and decision.section_id else None
            ),
            'recorded_by': decision.recorded_by.username if decision else None,
            'recorded_at': decision.recorded_at if decision else None,
        })
    return rows


def _full_payload(proposal):
    data = _proposal_payload(proposal, detail=True)
    data['participants'] = _participants_payload(proposal)
    data['versions'] = [
        {
            'number': v.number,
            'overall_reason': v.overall_reason,
            'submitted_by': v.submitted_by.username if v.submitted_by_id else None,
            'submitted_at': v.submitted_at,
            'decisions': [
                {'office': c.office.name, 'decision': c.decision,
                 'feedback': c.feedback, 'at': c.recorded_at}
                for c in v.concurrences.select_related('office')
            ],
        }
        for v in proposal.versions.order_by('number').prefetch_related(
            'concurrences__office'
        )
    ]
    data['events'] = [
        {'event': e.event, 'label': e.get_event_display(),
         'office': e.office_name_at_time, 'actor': e.actor.username,
         'at': e.at, 'detail': e.detail}
        for e in proposal.events.select_related('actor').order_by('at')
    ]
    return data


def _load(request, proposal_id):
    try:
        proposal = Proposal.objects.select_related(
            'manual', 'manual__series', 'initiating_office', 'created_by'
        ).get(id=proposal_id)
    except Proposal.DoesNotExist:
        return None, Response({'error': 'Proposal not found'}, status=404)
    return proposal, None


def _head_of(user, office):
    """The Head position this person holds at that office, or None.

    An Encoder may draft and may prepare feedback; only a Head commits the
    office. On the DCR the Head signs alongside the requester.
    """
    return _held_position(user, office, kinds=[Position.HEAD])


# ─── Submitting ──────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit(request, proposal_id):
    """Send a draft out for concurrence, or straight to locked.

    Freezes the participants at this moment. If no other office has to
    concur, there is nobody to ask and it locks immediately - the process
    has reached agreement by having only one party to it.
    """
    if not access.by_position():
        return _switch_off()

    proposal, error = _load(request, proposal_id)
    if error:
        return error

    office = proposal.initiating_office
    if _head_of(request.user, office) is None:
        return Response({
            'error': (
                f'Only the Head of {office} can submit this. On the form the '
                f'Head signs alongside the requester.'
            ),
            'reason': 'not_head',
        }, status=403)

    if proposal.status != Proposal.DRAFT:
        return Response({
            'error': f'This proposal is {proposal.get_status_display().lower()}.',
            'reason': 'not_draft',
        }, status=409)

    failure = reauth_failure(request)
    if failure:
        return failure

    version = proposal.current_version()
    changes = list(
        SectionChange.objects.filter(version=version).select_related('section')
    )
    changed = [c for c in changes if c.has_changed]

    blockers = _submission_blockers(proposal, version, changed)
    if blockers:
        return Response({
            'error': ' '.join(blockers),
            'reason': 'not_ready',
            'blockers': blockers,
        }, status=409)

    # Clause 6.3, on the one overall reason. The same two tiers the
    # single-section flow uses: a blank or throwaway reason is refused, a
    # vague but real one is flagged for the reviewer rather than blocking
    # a legitimate change.
    tier, message = classify_reason(version.overall_reason)
    if blocks_submission(tier):
        # The submitter's own message, not a generic one: it is written
        # for them and says what is missing.
        return Response({
            'error': message,
            'reason': 'reason_rejected',
            'tier': tier,
        }, status=400)

    # Every changed section's check must still be about the text being
    # submitted. Per section, using each change's own fingerprint.
    stale = [c for c in changed if not c.check_is_current]
    if stale:
        return Response({
            'error': (
                'These sections changed after they were checked: '
                + ', '.join(c.section.subtitle for c in stale)
                + '. Check them again before submitting.'
            ),
            'reason': 'stale_checks',
        }, status=409)

    with transaction.atomic():
        concurring = _freeze_participants(proposal)

        version.submitted_by = request.user
        version.submitted_at = timezone.now()
        version.save(update_fields=['submitted_by', 'submitted_at'])

        if concurring:
            proposal.status = Proposal.CONCURRENCE
            proposal.save(update_fields=['status'])
            _record(proposal, version, AuditEvent.SUBMITTED, request.user, office,
                    detail=f'{len(concurring)} office(s) to concur')
        else:
            # Nobody else works on this document, so there is nobody to
            # ask. Locking immediately is the honest outcome rather than
            # a concurrence stage with an empty list.
            _lock(proposal, version, request.user, office,
                  detail='No other office concurs on this document')

        proposal.refresh_open_changes()

    return Response(_full_payload(proposal))


def _freeze_participants(proposal):
    """Write the list of offices, once, at the first submission.

    Concurring offices minus the initiator - an office does not concur
    with itself - and then the approval route, in order. Each carries the
    office's name at this moment, because a rename next year must not
    rewrite what this request said.

    **Frozen for the request, not for the version.** A redraft after a
    return is a new version of the same request, so the list is not
    rebuilt: re-freezing would mean an office added to the document
    halfway through suddenly had to agree to a proposal it never saw, and
    one removed stopped mattering - which is exactly the silent change
    freezing exists to prevent.

    Found in rehearsal, not by a unit test: an office added mid-request
    became a participant on resubmission and blocked a proposal every
    original participant had already concurred with.
    """
    manual = proposal.manual

    existing = list(
        proposal.participants.filter(role=ProposalParticipant.CONCURRING)
        .select_related('office')
    )
    if proposal.participants.exists():
        return [p.office for p in existing]

    concurring = [
        link.office for link in manual.effective_office_links()
        if link.relationship == OfficeLink.CONCURRING
        and link.office_id != proposal.initiating_office_id
    ]
    for office in concurring:
        ProposalParticipant.objects.create(
            proposal=proposal, office=office, office_name_at_time=office.name,
            role=ProposalParticipant.CONCURRING,
        )

    # The route continues above the owner when the owner initiated, which
    # is the case the owner-may-propose rule exists for: the office that
    # wrote the change must not be the office that approves it.
    for order, office in enumerate(manual.approval_route()):
        ProposalParticipant.objects.create(
            proposal=proposal, office=office, office_name_at_time=office.name,
            role=ProposalParticipant.APPROVING, route_order=order,
        )

    return concurring


def _lock(proposal, version, user, office, detail=''):
    proposal.status = Proposal.LOCKED
    proposal.locked_at = timezone.now()
    proposal.save(update_fields=['status', 'locked_at'])
    _record(proposal, version, AuditEvent.LOCKED, user, office, detail=detail)


# ─── Concurrence ─────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def decide(request, proposal_id):
    """One office concurs, or returns it with feedback."""
    if not access.by_position():
        return _switch_off()

    proposal, error = _load(request, proposal_id)
    if error:
        return error

    if proposal.status != Proposal.CONCURRENCE:
        return Response({
            'error': f'This proposal is {proposal.get_status_display().lower()}, '
                     f'so there is nothing to decide.',
            'reason': 'not_in_concurrence',
        }, status=409)

    # Which participating office is this person a Head of? Read from the
    # frozen list, so somebody moved into a new office mid-request does
    # not acquire a say in it.
    participating = {
        p.office_id: p for p in proposal.participants.filter(
            role=ProposalParticipant.CONCURRING
        ).select_related('office')
    }
    office = position = None
    for assignment_office in access.current_offices(request.user):
        if assignment_office.pk in participating:
            head = _head_of(request.user, assignment_office)
            if head is not None:
                office, position = assignment_office, head
                break

    if office is None:
        in_list = any(
            o.pk in participating for o in access.current_offices(request.user)
        )
        return Response({
            'error': (
                'Only the Head of a concurring office can record its '
                'decision. An Encoder can prepare the feedback for the Head '
                'to confirm.'
                if in_list else
                'Your office is not asked to concur on this proposal.'
            ),
            'reason': 'not_head' if in_list else 'not_participating',
        }, status=403)

    decision = request.data.get('decision')
    if decision not in (Concurrence.CONCUR, Concurrence.RETURN):
        return Response(
            {'error': 'Decide to concur or to return it.'}, status=400
        )

    feedback = (request.data.get('feedback') or '').strip()
    if decision == Concurrence.RETURN and not feedback:
        return Response({
            'error': (
                'Say what needs changing. Returning a proposal without '
                'feedback leaves the office nothing to act on.'
            ),
            'reason': 'feedback_required',
        }, status=400)

    failure = reauth_failure(request)
    if failure:
        return failure

    version = proposal.current_version()
    section_id = request.data.get('section_id')

    with transaction.atomic():
        Concurrence.objects.update_or_create(
            version=version, office=office,
            defaults={
                'decision': decision,
                'feedback': feedback,
                'section_id': section_id or None,
                'recorded_by': request.user,
                'recorded_by_position': position,
            },
        )

        if decision == Concurrence.RETURN:
            _return_to_draft(proposal, version, request.user, office, feedback)
        else:
            _record(proposal, version, AuditEvent.CONCURRED,
                    request.user, office)
            outstanding = _offices_yet_to_decide(proposal, version)
            if not outstanding:
                _lock(proposal, version, request.user, office,
                      detail='All concurring offices agreed')
                proposal.refresh_open_changes()

    proposal.refresh_from_db()
    return Response(_full_payload(proposal))


def _offices_yet_to_decide(proposal, version):
    decided = set(
        Concurrence.objects.filter(
            version=version, decision=Concurrence.CONCUR,
        ).values_list('office_id', flat=True)
    )
    return [
        p for p in proposal.participants.filter(
            role=ProposalParticipant.CONCURRING
        ) if p.office_id not in decided
    ]


def _return_to_draft(proposal, version, user, office, feedback):
    """Send it back, and open a fresh version to redraft into.

    The new version starts as a **copy** of the returned one - the office
    is amending its own work, not starting again - but every check is
    dropped, because the text will move and a check that survived would be
    about text nobody submitted.

    Every concurrence is left on the old version rather than carried
    forward: an office agreed to text that no longer exists.
    """
    _record(proposal, version, AuditEvent.RETURNED, user, office, detail=feedback)

    next_number = version.number + 1
    new_version = ProposalVersion.objects.create(
        proposal=proposal, number=next_number,
        overall_reason=version.overall_reason,
    )
    proposal.status = Proposal.DRAFT
    proposal.save(update_fields=['status'])

    # Close the returned version's changes **before** copying, or both
    # versions hold the same section open for the length of the loop and
    # the one-open-change index refuses the copy. The new version is
    # already the current one, so this closes exactly the old rows.
    proposal.refresh_open_changes()

    for change in SectionChange.objects.filter(version=version):
        SectionChange.objects.create(
            version=new_version, section=change.section,
            old_text=change.old_text, new_text=change.new_text,
            note=change.note,
            # No assessment, no hash: it has to be checked again.
        )

    # The actor is whoever returned it, the office is the one that has to
    # redraft. Said in full, because "BUD_Jose redrafted for Accounting"
    # reads as though Budget did the drafting.
    _record(proposal, new_version, AuditEvent.REDRAFTED,
            user, proposal.initiating_office,
            detail=(
                f'Version {next_number} opened for redrafting after '
                f'{office.name} returned version {version.number}'
            ))


# ─── Withdrawal ──────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def withdraw(request, proposal_id):
    """The initiating office takes it back. The record stays."""
    if not access.by_position():
        return _switch_off()

    proposal, error = _load(request, proposal_id)
    if error:
        return error

    office = proposal.initiating_office
    if _head_of(request.user, office) is None:
        return Response({
            'error': f'Only the Head of {office} can withdraw this.',
            'reason': 'not_head',
        }, status=403)

    if not proposal.is_open:
        return Response({
            'error': f'This proposal is {proposal.get_status_display().lower()} '
                     f'and cannot be withdrawn.',
            'reason': 'not_open',
        }, status=409)

    reason = (request.data.get('reason') or '').strip()
    if not reason:
        return Response({
            'error': 'Say why it is being withdrawn. The record stays.',
            'reason': 'reason_required',
        }, status=400)

    failure = reauth_failure(request)
    if failure:
        return failure

    with transaction.atomic():
        version = proposal.current_version()
        proposal.status = Proposal.WITHDRAWN
        proposal.withdrawn_at = timezone.now()
        proposal.withdrawn_by = request.user
        proposal.withdrawn_reason = reason
        proposal.save(update_fields=[
            'status', 'withdrawn_at', 'withdrawn_by', 'withdrawn_reason',
        ])
        _record(proposal, version, AuditEvent.WITHDRAWN,
                request.user, office, detail=reason)
        # The sections go back to whoever wants them.
        proposal.refresh_open_changes()

    return Response(_full_payload(proposal))


# ─── Reading ─────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def proposal_full(request, proposal_id):
    """The whole proposal: sections, participants, versions, events.

    Visible to the initiating office, every participating office, and -
    read only - to the system admin and QMS staff.
    """
    if not access.by_position():
        return _switch_off()

    proposal, error = _load(request, proposal_id)
    if error:
        return error

    mine = {o.pk for o in access.current_offices(request.user)}
    involved = (
        proposal.initiating_office_id in mine
        or proposal.participants.filter(office_id__in=mine).exists()
    )
    from .models import CustomUser
    oversight = request.user.system_role in (
        CustomUser.SYSTEM_ADMIN, CustomUser.QMS_STAFF,
    )
    if not (involved or oversight):
        return Response({'error': 'Access denied'}, status=403)

    data = _full_payload(proposal)
    data['can_decide'] = bool(
        proposal.status == Proposal.CONCURRENCE
        and any(
            _head_of(request.user, o) is not None
            for o in access.current_offices(request.user)
            if proposal.participants.filter(
                office=o, role=ProposalParticipant.CONCURRING
            ).exists()
        )
    )
    data['can_submit'] = bool(
        proposal.status == Proposal.DRAFT
        and _head_of(request.user, proposal.initiating_office) is not None
    )
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def awaiting_my_office(request):
    """Proposals in concurrence where one of my offices has not decided.

    Derived rather than notified - notifications are P5. A count only
    when it is not zero: a badge showing nothing is a badge people learn
    to stop reading.
    """
    if not access.by_position():
        return _switch_off()

    mine = [o.pk for o in access.current_offices(request.user)]
    if not mine:
        return Response({'proposals': [], 'total': 0})

    rows = []
    for proposal in Proposal.objects.filter(
        status=Proposal.CONCURRENCE,
        participants__office_id__in=mine,
        participants__role=ProposalParticipant.CONCURRING,
    ).distinct().select_related(
        'manual', 'manual__series', 'initiating_office', 'created_by'
    ):
        version = proposal.current_version()
        undecided = [
            p for p in _offices_yet_to_decide(proposal, version)
            if p.office_id in mine
        ]
        if undecided:
            payload = _proposal_payload(proposal)
            payload['my_offices'] = [p.office_name_at_time for p in undecided]
            rows.append(payload)

    return Response({'proposals': rows, 'total': len(rows)})
