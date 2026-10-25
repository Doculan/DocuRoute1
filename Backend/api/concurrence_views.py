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

from . import access, deadlines, delegation, documents, freeze, lists, notifications
from .ai_notes import compose_version_note
from .deadline_tags import tag_rows
from .generation.common import position_title
from .models import (
    AuditEvent, Concurrence, OfficeLink, Position, Proposal,
    ProposalParticipant, ProposalVersion, SectionChange,
)
from .proposal_views import (
    _change_payload, _held_position, _proposal_payload, _submission_blockers,
)
from .views import reauth_failure
from ml.revision_pipeline.change_reason import blocks_submission, classify_reason


def _record(proposal, version, event, user, office, detail='', position=None):
    """Write the audit event, and tell whoever needs to hear about it.

    One place for both, so no transition can be recorded and forgotten
    by the inbox - which is how the proposing office went unaware of
    concurrences and returns.
    """
    record = AuditEvent.objects.create(
        proposal=proposal, version=version, event=event, actor=user,
        position=position or _held_position(user, office), office=office,
        office_name_at_time=office.name, detail=detail,
    )
    notifications.notify(record)
    return record


def _who(user, office_name, position=None, kind=None, delegated=False):
    """A person as the screens show them: position first, then full name.

    Never the username - it is a login, not a name, and it says nothing
    about the part someone played. The position is built from the office
    name recorded at the time, so a rename does not rewrite it. Generated
    documents do not use this: they print titles only.
    """
    kind = kind or (position.kind if position is not None else None)
    title = position_title(office_name, kind) if kind else office_name
    if delegated:
        title += ' (delegated)'
    name = user.get_full_name().strip() if user is not None else ''
    return {'position': title, 'name': name or None}


def _participants_payload(proposal):
    """Who must agree, who signs, and where each has got to.

    Read from the frozen rows, not recomputed from the current
    organisation - that is the whole point of freezing them.
    """
    version = proposal.current_version()
    decisions = {
        c.office_id: c for c in
        Concurrence.objects.filter(version=version).select_related(
            'office', 'recorded_by', 'recorded_by_position'
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
            # Only a Head records a decision, so that is the fallback
            # when the position has since been removed.
            'recorded_by': _who(
                decision.recorded_by, participant.office_name_at_time,
                decision.recorded_by_position,
                kind=None if decision.recorded_by_position_id else Position.HEAD,
            ) if decision else None,
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
            # Only the initiating office's Head submits.
            'submitted_by': _who(
                v.submitted_by, proposal.initiating_office.name, kind=Position.HEAD,
            ) if v.submitted_by_id else None,
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
         'office': e.office_name_at_time,
         'by': _who(e.actor, e.office_name_at_time, e.position,
                    delegated=e.acting_for_id is not None),
         'at': e.at, 'detail': e.detail}
        for e in proposal.events.select_related('actor', 'position').order_by('at')
    ]
    # The IMR's and custodian's decisions - a denial's reason above all -
    # shown to every office involved.
    from .qms_views import decisions_payload
    data['qms_decisions'] = decisions_payload(proposal)
    # Section 5, once the custodian has made it effective.
    from .document_status import status_payload
    data['document_status'] = status_payload(getattr(proposal, 'document_status', None))
    return data


def _load(request, proposal_id):
    try:
        proposal = Proposal.objects.select_related(
            'manual', 'manual__series', 'initiating_office', 'created_by'
        ).get(id=proposal_id)
    except Proposal.DoesNotExist:
        return None, Response({'error': 'Proposal not found'}, status=404)
    return proposal, None


def can_see(user, proposal):
    """The initiating office, every participating office, and - read only -
    the system admin and QMS staff. The one rule for seeing a proposal and
    everything attached to it."""
    from .models import CustomUser
    mine = {o.pk for o in access.current_offices(user)}
    involved = (
        proposal.initiating_office_id in mine
        or proposal.participants.filter(office_id__in=mine).exists()
    )
    oversight = user.system_role in (CustomUser.SYSTEM_ADMIN, CustomUser.QMS_STAFF)
    return involved or oversight


def _head_of(user, office):
    """The Head position this person holds at that office, or None.

    An Encoder may draft and may prepare feedback; only a Head commits the
    office. On the DCR the Head signs alongside the requester.
    """
    return _held_position(user, office, kinds=[Position.HEAD])


# ─── Submitting ──────────────────────────────────────────────

def _readiness_refusal(proposal, version):
    """Why this draft cannot leave the drafter yet, or None.

    The same bar for Send to Head as for Submit, so the Head sees exactly
    what the Encoder read: every changed section checked against its
    current text, and an acceptable reason.
    """
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
    return None


def has_current_encoder(office):
    return bool(notifications.current_posts([office.pk], [Position.ENCODER]))


def head_may_submit_draft(user, proposal):
    """A Head submits a draft directly - without it being sent - only when
    they drafted it themselves, or the office has no Encoder to send it."""
    return (proposal.created_by_id == user.pk
            or not has_current_encoder(proposal.initiating_office))


def _encoder_of(user, office):
    """The Encoder post this person holds there - and not the Head's: a
    Head who drafts submits directly rather than sending it to themselves."""
    if _head_of(user, office) is not None:
        return None
    return _held_position(user, office, kinds=[Position.ENCODER])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit(request, proposal_id):
    """Send it out for concurrence, or straight to locked.

    From the Head: a draft the Encoder sent (`with_head`), or one the Head
    may submit directly. Freezes the participants at this moment. If no
    other office has to concur, there is nobody to ask and it locks
    immediately - the process has reached agreement by having only one
    party to it.
    """

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
    refusal = delegation.maker_checker_refusal(request.user, proposal, office)
    if refusal:
        return refusal

    if proposal.status not in (Proposal.DRAFT, Proposal.WITH_HEAD):
        return Response({
            'error': f'This proposal is {proposal.get_status_display().lower()}.',
            'reason': 'not_draft',
        }, status=409)
    if proposal.status == Proposal.DRAFT and not head_may_submit_draft(request.user, proposal):
        return Response({
            'error': ('This draft is the Encoder\'s. It comes to you when they '
                      'send it to you.'),
            'reason': 'send_to_head_first',
        }, status=409)
    refusal = freeze.refusal(freeze.SUBMIT, proposal=proposal)
    if refusal:
        return refusal

    failure = reauth_failure(request)
    if failure:
        return failure

    version = proposal.current_version()
    refusal = _readiness_refusal(proposal, version)
    if refusal:
        return refusal

    with transaction.atomic():
        concurring = _freeze_participants(proposal)

        version.submitted_by = request.user
        version.submitted_at = timezone.now()
        # The proposal-level note: composed once, from the stored section
        # checks, and frozen with this version. It never re-runs a check,
        # and a failure to write it never blocks the submission.
        version.proposal_note = compose_version_note(version)
        version.save(update_fields=['submitted_by', 'submitted_at', 'proposal_note'])

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

        # Submitted: the office milestone of any deadline this meets.
        deadlines.on_submitted(proposal, request.user)
        proposal.refresh_open_changes()

    return Response(_full_payload(proposal))


# ─── Encoder and Head ────────────────────────────────────────
#
# Drafting (Encoder) --Send to Head--> With Head --Submit--> In concurrence
#        ^                                |
#        '-- Return to Encoder / Recall --'
#
# No password on these three: they move a draft inside one office and
# commit nothing to anyone outside it (CLAUDE.md, re-authentication).

def _move(proposal, status, event, user, office, position, detail=''):
    with transaction.atomic():
        proposal.status = status
        proposal.save(update_fields=['status'])
        _record(proposal, proposal.current_version(), event, user, office,
                detail=detail, position=position)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_to_head(request, proposal_id):
    """The Encoder hands a ready draft to the Head."""
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    office = proposal.initiating_office
    if _head_of(request.user, office) is not None:
        return Response({
            'error': 'You are the Head of this office: submit it directly.',
            'reason': 'head_submits_directly',
        }, status=409)
    position = _encoder_of(request.user, office)
    if position is None:
        return Response({
            'error': f'Only an Encoder of {office} sends its drafts to the Head.',
            'reason': 'not_encoder',
        }, status=403)
    if proposal.status != Proposal.DRAFT:
        return Response({
            'error': f'This proposal is {proposal.get_status_display().lower()}.',
            'reason': 'not_draft',
        }, status=409)
    refusal = _readiness_refusal(proposal, proposal.current_version())
    if refusal:
        return refusal
    refusal = freeze.refusal(freeze.SEND_TO_HEAD, proposal=proposal)
    if refusal:
        return refusal

    _move(proposal, Proposal.WITH_HEAD, AuditEvent.SENT_TO_HEAD,
          request.user, office, position)
    return Response(_full_payload(proposal))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def recall(request, proposal_id):
    """The Encoder takes it back before the Head has acted."""
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    office = proposal.initiating_office
    position = _encoder_of(request.user, office)
    if position is None:
        return Response({
            'error': f'Only an Encoder of {office} recalls a draft from the Head.',
            'reason': 'not_encoder',
        }, status=403)
    if proposal.status != Proposal.WITH_HEAD:
        return Response({
            'error': 'It is not with the Head, so there is nothing to recall.',
            'reason': 'not_with_head',
        }, status=409)

    _move(proposal, Proposal.DRAFT, AuditEvent.RECALLED, request.user, office, position)
    return Response(_full_payload(proposal))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def return_to_encoder(request, proposal_id):
    """The Head sends it back to the Encoder, saying what to change."""
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    office = proposal.initiating_office
    position = _head_of(request.user, office)
    if position is None:
        return Response({
            'error': f'Only the Head of {office} returns a draft to the Encoder.',
            'reason': 'not_head',
        }, status=403)
    refusal = delegation.maker_checker_refusal(request.user, proposal, office)
    if refusal:
        return refusal
    if proposal.status != Proposal.WITH_HEAD:
        return Response({
            'error': 'It is not with you, so there is nothing to return.',
            'reason': 'not_with_head',
        }, status=409)
    note = (request.data.get('note') or '').strip()
    if not note:
        return Response({
            'error': 'Say what needs changing, so the Encoder knows what to do.',
            'reason': 'note_required',
        }, status=400)

    _move(proposal, Proposal.DRAFT, AuditEvent.RETURNED_TO_ENCODER,
          request.user, office, position, detail=note)
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
    """Freeze the content, number the request, make the documents.

    **Call inside a transaction.** Generation runs here rather than on
    demand afterwards, so that a proposal is never frozen with nothing to
    sign: if a generator fails, the lock fails with it and the offices
    keep a proposal they can still work on.

    The status advances to `AWAITING_SIGNATURE` only once the documents
    exist. Until 3b registers the generators, nothing is produced and the
    proposal rests at `LOCKED` - which is the honest description of it.
    """
    proposal.status = Proposal.LOCKED
    proposal.locked_at = timezone.now()
    if not proposal.dcr_number:
        proposal.dcr_number = documents.allocate_dcr_number(proposal.locked_at)
    proposal.save(update_fields=['status', 'locked_at', 'dcr_number'])
    _record(proposal, version, AuditEvent.LOCKED, user, office, detail=detail)

    documents.generate_package(proposal, version, user)
    if documents.package_is_complete(proposal, version):
        proposal.status = Proposal.AWAITING_SIGNATURE
        proposal.save(update_fields=['status'])
        _record(
            proposal, version, AuditEvent.DOCUMENTS_GENERATED, user, office,
            detail=f'Document Change Request {proposal.dcr_number}',
        )


# ─── Concurrence ─────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def decide(request, proposal_id):
    """One office concurs, or returns it with feedback."""

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
    refusal = delegation.maker_checker_refusal(request.user, proposal, office)
    if refusal:
        return refusal

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

    # One decision per office per version. A return opens a new version,
    # so this only ever refuses a second word on text the office has
    # already agreed to - which used to overwrite the first and log a
    # second "concurred". Changing a concurrence into a return before the
    # lock is a possible later feature, not something to allow by accident.
    version = proposal.current_version()
    already = Response({
        'error': f'{office} has already concurred on this version.',
        'reason': 'already_decided',
    }, status=409)
    if Concurrence.objects.filter(version=version, office=office).exists():
        return already

    failure = reauth_failure(request)
    if failure:
        return failure

    section_id = request.data.get('section_id')

    with transaction.atomic():
        # Again under the write lock, which an immediate transaction holds
        # from here: a double click that slipped past the check above would
        # otherwise meet the unique constraint as a server error.
        if Concurrence.objects.filter(version=version, office=office).exists():
            return already
        Concurrence.objects.create(
            version=version, office=office, decision=decision,
            feedback=feedback, section_id=section_id or None,
            recorded_by=request.user, recorded_by_position=position,
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
        # What it met is owed again (or passes to another proposal in flight).
        deadlines.on_withdrawn(proposal, request.user)
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

    proposal, error = _load(request, proposal_id)
    if error:
        return error

    if not can_see(request.user, proposal):
        return Response({'error': 'Access denied'}, status=403)

    # Opening the proposal is reading what the notices were about.
    notifications.mark_read(request.user, proposal_id=proposal.id)

    data = _full_payload(proposal)
    # Which rendering of each section's AI note to show: the one addressed
    # to the drafting office, or the one addressed to those reviewing it.
    data['viewer_is_initiator'] = any(
        o.pk == proposal.initiating_office_id
        for o in access.current_offices(request.user)
    )
    # Offered only to an office still to decide on this version. It used
    # to stay after the office had concurred, so the page looked as if the
    # concurrence had not been recorded, and a second click logged it twice.
    undecided = (
        {p.office_id for p in _offices_yet_to_decide(proposal, proposal.current_version())}
        if proposal.status == Proposal.CONCURRENCE else set()
    )
    data['can_decide'] = any(
        _head_of(request.user, o) is not None
        for o in access.current_offices(request.user)
        if o.pk in undecided
    )
    # Each action offered only where the server would accept it: an
    # Encoder never sees a button they cannot use.
    office = proposal.initiating_office
    is_head = _head_of(request.user, office) is not None
    is_encoder = _encoder_of(request.user, office) is not None
    data['can_submit'] = bool(is_head and (
        proposal.status == Proposal.WITH_HEAD
        or (proposal.status == Proposal.DRAFT
            and head_may_submit_draft(request.user, proposal))))
    data['can_send_to_head'] = is_encoder and proposal.status == Proposal.DRAFT
    data['can_recall'] = is_encoder and proposal.status == Proposal.WITH_HEAD
    data['can_return_to_encoder'] = is_head and proposal.status == Proposal.WITH_HEAD
    # The server's own rule for withdrawing, so the screen offers it exactly
    # where it works. The screen used `can_submit`, which ends at the
    # draft: a request out for concurrence could be withdrawn, and nobody
    # was shown how.
    data['can_withdraw'] = bool(
        proposal.is_open
        and _head_of(request.user, proposal.initiating_office) is not None
    )
    # A change freeze over this request (3D): the screen keeps its buttons
    # but disables Send to Head, Submit and Make effective, saying why.
    data['freeze'] = freeze.payload(freeze.blocking(proposal=proposal)) \
        if proposal.status in (*Proposal.OPEN_STATUSES, Proposal.WITH_CUSTODIAN) else None
    from .qms_views import can_custodian_return, can_imr_decide, can_make_effective
    data['can_imr_decide'] = can_imr_decide(request.user, proposal)
    data['can_custodian_return'] = can_custodian_return(request.user, proposal)
    data['can_make_effective'] = can_make_effective(request.user, proposal)
    from .trail_views import report_access
    kind, _ = report_access(request.user, proposal)
    data['trail_report'] = {
        'can_generate': kind is not None,
        'needs_reason': kind == 'admin',
    }
    tag_rows(request.user, [data])
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def awaiting_my_office(request):
    """Proposals in concurrence where one of my offices has not concurred
    on the current version, newest activity first, a page of 50 at a time
    (`page`, `q` for a title). `total` is the count for the tab.

    Built on the same aggregate as Needs your action (`awaiting_pairs`),
    so the two never disagree, in a fixed number of queries.
    """
    from .action_views import awaiting_pairs
    mine = [o.pk for o in access.current_offices(request.user)]
    if not mine:
        return Response({'proposals': [], 'total': 0, 'count': 0, 'page': 1,
                         'page_size': lists.PAGE_SIZE, 'pages': 1})
    pairs = awaiting_pairs(mine)
    proposals = Proposal.objects.filter(pk__in=pairs.values('proposal'))
    response = _proposal_page(request, proposals)
    if isinstance(response, Response):
        return response
    rows, paging = response
    undecided = {}
    for proposal_id, name in pairs.filter(proposal_id__in=[r['id'] for r in rows]).values_list(
            'proposal_id', 'office_name_at_time'):
        undecided.setdefault(proposal_id, []).append(name)
    for row in rows:
        row['my_offices'] = undecided.get(row['id'], [])
    return Response({'proposals': rows, 'total': paging['count'], **paging})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def involving_my_office(request):
    """Other offices' requests my office concurs on, once they no longer
    wait on us, a page of 50 at a time (`page`, `q`).

    Without this a concurring office lost sight of a request the moment it
    concurred: "Awaiting my office" holds only what is waiting, and "From
    my office" only its own. An IMR's denial - whose reason every office
    involved is meant to read - had no way to reach them on screen.
    """
    from .action_views import awaiting_pairs
    mine = [o.pk for o in access.current_offices(request.user)]
    if not mine:
        return Response({'proposals': [], 'total': 0, 'count': 0, 'page': 1,
                         'page_size': lists.PAGE_SIZE, 'pages': 1})
    proposals = Proposal.objects.filter(pk__in=ProposalParticipant.objects.filter(
        office_id__in=mine, role=ProposalParticipant.CONCURRING,
    ).values('proposal')).exclude(pk__in=awaiting_pairs(mine).values('proposal'))
    response = _proposal_page(request, proposals)
    if isinstance(response, Response):
        return response
    rows, paging = response
    return Response({'proposals': rows, 'total': paging['count'], **paging})


def _proposal_page(request, proposals):
    """(rows, paging) for one page of a Proposals tab, or a refusal."""
    page = lists.page_number(request.query_params)
    if page is None:
        return lists.refuse('Pages are numbered from 1.', 'invalid_page')
    q = (request.query_params.get('q') or '').strip()
    if q:
        proposals = proposals.filter(manual__title__icontains=q)
    rows, paging = lists.page_of(
        lists.with_latest_version(proposals.select_related(*lists.PROPOSAL_RELATED))
        .order_by('-updated_at', '-pk'), page)
    return lists.proposal_rows(request.user, rows), paging
