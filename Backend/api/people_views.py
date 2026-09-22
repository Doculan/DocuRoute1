"""People, and the positions they hold.

The process never names a person. It names a position - the office's Head,
the IMR - and asks who holds it. So this is where the two are joined, and
the joining is **dated**: an assignment has a start and an end, and "who
holds this now" is derived from those rather than stored anywhere.

That is the whole design. A pointer would answer only "who holds it now",
and a request signed in 2024 needs the answer for 2024.

**Nobody is ever deleted.** A person is deactivated, which ends their
current assignments; the record of what they did stands.

### The QMS positions

IMR and Document Custodian are positions like any other, attached to
whichever office the system admin chooses. The two QMS offices on the 2022
chart have since merged, so in practice both live in one office - but
nothing here says so, and nothing prevents a university from splitting
them again.

Which IMR handles which series is **not** resolved here. There is one set
of QMS positions and whoever currently holds them acts on everything. Per
series routing would be a field on `ManualSeries` pointing at an office,
and nothing in this module would have to change to add it.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import CustomUser, Office, Position, PositionAssignment
from .organisation_views import IsSystemAdmin
from .views import reauth_failure

# Positions whose holder commits an office, decides a request, or controls
# a document. Assigning or ending one asks for the password; an Encoder
# drafts, which is ordinary work.
GUARDED_KINDS = (Position.HEAD, Position.IMR, Position.DOCUMENT_CUSTODIAN)


def _assignment_payload(assignment):
    return {
        'id': assignment.id,
        'position_id': assignment.position_id,
        'office': str(assignment.position.office),
        'office_id': assignment.position.office_id,
        'kind': assignment.position.kind,
        'kind_label': assignment.position.get_kind_display(),
        'is_acting': assignment.is_acting,
        'starts_on': assignment.starts_on,
        'ends_on': assignment.ends_on,
        'is_current': assignment.is_current,
    }


def _person_payload(person, assignments=None):
    if assignments is None:
        assignments = person.position_assignments.select_related(
            'position', 'position__office'
        ).all()
    current = [a for a in assignments if a.is_current]
    return {
        'id': person.id,
        'username': person.username,
        'full_name': person.full_name,
        'email': person.email,
        'system_role': person.system_role,
        'is_approved': person.is_approved,
        'is_active': person.is_active,
        'current_positions': [_assignment_payload(a) for a in current],
        'past_positions': [
            _assignment_payload(a) for a in assignments if not a.is_current
        ],
    }


@api_view(['GET'])
@permission_classes([IsSystemAdmin])
def people(request):
    """Everyone, with what they currently hold.

    The full list is system-admin only. Names are personal data under RA
    10173, and the process itself only ever needs a position.
    """
    queryset = CustomUser.objects.prefetch_related(
        'position_assignments__position__office'
    ).order_by('username')

    filter_by = request.query_params.get('filter')
    if filter_by == 'pending':
        queryset = queryset.filter(is_approved=False)
    elif filter_by == 'awaiting_position':
        queryset = queryset.filter(is_approved=True, is_active=True)

    rows = [_person_payload(p) for p in queryset]

    if filter_by == 'awaiting_position':
        # Approved, active, and holding nothing - so they can sign in and
        # do nothing at all, which is the state worth surfacing.
        rows = [r for r in rows if not r['current_positions']]

    return Response({
        'people': rows,
        'pending_total': CustomUser.objects.filter(is_approved=False).count(),
        'awaiting_position_total': sum(
            1 for p in CustomUser.objects.filter(is_approved=True, is_active=True)
            if not PositionAssignment.objects.filter(
                user=p, ends_on__isnull=True
            ).exists()
        ),
    })


@api_view(['POST'])
@permission_classes([IsSystemAdmin])
def approve_person(request, person_id):
    """Let someone in. Not guarded: approving is reversible by
    deactivating, and a prompt here would be a prompt on routine work."""
    try:
        person = CustomUser.objects.get(id=person_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'Person not found'}, status=404)

    person.is_approved = True
    if 'full_name' in request.data:
        person.full_name = (request.data.get('full_name') or '').strip()
    person.save(update_fields=['is_approved', 'full_name'])
    return Response(_person_payload(person))


@api_view(['POST'])
@permission_classes([IsSystemAdmin])
def deactivate_person(request, person_id):
    """Someone has left. Their assignments end; their record stays.

    Guarded, because ending a Head's assignment changes who can commit
    that office - the same reason the merge screen asks.
    """
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        person = CustomUser.objects.get(id=person_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'Person not found'}, status=404)

    if person.system_role == CustomUser.SYSTEM_ADMIN and person.id == request.user.id:
        return Response({
            'error': 'You cannot deactivate your own account.',
            'reason': 'self',
        }, status=409)

    today = timezone.localdate()
    with transaction.atomic():
        PositionAssignment.objects.filter(
            user=person, ends_on__isnull=True,
        ).update(ends_on=today)
        person.is_active = False
        person.save(update_fields=['is_active'])

    return Response(_person_payload(person))


@api_view(['POST'])
@permission_classes([IsSystemAdmin])
def reactivate_person(request, person_id):
    """Coming back does not restore the posts they held. Those ended on a
    date, and re-opening them would rewrite what the record says
    happened - so the admin assigns again, and the gap stays visible."""
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        person = CustomUser.objects.get(id=person_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'Person not found'}, status=404)

    person.is_active = True
    person.save(update_fields=['is_active'])
    return Response(_person_payload(person))


@api_view(['POST'])
@permission_classes([IsSystemAdmin])
def assign_position(request, person_id):
    """Put someone in a post, from a date.

    The position row is created if the office does not have one yet: a
    Position is a slot, not a decision, and making the admin create the
    slot and then fill it would be two screens for one intention.
    """
    kind = request.data.get('kind')
    if kind not in dict(Position.KIND_CHOICES):
        return Response({'error': f'Unknown position: {kind!r}.'}, status=400)

    if kind in GUARDED_KINDS:
        failure = reauth_failure(request)
        if failure:
            return failure

    try:
        person = CustomUser.objects.get(id=person_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'Person not found'}, status=404)

    if not person.is_approved:
        return Response({
            'error': f'{person.username} has not been approved yet.',
            'reason': 'not_approved',
        }, status=409)
    if not person.is_active:
        return Response({
            'error': f'{person.username} is deactivated. Reactivate them first.',
            'reason': 'inactive',
        }, status=409)

    try:
        office = Office.objects.get(id=request.data.get('office_id'))
    except (Office.DoesNotExist, ValueError, TypeError):
        return Response({'error': 'Office not found'}, status=404)
    if not office.is_active:
        return Response({
            'error': f'{office} is not active.', 'reason': 'office_inactive',
        }, status=409)

    starts_on = request.data.get('starts_on')
    starts_on = parse_date(starts_on) if isinstance(starts_on, str) else starts_on
    if starts_on is None:
        starts_on = timezone.localdate()

    position, _ = Position.objects.get_or_create(office=office, kind=kind)
    if not position.is_active:
        position.is_active = True
        position.save(update_fields=['is_active'])

    assignment = PositionAssignment(
        user=person, position=position, starts_on=starts_on,
        is_acting=bool(request.data.get('is_acting')),
        assigned_by=request.user,
    )
    try:
        assignment.full_clean(exclude=['sole_holder'])
        # A savepoint, so the IntegrityError below rolls back only this
        # insert. Without it the surrounding transaction is poisoned and
        # the query that builds the error message cannot run - which is
        # how the handler came to fail on the very case it exists for.
        with transaction.atomic():
            assignment.save()
    except ValidationError as error:
        return Response({'error': '; '.join(
            f'{f}: {m}' if f != '__all__' else m
            for f, messages in error.message_dict.items() for m in messages
        )}, status=400)
    except IntegrityError:
        # The one-current-holder constraint. Reported as what it means
        # rather than as a database error: there is already a head, and
        # the admin has to end that appointment first.
        current = PositionAssignment.objects.filter(
            position=position, ends_on__isnull=True,
        ).select_related('user').first()
        held_by = current.user.username if current else 'someone else'
        return Response({
            'error': (
                f'{office} already has a current {position.get_kind_display()} '
                f'({held_by}). End that appointment first - two people cannot '
                f'hold it at the same time.'
            ),
            'reason': 'already_held',
        }, status=409)

    return Response(_assignment_payload(assignment), status=201)


@api_view(['POST'])
@permission_classes([IsSystemAdmin])
def end_assignment(request, assignment_id):
    """Close a post on a date. Never delete one."""
    try:
        assignment = PositionAssignment.objects.select_related(
            'position', 'position__office', 'user'
        ).get(id=assignment_id)
    except PositionAssignment.DoesNotExist:
        return Response({'error': 'Assignment not found'}, status=404)

    if assignment.position.kind in GUARDED_KINDS:
        failure = reauth_failure(request)
        if failure:
            return failure

    if assignment.ends_on is not None:
        return Response({
            'error': f'That appointment already ended on {assignment.ends_on}.',
            'reason': 'already_ended',
        }, status=409)

    # JSON carries a date as a string; the model's own field is a date.
    # Comparing the two raises rather than returning False, so the parse
    # happens before anything is compared.
    ends_on = request.data.get('ends_on')
    ends_on = parse_date(ends_on) if isinstance(ends_on, str) else ends_on
    if ends_on is None:
        ends_on = timezone.localdate()
    assignment.ends_on = ends_on

    if assignment.ends_on < assignment.starts_on:
        # Checked here rather than left to the database constraint, which
        # would surface as an IntegrityError with nothing an admin could
        # act on.
        return Response({
            'error': (
                f'An appointment cannot end before it started. This one '
                f'began on {assignment.starts_on}.'
            ),
            'reason': 'ends_before_start',
        }, status=400)

    try:
        assignment.save()
    except IntegrityError:
        return Response(
            {'error': 'That appointment could not be ended.'}, status=400
        )
    return Response(_assignment_payload(assignment))


@api_view(['GET'])
@permission_classes([IsSystemAdmin])
def positions_by_office(request):
    """Who holds what, per office, with the people who held it before.

    The history is the point. A position with nobody in it is as worth
    seeing as one that is filled - an office with no current Head cannot
    commit to anything.
    """
    rows = []
    offices = Office.objects.filter(is_active=True).prefetch_related(
        'positions__assignments__user'
    )
    for office in offices:
        positions = []
        for position in office.positions.all():
            assignments = sorted(
                position.assignments.all(),
                key=lambda a: (a.ends_on is not None, -a.starts_on.toordinal()),
            )
            current = [a for a in assignments if a.is_current]
            positions.append({
                'id': position.id,
                'kind': position.kind,
                'kind_label': position.get_kind_display(),
                'is_active': position.is_active,
                'held_by': [
                    {'user': a.user.username,
                     'full_name': a.user.full_name,
                     'assignment_id': a.id,
                     'is_acting': a.is_acting,
                     'since': a.starts_on}
                    for a in current
                ],
                'previously': [
                    {'user': a.user.username,
                     'is_acting': a.is_acting,
                     'from': a.starts_on, 'to': a.ends_on}
                    for a in assignments if not a.is_current
                ],
            })
        rows.append({
            'office_id': office.id,
            'office': office.name,
            'abbreviation': office.abbreviation,
            'is_approving_level': office.is_approving_level,
            'positions': positions,
            'has_current_head': any(
                p['kind'] == Position.HEAD and p['held_by'] for p in positions
            ),
        })

    return Response({
        'offices': rows,
        # Who currently carries the QMS positions, wherever they live. One
        # office in practice; the shape does not assume it.
        'qms': [
            {'kind': a.position.kind,
             'kind_label': a.position.get_kind_display(),
             'office': str(a.position.office),
             'user': a.user.username,
             'is_acting': a.is_acting}
            for a in PositionAssignment.objects.filter(
                position__kind__in=Position.QMS_KINDS,
                position__is_active=True,
                ends_on__isnull=True,
            ).select_related('position', 'position__office', 'user')
        ],
    })
