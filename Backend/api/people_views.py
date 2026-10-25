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
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import APIException

from .models import CustomUser, Office, Position, PositionAssignment
from .organisation_views import IsSystemAdmin
from .views import reauth_failure

# Positions whose holder commits an office, decides a request, or controls
# a document. Assigning or ending one asks for the password; an Encoder
# drafts, which is ordinary work.
GUARDED_KINDS = (Position.HEAD, Position.IMR, Position.DOCUMENT_CUSTODIAN)


class ApprovalConflict(APIException):
    status_code = 409


def _head_is_held(office, person):
    # Unended appointments include reserved future posts. Dated appointments
    # ending today or later still authorize their holder through access.py.
    return PositionAssignment.objects.filter(
        position__office=office, position__kind=Position.HEAD,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=timezone.localdate())).exclude(user=person).exists()


def _heads_held(people):
    """{office id: user ids holding its Head post} for the offices these
    applicants asked to head - one query for a page, where
    `_head_is_held` would ask once per applicant."""
    offices = {p.requested_office_id for p in people
               if p.requested_office_id and p.requested_position_kind == Position.HEAD}
    held = {}
    for office_id, user_id in PositionAssignment.objects.filter(
            position__office_id__in=offices, position__kind=Position.HEAD,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=timezone.localdate())).values_list(
            'position__office_id', 'user_id'):
        held.setdefault(office_id, set()).add(user_id)
    return held


def application_details(person, heads_held=None):
    office = person.requested_office
    warning = ''
    asks_head = office is not None and person.requested_position_kind == Position.HEAD
    if asks_head and heads_held is not None:
        head_taken = bool(heads_held.get(office.pk, set()) - {person.pk})
    else:
        head_taken = asks_head and _head_is_held(office, person)
    if office and not office.is_active:
        warning = f'{office.name} is no longer active; an office must be assigned manually.'
    elif asks_head and head_taken:
        warning = f'Unable to add as Head: {office.name} already has a Head. The applicant stays pending.'
    return {
        'requested_position_kind': person.requested_position_kind,
        'requested_position_label': person.get_requested_position_kind_display(),
        'approval_warning': warning,
    }


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


def _person_payload(person, assignments=None, heads_held=None):
    if assignments is None:
        assignments = person.position_assignments.select_related(
            'position', 'position__office'
        ).all()
    current = [a for a in assignments if a.is_current]
    return {
        **application_details(person, heads_held),
        'id': person.id,
        'username': person.username,
        'full_name': person.full_name,
        'email': person.email,
        'system_role': person.system_role,
        'is_approved': person.is_approved,
        'is_active': person.is_active,
        'date_joined': person.date_joined,
        # The office chosen at sign-up. Approval places them there as an
        # Encoder or Head; the posts below are what they actually hold.
        'requested_office': (
            {'id': person.requested_office_id, 'name': person.requested_office.name}
            if person.requested_office_id else None
        ),
        # Typed under "Office not listed"; blank otherwise.
        'requested_office_name': person.requested_office_name,
        'current_positions': [_assignment_payload(a) for a in current],
        'past_positions': [
            _assignment_payload(a) for a in assignments if not a.is_current
        ],
    }


PEOPLE_STATUSES = ('all', 'active', 'pending', 'awaiting_position', 'inactive')
POSITION_KINDS = {kind for kind, _ in Position.KIND_CHOICES} | {'none'}


def _rows(people):
    """Payloads for a page of people, from the page's prefetched posts and
    one query for the Head posts their applications ask for."""
    people = list(people)
    held = _heads_held(people)
    return [_person_payload(p, list(p.position_assignments.all()), held) for p in people]


def _with_posts(queryset):
    return queryset.select_related('requested_office').prefetch_related(Prefetch(
        'position_assignments',
        queryset=PositionAssignment.objects.select_related('position', 'position__office')))


@api_view(['GET'])
@permission_classes([IsSystemAdmin])
def people(request):
    """People, a page of 50 at a time, counts first and sign-ups on top.

    `?status=all|active|pending|awaiting_position|inactive` (`filter=` is
    kept for the older callers), `q=` name or username, `office=<id>`,
    `branch=<id>` (that office and everything beneath it), `position=`
    a kind or `none`, `page=`. Built in a fixed number of queries,
    whatever the page holds.

    The full list is system-admin only. Names are personal data under RA
    10173, and the process itself only ever needs a position.
    """
    from . import lists
    params = request.query_params
    today = timezone.localdate()
    current = PositionAssignment.objects.filter(user=OuterRef('pk'), starts_on__lte=today).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=today))
    everyone = CustomUser.objects.annotate(holds=Exists(current))
    counts = everyone.aggregate(
        all=Count('pk'),
        active=Count('pk', filter=Q(is_approved=True, is_active=True)),
        pending=Count('pk', filter=Q(is_approved=False)),
        # Approved, active, and holding nothing - so they can sign in and
        # do nothing at all, which is the state worth surfacing.
        awaiting_position=Count('pk', filter=Q(is_approved=True, is_active=True, holds=False)),
        inactive=Count('pk', filter=Q(is_approved=True, is_active=False)),
    )

    status = params.get('status') or params.get('filter') or 'all'
    if status not in PEOPLE_STATUSES:
        return lists.refuse('Unknown status.', 'invalid_status')
    queryset = everyone
    if status == 'active':
        queryset = queryset.filter(is_approved=True, is_active=True)
    elif status == 'pending':
        queryset = queryset.filter(is_approved=False)
    elif status == 'awaiting_position':
        queryset = queryset.filter(is_approved=True, is_active=True, holds=False)
    elif status == 'inactive':
        queryset = queryset.filter(is_approved=True, is_active=False)

    q = (params.get('q') or '').strip()
    if q:
        queryset = queryset.filter(Q(username__icontains=q) | Q(full_name__icontains=q))
    offices = None
    for name in ('office', 'branch'):
        if params.get(name):
            try:
                office_id = int(params[name])
            except ValueError:
                return lists.refuse(f'Choose a {name} from the list.', f'invalid_{name}')
            if name == 'office':
                offices = [office_id]
            else:
                from .org_tree import Tree
                offices = [office_id] + Tree().descendants(office_id)
    if offices is not None:
        queryset = queryset.filter(Exists(current.filter(position__office_id__in=offices)))
    kind = params.get('position')
    if kind:
        if kind not in POSITION_KINDS:
            return lists.refuse('Choose a position from the list.', 'invalid_position')
        queryset = (queryset.filter(holds=False) if kind == 'none' else
                    queryset.filter(Exists(current.filter(position__kind=kind))))
    page = lists.page_number(params)
    if page is None:
        return lists.refuse('Pages are numbered from 1.', 'invalid_page')

    rows, paging = lists.page_of(_with_posts(queryset).order_by('username', 'pk'), page)
    data = {
        'counts': counts,
        'pending_total': counts['pending'],
        'awaiting_position_total': counts['awaiting_position'],
        **paging,
        'people': _rows(rows),
    }
    if status != 'pending':
        # The sign-ups waiting on the admin, on top of whatever is listed.
        data['pending_signups'] = _rows(_with_posts(everyone.filter(is_approved=False))
                                        .order_by('date_joined', 'pk')[:lists.PAGE_SIZE])
    return Response(data)


def place_in_requested_office(person, approved_by):
    """On approval, make the office chosen at sign-up the person's post.

    The applicant's choice stands (user's decision, 10 Oct 2026): they
    receive the requested Encoder or Head post after re-authentication.
    An occupied Head post refuses the entire approval. Unresolved offices
    are approved without a post, with an explicit manual-assignment note.

    Returns `(assignment or None, note)`, the note saying why not.
    """
    if person.requested_office_id is None:
        typed = (f' ("{person.requested_office_name}")'
                 if person.requested_office_name else '')
        return None, f'Office not listed at sign-up{typed}; assign one by hand.'
    office = Office.objects.select_for_update().get(pk=person.requested_office_id)
    if not office.is_active:
        return None, f'{office.name} is no longer active; assign an office by hand.'
    today = timezone.localdate()
    kind = person.requested_position_kind
    if kind not in (Position.ENCODER, Position.HEAD):
        raise ApprovalConflict({'error': 'The requested position is invalid.', 'reason': 'invalid_position'})
    if kind == Position.HEAD and _head_is_held(office, person):
        raise ApprovalConflict({
            'error': f'Unable to add as Head: {office.name} already has a Head. The applicant stays pending.',
            'reason': 'already_held',
        })
    already = PositionAssignment.objects.filter(
        user=person, position__office=office, position__kind=kind,
        position__is_active=True, starts_on__lte=today,
    ).exclude(ends_on__lt=today).first()
    if already:
        return already, ''

    position, _ = Position.objects.get_or_create(office=office, kind=kind)
    if not position.is_active:
        return None, f'The {position.get_kind_display()} position at {office.name} is inactive; assign a post manually.'
    try:
        with transaction.atomic():
            assignment = PositionAssignment.objects.create(
                user=person, position=position, starts_on=today, assigned_by=approved_by,
            )
    except IntegrityError:
        if kind != Position.HEAD:
            raise
        raise ApprovalConflict({
            'error': f'Unable to add as Head: {office.name} already has a Head. The applicant stays pending.',
            'reason': 'already_held',
        })
    return assignment, ''


def approve(person, approved_by, full_name=None):
    """Approve an account and place it in its chosen office. One path for
    both approval screens."""
    with transaction.atomic():
        # Refresh under a lock so a repeated request cannot restore an ended
        # assignment or place someone twice after another admin's approval.
        locked = CustomUser.objects.select_for_update().get(pk=person.pk)
        if locked.is_approved:
            person.is_approved = True
            return None, 'Already approved; existing assignments were left unchanged.'
        placement = place_in_requested_office(locked, approved_by)
        person.is_approved = True
        fields = ['is_approved']
        if full_name is not None:
            person.full_name = full_name
            fields.append('full_name')
        person.save(update_fields=fields)
        return placement


@api_view(['POST'])
@permission_classes([IsSystemAdmin])
def approve_person(request, person_id):
    """Approve the account and requested post after confirming the admin."""
    failure = reauth_failure(request)
    if failure:
        return failure
    try:
        person = CustomUser.objects.get(id=person_id)
    except CustomUser.DoesNotExist:
        return Response({'error': 'Person not found'}, status=404)

    full_name = (request.data.get('full_name') or '').strip() if 'full_name' in request.data else None
    assignment, note = approve(person, request.user, full_name=full_name)
    data = _person_payload(person)
    data['placed'] = assignment is not None
    data['note'] = note
    data['message'] = (
        f'{person.username} approved as {assignment.position.get_kind_display()} at {assignment.position.office.name}.'
        if assignment else f'{person.username} approved.'
    )
    return Response(data)


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
    # A Head away (3C-2): current and coming delegations, one query.
    from django.utils import timezone
    from .models import HeadDelegation
    today = timezone.localdate()
    away = {}
    for d in HeadDelegation.objects.filter(ended_at__isnull=True, ends_on__gte=today)             .select_related('delegate').order_by('starts_on'):
        away.setdefault(d.office_id, []).append({
            'id': d.pk, 'delegate': d.delegate.full_name or d.delegate.username,
            'starts_on': d.starts_on, 'ends_on': d.ends_on,
            'current': d.starts_on <= today})
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
            'delegations': away.get(office.id, []),
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
