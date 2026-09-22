"""The Organisation screens: offices, and the hierarchy they form.

Kept out of `views.py`, which is already 2,800 lines and holds the v3
application. These endpoints belong to a part of the system that did not
exist before and will outlive most of what is in there.

Two rules run through all of it.

**Nothing is deleted.** There is no delete endpoint below, and there will
not be one. An office is deactivated or merged into another; it stays, so
that a request from two years ago still resolves to the office that made
it. The closest thing to removal is `merge`, and even that leaves the
merged office in place with a pointer to its successor.

**Destructive-shaped actions re-authenticate.** Not creating or renaming -
prompts on routine work teach people to type their password without
reading it - but moving, deactivating and merging, because each silently
changes who will have to agree to future changes.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from .models import (
    CustomUser, Manual, ManualOffice, ManualSeries, ManualSeriesOffice,
    Office, Position, PositionAssignment,
)
from .views import reauth_failure


class IsSystemAdmin(BasePermission):
    """Configures the system. Separate from deciding requests.

    Reads `system_role`, not the v3 `role`: this is the first part of the
    application written against the new field, and the point of phase 1a
    was that it exists to be read.
    """

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, 'system_role', None) == CustomUser.SYSTEM_ADMIN
        )


def _office_payload(office, counts=None):
    data = {
        'id': office.id,
        'name': office.name,
        'abbreviation': office.abbreviation,
        'parent_id': office.parent_id,
        'is_approving_level': office.is_approving_level,
        'is_active': office.is_active,
        'merged_into_id': office.merged_into_id,
        'merged_into': str(office.merged_into) if office.merged_into_id else None,
    }
    if counts is not None:
        data.update(counts)
    return data


def _impact_of(office):
    """What hangs off an office, for the warning before deactivating or
    the preview before merging.

    A count of zero is still reported. "This office holds nothing" is the
    answer that makes the action safe, and leaving it out would make the
    admin guess whether it was checked.
    """
    positions = Position.objects.filter(office=office)
    return {
        'children': Office.objects.filter(parent=office, is_active=True).count(),
        'owned_series': ManualSeries.objects.filter(owning_office=office).count(),
        'owned_documents': Manual.objects.filter(owning_office=office).count(),
        'series_links': ManualSeriesOffice.objects.filter(office=office).count(),
        'document_links': ManualOffice.objects.filter(office=office).count(),
        'positions': positions.count(),
        'current_holders': PositionAssignment.objects.filter(
            position__in=positions, ends_on__isnull=True,
        ).count(),
    }


@api_view(['GET', 'POST'])
@permission_classes([IsSystemAdmin])
def offices(request):
    """The whole tree in one response, or a new office.

    The tree is sent flat, with `parent_id`, and assembled by the client.
    A nested payload would have to choose a shape for a hierarchy with no
    fixed depth, and the flat list is what the pickers elsewhere need
    anyway.
    """
    if request.method == 'GET':
        include_inactive = request.query_params.get('include_inactive') == 'true'
        queryset = Office.objects.select_related('merged_into')
        if not include_inactive:
            queryset = queryset.filter(is_active=True)

        rows = list(queryset)
        return Response({
            'offices': [_office_payload(o) for o in rows],
            'inactive_total': Office.objects.filter(is_active=False).count(),
        })

    name = (request.data.get('name') or '').strip()
    if not name:
        return Response({'error': 'An office needs a name.'}, status=400)

    office = Office(
        name=name,
        abbreviation=(request.data.get('abbreviation') or '').strip(),
        parent_id=request.data.get('parent_id') or None,
        is_approving_level=bool(request.data.get('is_approving_level')),
    )
    try:
        office.full_clean()
    except ValidationError as error:
        return Response({'error': '; '.join(
            m for messages in error.message_dict.values() for m in messages
        )}, status=400)

    office.save()
    return Response(_office_payload(office), status=201)


@api_view(['GET', 'PATCH'])
@permission_classes([IsSystemAdmin])
def office_detail(request, office_id):
    """Read one office with what hangs off it, or edit it.

    Renaming and re-flagging are ordinary edits. **Moving is not** - it
    changes the approval route of every document the office owns - so a
    change of parent asks for the password while a change of name does
    not.
    """
    try:
        office = Office.objects.select_related('parent', 'merged_into').get(
            id=office_id
        )
    except Office.DoesNotExist:
        return Response({'error': 'Office not found'}, status=404)

    if request.method == 'GET':
        return Response(_office_payload(office, _impact_of(office)))

    moving = (
        'parent_id' in request.data
        and (request.data.get('parent_id') or None) != office.parent_id
    )
    if moving:
        failure = reauth_failure(request)
        if failure:
            return failure

    if 'name' in request.data:
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'error': 'An office needs a name.'}, status=400)
        office.name = name
    if 'abbreviation' in request.data:
        office.abbreviation = (request.data.get('abbreviation') or '').strip()
    if 'is_approving_level' in request.data:
        office.is_approving_level = bool(request.data['is_approving_level'])
    if moving:
        office.parent_id = request.data.get('parent_id') or None

    try:
        office.full_clean()
    except ValidationError as error:
        return Response({'error': '; '.join(
            m for messages in error.message_dict.values() for m in messages
        )}, status=400)

    office.save()
    return Response(_office_payload(office, _impact_of(office)))


@api_view(['POST'])
@permission_classes([IsSystemAdmin])
def deactivate_office(request, office_id):
    """Retire an office without removing it.

    Refused while it still has active children: an office cannot be
    retired out from under the units reporting to it, and doing so
    silently would leave them orphaned in the tree with no sign of why.
    Move or retire them first.
    """
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        office = Office.objects.get(id=office_id)
    except Office.DoesNotExist:
        return Response({'error': 'Office not found'}, status=404)

    impact = _impact_of(office)
    if impact['children']:
        return Response({
            'error': (
                f'{office} still has {impact["children"]} active office(s) '
                f'under it. Move or deactivate those first.'
            ),
            'reason': 'has_children',
            'impact': impact,
        }, status=409)

    office.is_active = False
    office.save(update_fields=['is_active', 'updated_at'])
    return Response(_office_payload(office, _impact_of(office)))


@api_view(['POST'])
@permission_classes([IsSystemAdmin])
def reactivate_office(request, office_id):
    """The way back from a deactivation, for the case where it was a
    mistake. Not available once the office has been merged - that is a
    statement about where its work went, not a status."""
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        office = Office.objects.get(id=office_id)
    except Office.DoesNotExist:
        return Response({'error': 'Office not found'}, status=404)

    if office.merged_into_id:
        return Response({
            'error': (
                f'{office} was merged into {office.merged_into}. Undo the '
                f'merge rather than reactivating it, or the same work would '
                f'belong to two offices.'
            ),
            'reason': 'merged',
        }, status=409)

    office.is_active = True
    office.save(update_fields=['is_active', 'updated_at'])
    return Response(_office_payload(office, _impact_of(office)))


@api_view(['GET', 'POST'])
@permission_classes([IsSystemAdmin])
def merge_office(request, office_id):
    """GET previews what would move; POST moves it.

    Two calls on purpose. A merge rewrites ownership, office links and
    positions in one go, and an admin should see the list before agreeing
    to it rather than after.
    """
    try:
        office = Office.objects.get(id=office_id)
    except Office.DoesNotExist:
        return Response({'error': 'Office not found'}, status=404)

    target_id = request.query_params.get('into') or request.data.get('into')
    if not target_id:
        return Response({'error': 'Choose the office to merge into.'}, status=400)

    try:
        target = Office.objects.get(id=target_id)
    except (Office.DoesNotExist, ValueError, TypeError):
        return Response({'error': 'Target office not found'}, status=404)

    if target.pk == office.pk:
        return Response(
            {'error': 'An office cannot be merged into itself.'}, status=400
        )
    if any(a.pk == office.pk for a in target.ancestors()):
        return Response({
            'error': (
                f'{target} sits under {office}. Merging upward would put the '
                f'surviving office inside the one being retired.'
            ),
        }, status=400)

    preview = _impact_of(office)
    # Links the target already holds. Those rows cannot simply be
    # re-pointed - the unique constraint would refuse them - and the
    # target's own relationship is the one that survives, since it is the
    # office that continues to exist.
    existing_series = set(
        ManualSeriesOffice.objects.filter(office=target).values_list(
            'series_id', flat=True
        )
    )
    existing_documents = set(
        ManualOffice.objects.filter(office=target).values_list(
            'manual_id', flat=True
        )
    )
    existing_kinds = set(
        Position.objects.filter(office=target).values_list('kind', flat=True)
    )
    # Positions the surviving office already has. These cannot move across
    # - one row per (office, kind) - so they are retired in place, and
    # anyone currently holding one has that assignment **ended with a
    # date** rather than left open. An assignment with no end date is a
    # claim that someone still holds the post; leaving it open on a
    # position at a retired office makes that claim falsely, and every
    # reader asking "who holds this now" would believe it.
    conflicting = Position.objects.filter(office=office, kind__in=existing_kinds)
    ending = PositionAssignment.objects.filter(
        position__in=conflicting, ends_on__isnull=True,
    ).select_related('position', 'position__office', 'user')
    preview['series_links_already_held'] = ManualSeriesOffice.objects.filter(
        office=office, series_id__in=existing_series,
    ).count()
    preview['document_links_already_held'] = ManualOffice.objects.filter(
        office=office, manual_id__in=existing_documents,
    ).count()
    preview['positions_already_held'] = conflicting.count()
    preview['holders_ending'] = ending.count()
    preview['holders_ending_detail'] = [
        {
            'user': a.user.username,
            'position': a.position.get_kind_display(),
            'since': a.starts_on,
        }
        for a in ending
    ]

    if request.method == 'GET':
        return Response({
            'office': _office_payload(office),
            'into': _office_payload(target),
            'moves': preview,
        })

    failure = reauth_failure(request)
    if failure:
        return failure

    with transaction.atomic():
        ManualSeries.objects.filter(owning_office=office).update(
            owning_office=target
        )
        Manual.objects.filter(owning_office=office).update(owning_office=target)

        # Duplicates are dropped rather than re-pointed. The target
        # already relates to that series or document, and its own
        # relationship is the one that keeps applying.
        ManualSeriesOffice.objects.filter(
            office=office, series_id__in=existing_series,
        ).delete()
        ManualSeriesOffice.objects.filter(office=office).update(office=target)

        ManualOffice.objects.filter(
            office=office, manual_id__in=existing_documents,
        ).delete()
        ManualOffice.objects.filter(office=office).update(office=target)

        # End before deactivating, so the rows being closed are still
        # reachable through the same filter.
        PositionAssignment.objects.filter(
            position__in=conflicting, ends_on__isnull=True,
        ).update(ends_on=timezone.localdate())
        conflicting.update(is_active=False)

        # The rest move across with their assignments intact: the person
        # goes on holding the post, at the office that now exists.
        Position.objects.filter(office=office).exclude(
            kind__in=existing_kinds
        ).update(office=target)

        Office.objects.filter(parent=office).update(parent=target)

        office.merged_into = target
        office.is_active = False
        office.save(update_fields=['merged_into', 'is_active', 'updated_at'])

    return Response({
        'office': _office_payload(office),
        'into': _office_payload(target, _impact_of(target)),
        'moved': preview,
    })
