"""Drafting a proposal: the whole document, one box per section.

Phase 2a. Creating a proposal, editing sections, the per-section AI check,
the overall reason, and the two rules that keep drafts from colliding.

**Proposals only work with the access switch on.** With it off, the v3
single-section flow is still the real one and these endpoints refuse -
building both at once would mean two ways to change a document with
nothing deciding between them.

**The pipeline is untouched.** Each changed section goes through the same
`_assess_unsaved` the single-section check has always used, and the result
is stored once and read thereafter. Nothing here re-runs an assessment for
display.
"""

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access, pre_assessment
from .models import (
    AuditEvent, Manual, ManualSection, Office, OfficeLink, Position,
    PositionAssignment, Proposal, ProposalVersion, RevisionPreAssessment,
    SectionChange,
)

# Raised from 60. The old limit was sized for one section at a time; a
# whole-document draft is up to 17 checks in this corpus, and a redraft
# costs one more per section revisited. 200 allows roughly ten full
# documents an hour and still bounds the cost of a model run.
RATE_LIMIT_PER_HOUR = 200

# Per proposal as well, so one runaway editor cannot spend the whole
# user budget on a single document.
RATE_LIMIT_PER_PROPOSAL = 80


def _switch_off():
    return Response({
        'error': (
            'Proposals are available once access is scoped by position. '
            'Until then, changes are proposed one section at a time.'
        ),
        'reason': 'switch_off',
    }, status=409)


def _current_assignments(user, kinds=None):
    """Position assignments this person currently holds.

    `kinds` narrows it - a Head submits, anyone drafts. The assignment
    rather than the office, because the audit trail records which
    position somebody was acting under, not only where.
    """
    today = timezone.localdate()
    query = PositionAssignment.objects.filter(
        user=user, position__is_active=True, position__office__is_active=True,
        starts_on__lte=today,
    ).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=today)
    ).select_related('position', 'position__office')
    if kinds:
        query = query.filter(position__kind__in=kinds)
    return list(query)


def _held_position(user, office, kinds=None):
    """The position this person holds at that office, if any."""
    for assignment in _current_assignments(user, kinds):
        if assignment.position.office_id == office.pk:
            return assignment.position
    return None


def _proposal_payload(proposal, detail=False):
    version = proposal.current_version()
    changes = list(
        SectionChange.objects.filter(version=version).select_related('section')
    ) if version else []
    changed = [c for c in changes if c.has_changed]

    data = {
        'id': proposal.id,
        'manual_id': proposal.manual_id,
        'manual': proposal.manual.title,
        'series': proposal.manual.series.code if proposal.manual.series_id else None,
        'initiating_office': str(proposal.initiating_office),
        'initiating_office_id': proposal.initiating_office_id,
        'status': proposal.status,
        'status_label': proposal.get_status_display(),
        'created_by': proposal.created_by.username,
        'created_at': proposal.created_at,
        'version': version.number if version else None,
        'overall_reason': version.overall_reason if version else '',
        'changed_sections': len(changed),
        # The strictest of the changed sections, which is what the DCR
        # carries - but each section's own result stays visible, so a
        # reviewer can see *which* section is the problem.
        'verdict': _overall_verdict(changed),
        'ready_to_submit': _submission_blockers(proposal, version, changed) == [],
        'blockers': _submission_blockers(proposal, version, changed),
    }
    if detail:
        data['sections'] = [_change_payload(c, changes) for c in changes]
    return data


# Strictest first. The overall verdict is the worst of the changed
# sections, because a document is not approvable while any part of it is
# not.
_VERDICT_ORDER = ['reject', 'needs_revision', 'approve']


def _overall_verdict(changes):
    verdicts = {
        c.assessment.verdict for c in changes
        if c.assessment_id and c.assessment.verdict
    }
    for verdict in _VERDICT_ORDER:
        if verdict in verdicts:
            return verdict
    return None


def _submission_blockers(proposal, version, changed):
    """Why this cannot be submitted yet, in the drafter's words."""
    blockers = []
    if not changed:
        blockers.append('Nothing has been changed yet.')
    if version is not None and not (version.overall_reason or '').strip():
        blockers.append('The reason for the change is required.')
    unchecked = [c for c in changed if not c.check_is_current]
    if unchecked:
        blockers.append(
            'These sections need a check: '
            + ', '.join(c.section.subtitle for c in unchecked)
        )
    return blockers


def _coordinated_advisory(change, all_changes):
    """*"This may be because section 3.6 is also being changed here."*

    A `contradicts_manual` concern is raised against the manual's
    **current** text. When the section it points at is also being changed
    in this proposal, the contradiction may be with text that is about to
    stop existing - so the concern is annotated rather than suppressed.
    Nobody can tell from the outside which it is, and silently dropping a
    high-severity concern would be worse than explaining it.

    Reads the stored snapshot. The retrieved section ids were recorded
    when the check ran, so nothing is recomputed here.
    """
    if not change.assessment_id:
        return None
    assessment = change.assessment
    if 'contradicts_manual' not in (assessment.issues or []):
        return None

    retrieved = set(assessment.retrieved_section_ids or [])
    others = {
        c.section_id: c.section.subtitle for c in all_changes
        if c.section_id != change.section_id and c.has_changed
    }
    overlap = [others[sid] for sid in retrieved if sid in others]
    if not overlap:
        return None
    return (
        'This may be because '
        + ', '.join(overlap)
        + (' is' if len(overlap) == 1 else ' are')
        + ' also being changed in this proposal.'
    )


def _change_payload(change, all_changes=None):
    from .views import build_diff
    assessment = change.assessment
    data = {
        'section_id': change.section_id,
        'subtitle': change.section.subtitle,
        'order': change.section.order,
        'old_text': change.old_text,
        'new_text': change.new_text,
        'note': change.note,
        'has_changed': change.has_changed,
        'check_is_current': change.check_is_current,
        # Built here with the same normaliser the v3 flow uses, so a diff
        # reads identically whichever screen shows it - and so the client
        # is not left diffing text it would have to normalise itself.
        'diff_text': (
            build_diff(change.old_text, change.new_text)
            if change.has_changed else ''
        ),
        'assessment': None,
    }
    if assessment is not None:
        data['assessment'] = {
            'id': str(assessment.id),
            'verdict': assessment.verdict,
            'confidence': assessment.confidence,
            'change_type': assessment.change_type,
            'issues': assessment.issues,
            'hard_fails': assessment.hard_fails,
            'advisories': assessment.advisories,
            'explanation': assessment.explanation_staff,
            'assessed_at': assessment.assessed_at,
            'stale': not change.check_is_current,
        }
        advisory = _coordinated_advisory(change, all_changes or [change])
        if advisory:
            data['assessment']['coordinated_change'] = advisory
    return data


# ─── Endpoints ───────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def proposals(request):
    """List the proposals this person's offices initiated, or start one."""
    if not access.by_position():
        return _switch_off()

    offices = access.current_offices(request.user)
    if not offices:
        return Response({
            'error': (
                'Your account is approved but not yet assigned to an office. '
                'The system administrator will assign you.'
            ),
            'reason': 'no_position',
        }, status=403)

    if request.method == 'GET':
        rows = Proposal.objects.filter(
            initiating_office__in=offices
        ).select_related('manual', 'manual__series', 'initiating_office', 'created_by')
        return Response({'proposals': [_proposal_payload(p) for p in rows]})

    try:
        manual = Manual.objects.select_related('series').get(
            id=request.data.get('manual_id')
        )
    except (Manual.DoesNotExist, ValueError, TypeError):
        return Response({'error': 'Document not found'}, status=404)

    office_id = request.data.get('office_id')
    office = None
    if office_id:
        office = next((o for o in offices if o.pk == int(office_id)), None)
    elif len(offices) == 1:
        office = offices[0]
    if office is None:
        return Response({
            'error': (
                'Choose which office you are drafting for.'
                if len(offices) > 1 else 'You hold no position in that office.'
            ),
            'reason': 'office_required',
            'offices': [{'id': o.id, 'name': str(o)} for o in offices],
        }, status=400)

    # Only a concurring office may propose. The owner counts when it is
    # also listed as concurring - which is allowed, and common.
    concurring = {
        link.office_id for link in manual.effective_office_links()
        if link.relationship == OfficeLink.CONCURRING
    }
    if office.pk not in concurring:
        return Response({
            'error': (
                f'{office} does not concur on {manual.title}, so it cannot '
                f'propose changes to it.'
            ),
            'reason': 'not_concurring',
        }, status=403)

    existing = _open_proposal(manual, office)
    if existing:
        return _already_open(manual, office, existing)

    try:
        with transaction.atomic():
            proposal = Proposal.objects.create(
                manual=manual, initiating_office=office, created_by=request.user,
            )
            ProposalVersion.objects.create(proposal=proposal, number=1)
            AuditEvent.objects.create(
                proposal=proposal, version=proposal.current_version(),
                event=AuditEvent.CREATED, actor=request.user,
                position=_held_position(request.user, office), office=office,
                office_name_at_time=office.name,
            )
    except IntegrityError:
        # Another request made it between the check above and this insert
        # - a double click, or React running the effect twice. The
        # database kept one; send this one there.
        return _already_open(manual, office, _open_proposal(manual, office))

    return Response(_proposal_payload(proposal, detail=True), status=201)


def _open_proposal(manual, office):
    return Proposal.objects.filter(
        manual=manual, initiating_office=office,
        status__in=Proposal.OPEN_STATUSES,
    ).first()


def _already_open(manual, office, existing):
    return Response({
        'error': f'{office} already has an open proposal for {manual.title}.',
        'reason': 'already_open',
        'proposal_id': existing.id if existing else None,
    }, status=409)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def proposal_detail(request, proposal_id):
    """The whole document, every section as its own box.

    Unchanged sections are included, because the editor shows the whole
    manual - the drafter has to see what they are *not* changing to know
    whether the change is coherent.
    """
    if not access.by_position():
        return _switch_off()

    try:
        proposal = Proposal.objects.select_related(
            'manual', 'manual__series', 'initiating_office', 'created_by'
        ).get(id=proposal_id)
    except Proposal.DoesNotExist:
        return Response({'error': 'Proposal not found'}, status=404)

    # Reading follows the one rule for seeing a proposal: the offices asked
    # to concur must be able to read what they are agreeing to. This once
    # admitted only the requesting office, and a concurring Head was shown
    # "1 of 0 changed" and no text at all. Writing stays with the office
    # that made the proposal.
    from .concurrence_views import can_see
    if request.method == 'GET':
        if not can_see(request.user, proposal):
            return Response({'error': 'Access denied'}, status=403)
        data = _proposal_payload(proposal, detail=True)
        data['all_sections'] = _document_sections(proposal)
        return Response(data)

    offices = {o.pk for o in access.current_offices(request.user)}
    if proposal.initiating_office_id not in offices:
        return Response({'error': 'Access denied'}, status=403)

    version = proposal.current_version()
    if not proposal.is_open:
        return Response({
            'error': f'This proposal is {proposal.get_status_display().lower()} '
                     f'and can no longer be edited.',
            'reason': 'not_open',
        }, status=409)

    if 'overall_reason' in request.data:
        version.overall_reason = (request.data.get('overall_reason') or '').strip()
        version.save(update_fields=['overall_reason'])

    return Response(_proposal_payload(proposal, detail=True))


def _document_sections(proposal):
    """Every section of the document, with the change if there is one.

    The editor is the whole manual. Sections are collapsed by default and
    only a changed one carries a check, but they are all here.
    """
    version = proposal.current_version()
    changes = {
        c.section_id: c for c in
        SectionChange.objects.filter(version=version).select_related('section')
    } if version else {}

    rows = []
    for section in proposal.manual.sections.all().order_by('order'):
        change = changes.get(section.id)
        rows.append({
            'section_id': section.id,
            'subtitle': section.subtitle,
            'order': section.order,
            'tag': section.tag,
            'current_text': section.content,
            'change': _change_payload(change, list(changes.values()))
            if change else None,
        })
    return rows


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def proposal_section(request, proposal_id, section_id):
    """Edit one section's proposed text, or put it back as it was.

    Editing clears **only this section's** check, by leaving the stored
    hash behind. That is the whole reason the check is per section: a
    twenty-section document would otherwise be unworkable.
    """
    if not access.by_position():
        return _switch_off()

    proposal, error = _editable_proposal(request, proposal_id)
    if error:
        return error

    try:
        section = proposal.manual.sections.get(id=section_id)
    except ManualSection.DoesNotExist:
        return Response(
            {'error': 'That section is not in this document.'}, status=404
        )

    version = proposal.current_version()

    if request.method == 'DELETE':
        SectionChange.objects.filter(version=version, section=section).delete()
        return Response(_proposal_payload(proposal, detail=True))

    new_text = request.data.get('new_text')
    if new_text is None:
        return Response({'error': 'new_text is required.'}, status=400)

    change = SectionChange.objects.filter(
        version=version, section=section
    ).first()

    if change is None:
        # Held by another office? Report it as that, rather than as a
        # database error - the drafter needs to know who to talk to.
        holder = SectionChange.objects.filter(
            section=section, is_open=True
        ).select_related('version__proposal__initiating_office').first()
        if holder is not None:
            office = holder.version.proposal.initiating_office
            return Response({
                'error': (
                    f'{section.subtitle} is already in an open proposal by '
                    f'{office}. A section can be in only one at a time.'
                ),
                'reason': 'section_in_another_proposal',
                'office': str(office),
                'proposal_id': holder.version.proposal_id,
            }, status=409)

        change = SectionChange(
            version=version, section=section,
            # Captured now, so the diff a reviewer sees is the diff the
            # drafter saw even if the section moves underneath both.
            old_text=section.content or '',
        )

    change.new_text = new_text
    if 'note' in request.data:
        change.note = (request.data.get('note') or '').strip()

    try:
        with transaction.atomic():
            change.save()
    except IntegrityError:
        return Response({
            'error': (
                f'{section.subtitle} is already in an open proposal. A '
                f'section can be in only one at a time.'
            ),
            'reason': 'section_in_another_proposal',
        }, status=409)

    return Response(_proposal_payload(proposal, detail=True))


def _editable_proposal(request, proposal_id):
    try:
        proposal = Proposal.objects.select_related(
            'manual', 'initiating_office'
        ).get(id=proposal_id)
    except Proposal.DoesNotExist:
        return None, Response({'error': 'Proposal not found'}, status=404)

    offices = {o.pk for o in access.current_offices(request.user)}
    if proposal.initiating_office_id not in offices:
        return None, Response({'error': 'Access denied'}, status=403)

    if not proposal.is_open:
        return None, Response({
            'error': f'This proposal is {proposal.get_status_display().lower()} '
                     f'and can no longer be edited.',
            'reason': 'not_open',
        }, status=409)

    return proposal, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_section(request, proposal_id, section_id):
    """Run the AI check on one changed section.

    The same call the single-section flow has always made, per section.
    The result is stored and read thereafter; the advisory about
    coordinated changes is attached at display time from what was stored,
    not by running anything again.
    """
    if not access.by_position():
        return _switch_off()

    proposal, error = _editable_proposal(request, proposal_id)
    if error:
        return error

    version = proposal.current_version()
    change = SectionChange.objects.filter(
        version=version, section_id=section_id
    ).select_related('section').first()
    if change is None:
        return Response(
            {'error': 'That section has not been changed yet.'}, status=400
        )
    if not change.has_changed:
        return Response({
            'error': 'That section is unchanged, so there is nothing to check.',
            'reason': 'unchanged',
        }, status=400)

    limited = _rate_limited(request.user, proposal)
    if limited:
        return limited

    from .views import _assess_unsaved, _retrieved_section_ids

    section = change.section
    reason = version.overall_reason or change.note or ''
    result = _assess_unsaved(section, change.new_text, reason, seed=proposal.id)

    with transaction.atomic():
        snapshot = RevisionPreAssessment.objects.create(
            section=section,
            submitted_by=request.user,
            content_hash=pre_assessment.content_hash(
                section.id, section.content or '', change.new_text, reason,
            ),
            section_content_hash=pre_assessment.section_content_hash(
                section.content or ''
            ),
            proposed_content=change.new_text,
            change_reason=reason,
            verdict=result.get('verdict', ''),
            confidence=result.get('confidence'),
            change_type=result.get('change_type', ''),
            issues=result.get('issues', []),
            hard_fails=result.get('hard_fails', []),
            advisories=result.get('advisories', []),
            explanation_reviewer=result.get('explanation', ''),
            explanation_staff=result.get('explanation_staff', ''),
            trace=result.get('trace', {}),
            model_fingerprint=result.get('trace', {}).get('fingerprint', ''),
            pipeline_version=result.get('trace', {}).get('pipeline_version', ''),
            retrieved_section_ids=_retrieved_section_ids(section, change.new_text),
        )
        change.assessment = snapshot
        # The change's own fingerprint, over its two texts. The
        # assessment keeps its full hash (which folds in the reason) for
        # the submission-time guard the v3 flow already uses.
        change.content_hash = change.text_hash()
        change.section_content_hash = snapshot.section_content_hash
        change.save(update_fields=[
            'assessment', 'content_hash', 'section_content_hash',
        ])

    changes = list(
        SectionChange.objects.filter(version=version).select_related('section')
    )
    return Response(_change_payload(change, changes))


def _rate_limited(user, proposal):
    """A check costs a model run, and a whole document is many of them."""
    from datetime import timedelta
    window = timezone.now() - timedelta(hours=1)

    by_user = RevisionPreAssessment.objects.filter(
        submitted_by=user, assessed_at__gte=window,
    ).count()
    if by_user >= RATE_LIMIT_PER_HOUR:
        return Response({
            'error': 'Too many AI checks in the past hour. Please wait a few '
                     'minutes and try again.',
            'reason': 'rate_limited_user',
        }, status=429)

    on_proposal = RevisionPreAssessment.objects.filter(
        section_change__version__proposal=proposal, assessed_at__gte=window,
    ).count()
    if on_proposal >= RATE_LIMIT_PER_PROPOSAL:
        return Response({
            'error': 'Too many checks on this proposal in the past hour. '
                     'Please wait a few minutes and try again.',
            'reason': 'rate_limited_proposal',
        }, status=429)

    return None
