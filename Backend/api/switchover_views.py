"""The switchover: from departments to positions.

The organisation ships empty, so this cannot be a deploy. Positions
cannot exist until offices have been entered, and flipping the flag before
that would leave every staff account seeing nothing. It is an operation
the system admin performs when the data is ready - and the system has to
be able to say whether it is.

Two parts, answering different questions. The **flag** answers *when*. The
**gate** answers *whether it is safe*, and refuses while anything would
take a person's access away.

**There is no force.** Every blocker is somebody losing access to the
documents that govern their work. That is the one case where making it
easy to proceed is the wrong thing to build.

Rollback is flipping the flag back, and it is total: everything scoped
reads `AccessMode`, `can_propose` included. `Department` is untouched -
retiring it is phase 1c-ii, deliberately after the switch has held.
"""

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from . import access
from .models import (
    AccessMode, CustomUser, Manual, Office, Position, PositionAssignment,
)
from .organisation_views import IsSystemAdmin
from .views import reauth_failure


def _staff_who_would_lose_everything():
    """Approved, active, non-admin accounts holding no current position.

    They can sign in and would see nothing at all. Clearable two ways -
    give them a position, or deactivate the account - which matters
    because some of these are test accounts that will never hold one.
    """
    today = timezone.localdate()
    holding = set(
        PositionAssignment.objects.filter(
            position__is_active=True,
            position__office__is_active=True,
            starts_on__lte=today,
        ).filter(
            Q(ends_on__isnull=True) | Q(ends_on__gte=today)
        ).values_list('user_id', flat=True)
    )
    return CustomUser.objects.filter(
        is_approved=True, is_active=True,
    ).exclude(
        system_role=CustomUser.SYSTEM_ADMIN
    ).exclude(pk__in=holding).order_by('username')


def _documents_nobody_could_propose_against():
    """Documents with no concurring office.

    An owning office listed as concurring counts - it can propose, so the
    document is not stranded. That is why this walks the resolution rather
    than querying the link tables directly.
    """
    stranded = []
    for manual in Manual.objects.select_related(
        'series', 'series__owning_office', 'owning_office'
    ).order_by('title'):
        if not manual.can_be_proposed_against():
            stranded.append(manual)
    return stranded


def _owner_conflicts():
    """Configurations where an office would approve its own proposal."""
    conflicts = []
    for manual in Manual.objects.select_related(
        'series', 'series__owning_office', 'owning_office'
    ).order_by('title'):
        problem = manual.owner_proposal_conflict()
        if problem:
            conflicts.append({'document': manual.title, 'problem': problem})
    return conflicts


def _preview():
    """What each account sees today, and what it would see afterwards.

    The blockers catch people who would see *nothing*. This catches the
    case they cannot: somebody who holds a position, but the wrong one.
    Only a person reading the two numbers side by side will notice that.
    """
    total = Manual.objects.count()
    rows = []
    for person in CustomUser.objects.order_by('username'):
        # An admin's reach does not come from an office at all - the admin
        # screens go through `can_reach`, which passes them regardless -
        # so the department/position question simply does not apply.
        # Running them through the office rules would report "5 documents
        # today, 0 afterwards", which is alarming and false.
        scoped = person.system_role != CustomUser.SYSTEM_ADMIN

        if scoped:
            # Both answers asked for directly. The flag is never touched -
            # flipping it, even inside a try/finally, would mean a staff
            # member loading a page during the preview got the other rule.
            before = access.manuals_for(
                person, Manual.objects.all(), mode='department'
            ).count()
            after = access.manuals_for(
                person, Manual.objects.all(), mode='position'
            ).count()
        else:
            before = after = total

        offices = [str(o) for o in access.current_offices(person)]

        rows.append({
            'id': person.id,
            'username': person.username,
            'full_name': person.full_name,
            'system_role': person.system_role,
            'is_approved': person.is_approved,
            'is_active': person.is_active,
            'department': (
                person.department.name if person.department_id else None
            ),
            'offices': offices,
            'manuals_now': before,
            'manuals_after': after,
            # False for the system admin: their access is not scoped by
            # office either way, so the two numbers are the whole corpus
            # rather than a comparison.
            'scoped': scoped,
            'loses_everything': (
                person.is_approved and person.is_active
                and person.system_role != CustomUser.SYSTEM_ADMIN
                and before > 0 and after == 0
            ),
        })

    return rows


def _readiness():
    losing = list(_staff_who_would_lose_everything())
    stranded = _documents_nobody_could_propose_against()
    conflicts = _owner_conflicts()

    headless = [
        office for office in Office.objects.filter(is_active=True)
        if not PositionAssignment.objects.filter(
            position__office=office, position__kind=Position.HEAD,
            ends_on__isnull=True,
        ).exists()
    ]
    seriesless = Manual.objects.filter(series__isnull=True).count()

    # Notices whose targeting the new mode cannot express. They stop
    # showing rather than broadcasting - which is the safe reading, but
    # it is still a notice nobody sees, so it is worth saying out loud
    # before the switch rather than discovering it as silence.
    from .models import Announcement
    stale_notices = list(
        Announcement.objects.filter(
            active=True, office__isnull=True, department__isnull=False,
        ).select_related('department').order_by('title')
    )

    blockers = []
    if losing:
        blockers.append({
            'code': 'staff_without_positions',
            'count': len(losing),
            'detail': [
                {'id': p.id, 'username': p.username,
                 'department': p.department.name if p.department_id else None}
                for p in losing
            ],
            'message': (
                f'{len(losing)} approved account(s) hold no current position '
                f'and would see nothing. Assign them a position, or '
                f'deactivate the account if it will never hold one.'
            ),
        })
    if stranded:
        blockers.append({
            'code': 'documents_without_a_concurring_office',
            'count': len(stranded),
            'detail': [{'id': m.id, 'title': m.title} for m in stranded],
            'message': (
                f'{len(stranded)} document(s) have no concurring office, so '
                f'nobody could propose a change to them.'
            ),
        })
    if conflicts:
        blockers.append({
            'code': 'owner_would_approve_its_own_proposal',
            'count': len(conflicts),
            'detail': conflicts,
            'message': (
                f'{len(conflicts)} document(s) let their owning office '
                f'propose with no approving level above it.'
            ),
        })

    warnings = []
    if headless:
        warnings.append({
            'code': 'offices_without_a_head',
            'count': len(headless),
            'detail': [{'id': o.id, 'name': o.name} for o in headless],
            'message': (
                f'{len(headless)} office(s) have no current Head, so they can '
                f'read but cannot commit to anything.'
            ),
        })
    if stale_notices:
        warnings.append({
            'code': 'announcements_targeted_by_department',
            'count': len(stale_notices),
            'detail': [
                {'id': a.id, 'title': a.title,
                 'department': a.department.name}
                for a in stale_notices
            ],
            'message': (
                f'{len(stale_notices)} active announcement(s) are targeted at '
                f'a department. After the switch they stop showing to anyone '
                f'until they are given an office - they are not broadcast to '
                f'everyone.'
            ),
        })
    if seriesless:
        warnings.append({
            'code': 'documents_without_a_series',
            'count': seriesless,
            'detail': [],
            'message': (
                f'{seriesless} document(s) are not in a series. They are '
                f'reachable only through an owner or their own office links.'
            ),
        })

    return blockers, warnings


@api_view(['GET'])
@permission_classes([IsSystemAdmin])
def switchover(request):
    """Readiness, and what would change for each account."""
    mode = AccessMode.current()
    blockers, warnings = _readiness()
    rows = _preview()

    return Response({
        'by_position': mode.by_position,
        'switched_at': mode.switched_at,
        'switched_by': mode.switched_by.username if mode.switched_by_id else None,
        'ready': not blockers,
        'blockers': blockers,
        'warnings': warnings,
        # Accounts nobody has to worry about, kept apart so they do not
        # pad the list the admin is actually reading.
        'preview': [r for r in rows if r['is_active'] and r['is_approved']],
        'inactive': [r for r in rows if not r['is_active']],
        'unapproved': [
            r for r in rows if r['is_active'] and not r['is_approved']
        ],
    })


@api_view(['POST'])
@permission_classes([IsSystemAdmin])
def set_access_mode(request):
    """Flip it. Refused while any blocker stands.

    Switching back needs the password too: it is the same change of who
    can see what, in the other direction.
    """
    failure = reauth_failure(request)
    if failure:
        return failure

    wanted = bool(request.data.get('by_position'))
    mode = AccessMode.current()

    if wanted and not mode.by_position:
        blockers, _ = _readiness()
        if blockers:
            return Response({
                'error': (
                    'Not ready. '
                    + ' '.join(b['message'] for b in blockers)
                ),
                'reason': 'not_ready',
                'blockers': blockers,
            }, status=409)

    mode.by_position = wanted
    mode.switched_at = timezone.now()
    mode.switched_by = request.user
    mode.notes = (request.data.get('notes') or '').strip()
    mode.save()

    return Response({
        'by_position': mode.by_position,
        'switched_at': mode.switched_at,
        'switched_by': request.user.username,
    })
