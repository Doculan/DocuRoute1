"""Manual series and the documents inside them.

The screens where the system admin says who owns a document, who has to
agree to changing it, and who signs the result. Everything else in the
process reads what is entered here.

**Office links are set as a whole set, not one row at a time.** A PUT
replaces the lot. That is not laziness about REST: the relationship being
edited *is* a set, `offices_overridden` means "this document's set
replaces the series' set", and an add/remove pair would let a screen sit
half-way through a change with a set nobody chose. One call, one state.

**Re-authentication follows the same rule as the offices screen.** Naming
and renaming are free; anything that changes *who must agree* or *who
signs* asks for the password. That is the owner, the office links, and
moving a document between series.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import (
    Manual, ManualOffice, ManualSeries, ManualSeriesOffice, Office, OfficeLink,
)
from .organisation_views import IsSystemAdmin
from .views import reauth_failure

RELATIONSHIPS = {OfficeLink.CONCURRING, OfficeLink.READER}


def _office_brief(office):
    return {
        'id': office.id,
        'name': office.name,
        'abbreviation': office.abbreviation,
        'is_approving_level': office.is_approving_level,
    }


def _links_payload(links):
    return [
        {**_office_brief(link.office), 'relationship': link.relationship}
        for link in links
    ]


def _series_payload(series, detail=False):
    documents = list(series.documents.select_related('owning_office'))
    overriding = [d for d in documents if d.offices_overridden]

    data = {
        'id': series.id,
        'code': series.code,
        'title': series.title,
        'owning_office': (
            _office_brief(series.owning_office) if series.owning_office_id else None
        ),
        'approval_stops_at_owner': series.approval_stops_at_owner,
        'is_active': series.is_active,
        'document_count': len(documents),
        # Named rather than counted, because this is the cost of
        # replace-all: a change made here does not reach them, and the
        # admin should see which before making one.
        'overriding_documents': [
            {'id': d.id, 'title': d.title} for d in overriding
        ],
    }

    links = list(
        ManualSeriesOffice.objects.filter(series=series).select_related('office')
    )
    data['concurring'] = _links_payload(
        [l for l in links if l.relationship == OfficeLink.CONCURRING]
    )
    data['readers'] = _links_payload(
        [l for l in links if l.relationship == OfficeLink.READER]
    )

    if detail:
        data['documents'] = [_document_payload(d) for d in documents]
        data['approval_route'] = _route_for_series(series)
    return data


def _route_for_series(series):
    owner = series.owning_office
    if owner is None:
        return []
    route = [owner] if series.approval_stops_at_owner else (
        [owner] + [o for o in owner.ancestors() if o.is_approving_level]
    )
    return [_office_brief(o) for o in route]


def _document_payload(document, detail=False):
    data = {
        'id': document.id,
        'title': document.title,
        'series_id': document.series_id,
        'series_code': document.series.code if document.series_id else None,
        'section_count': document.sections.count(),
        'is_unassigned': document.is_unassigned,
        'owner_is_inherited': document.owner_is_inherited,
        'offices_overridden': document.offices_overridden,
        'approval_stops_at_owner': document.approval_stops_at_owner,
        'effective_owner': (
            _office_brief(document.effective_owner)
            if document.effective_owner else None
        ),
        # The question a reader of this screen actually has: can anybody
        # change this document yet?
        'can_be_proposed_against': document.can_be_proposed_against(),
    }
    if detail:
        links = document.effective_office_links()
        data['concurring'] = _links_payload(
            [l for l in links if l.relationship == OfficeLink.CONCURRING]
        )
        data['readers'] = _links_payload(
            [l for l in links if l.relationship == OfficeLink.READER]
        )
        data['approval_route'] = [
            _office_brief(o) for o in document.approval_route()
        ]
    return data


def _validation_error(error):
    """Name the field. "This field cannot be blank" without saying which
    field is a message that cannot be acted on - and it hid a real bug
    here for one test run."""
    parts = []
    for field, messages in error.message_dict.items():
        for message in messages:
            parts.append(
                message if field == '__all__' else f'{field}: {message}'
            )
    return Response({'error': '; '.join(parts)}, status=400)


def _apply_links(model, owner_field, owner, rows):
    """Replace an owner's whole link set in one go.

    Rows come in as `{office_id, relationship}`. Anything not named is
    removed, because the set is the thing being edited - a partial update
    would leave the screen and the database describing different sets.
    """
    wanted = {}
    for row in rows:
        try:
            office_id = int(row.get('office_id'))
        except (TypeError, ValueError):
            return None, Response({'error': 'Each office needs an id.'}, status=400)
        relationship = row.get('relationship')
        if relationship not in RELATIONSHIPS:
            return None, Response(
                {'error': f'Unknown relationship: {relationship!r}.'}, status=400
            )
        wanted[office_id] = relationship

    found = set(
        Office.objects.filter(id__in=wanted).values_list('id', flat=True)
    )
    missing = set(wanted) - found
    if missing:
        return None, Response(
            {'error': f'No such office: {sorted(missing)}.'}, status=400
        )

    with transaction.atomic():
        model.objects.filter(**{owner_field: owner}).exclude(
            office_id__in=wanted
        ).delete()
        for office_id, relationship in wanted.items():
            model.objects.update_or_create(
                office_id=office_id,
                defaults={'relationship': relationship},
                **{owner_field: owner},
            )
    return wanted, None


# ─── Series ──────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsSystemAdmin])
def series_list(request):
    if request.method == 'GET':
        rows = ManualSeries.objects.select_related('owning_office').all()
        return Response({
            'series': [_series_payload(s) for s in rows],
            'unassigned_documents': Manual.objects.filter(
                series__isnull=True
            ).count(),
        })

    code = (request.data.get('code') or '').strip()
    title = (request.data.get('title') or '').strip()
    if not code or not title:
        return Response(
            {'error': 'A series needs a code and a title.'}, status=400
        )
    if ManualSeries.objects.filter(code__iexact=code).exists():
        return Response(
            {'error': f'A series with the code "{code}" already exists.'},
            status=400,
        )

    series = ManualSeries(code=code, title=title)
    try:
        series.full_clean()
    except ValidationError as error:
        return _validation_error(error)
    series.save()
    return Response(_series_payload(series), status=201)


@api_view(['GET', 'PATCH'])
@permission_classes([IsSystemAdmin])
def series_detail(request, series_id):
    try:
        series = ManualSeries.objects.select_related('owning_office').get(
            id=series_id
        )
    except ManualSeries.DoesNotExist:
        return Response({'error': 'Series not found'}, status=404)

    if request.method == 'GET':
        return Response(_series_payload(series, detail=True))

    # Naming is free; ownership and the approval route are not.
    changes_authority = (
        ('owning_office_id' in request.data
         and (request.data.get('owning_office_id') or None) != series.owning_office_id)
        or ('approval_stops_at_owner' in request.data
            and bool(request.data['approval_stops_at_owner'])
            != series.approval_stops_at_owner)
    )
    if changes_authority:
        failure = reauth_failure(request)
        if failure:
            return failure

    if 'code' in request.data:
        code = (request.data.get('code') or '').strip()
        if not code:
            return Response({'error': 'A series needs a code.'}, status=400)
        if ManualSeries.objects.filter(code__iexact=code).exclude(
            pk=series.pk
        ).exists():
            return Response(
                {'error': f'A series with the code "{code}" already exists.'},
                status=400,
            )
        series.code = code
    if 'title' in request.data:
        title = (request.data.get('title') or '').strip()
        if not title:
            return Response({'error': 'A series needs a title.'}, status=400)
        series.title = title
    if 'owning_office_id' in request.data:
        series.owning_office_id = request.data.get('owning_office_id') or None
    if 'approval_stops_at_owner' in request.data:
        series.approval_stops_at_owner = bool(
            request.data['approval_stops_at_owner']
        )
    if 'is_active' in request.data:
        series.is_active = bool(request.data['is_active'])

    try:
        series.full_clean()
    except ValidationError as error:
        return _validation_error(error)
    series.save()
    return Response(_series_payload(series, detail=True))


@api_view(['PUT'])
@permission_classes([IsSystemAdmin])
def series_offices(request, series_id):
    """Replace the series' whole set of office links.

    Every document that inherits picks this up at once, which is the point
    of the series. Documents that override do **not** - the response says
    which, so the consequence is reported at the moment it happens rather
    than discovered later.
    """
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        series = ManualSeries.objects.get(id=series_id)
    except ManualSeries.DoesNotExist:
        return Response({'error': 'Series not found'}, status=404)

    rows = request.data.get('offices')
    if not isinstance(rows, list):
        return Response(
            {'error': 'Send the whole set of offices as a list.'}, status=400
        )

    _, error = _apply_links(ManualSeriesOffice, 'series', series, rows)
    if error:
        return error

    payload = _series_payload(series, detail=True)
    payload['did_not_reach'] = payload['overriding_documents']
    return Response(payload)


# ─── Documents ───────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsSystemAdmin])
def documents_list(request):
    """Every document, or only the ones nobody owns yet.

    The unassigned list is the one that matters at the start: nineteen
    documents arrive from v3 with no series and no owner, and the job of
    this phase is to empty it.
    """
    queryset = Manual.objects.select_related(
        'series', 'series__owning_office', 'owning_office'
    ).order_by('title')

    if request.query_params.get('unassigned') == 'true':
        queryset = queryset.filter(series__isnull=True, owning_office__isnull=True)
    series_id = request.query_params.get('series')
    if series_id:
        queryset = queryset.filter(series_id=series_id)

    return Response({
        'documents': [_document_payload(d) for d in queryset],
        'unassigned_total': Manual.objects.filter(
            series__isnull=True, owning_office__isnull=True
        ).count(),
    })


@api_view(['GET', 'PATCH'])
@permission_classes([IsSystemAdmin])
def document_detail(request, document_id):
    try:
        document = Manual.objects.select_related(
            'series', 'series__owning_office', 'owning_office'
        ).get(id=document_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Document not found'}, status=404)

    if request.method == 'GET':
        return Response(_document_payload(document, detail=True))

    changes_authority = (
        ('series_id' in request.data
         and (request.data.get('series_id') or None) != document.series_id)
        or ('owning_office_id' in request.data
            and (request.data.get('owning_office_id') or None)
            != document.owning_office_id)
        or 'approval_stops_at_owner' in request.data
    )
    if changes_authority:
        failure = reauth_failure(request)
        if failure:
            return failure

    if 'series_id' in request.data:
        document.series_id = request.data.get('series_id') or None
    if 'owning_office_id' in request.data:
        # Null here means inherit from the series, which is a different
        # statement from "nobody owns it" - that is null owner *and* null
        # series, and the screen says so.
        document.owning_office_id = request.data.get('owning_office_id') or None
    if 'approval_stops_at_owner' in request.data:
        value = request.data['approval_stops_at_owner']
        document.approval_stops_at_owner = None if value is None else bool(value)

    try:
        document.full_clean(exclude=['file', 'department'])
    except ValidationError as error:
        return _validation_error(error)
    document.save()
    return Response(_document_payload(document, detail=True))


@api_view(['PUT'])
@permission_classes([IsSystemAdmin])
def document_offices(request, document_id):
    """Set this document's own office links, or hand it back to the series.

    `{"inherit": true}` clears the override and deletes the document's
    rows: leaving them behind would mean the next person to switch the
    override on would silently get a set somebody chose months ago.
    """
    failure = reauth_failure(request)
    if failure:
        return failure

    try:
        document = Manual.objects.select_related('series').get(id=document_id)
    except Manual.DoesNotExist:
        return Response({'error': 'Document not found'}, status=404)

    if request.data.get('inherit'):
        with transaction.atomic():
            ManualOffice.objects.filter(manual=document).delete()
            document.offices_overridden = False
            document.save(update_fields=['offices_overridden'])
        return Response(_document_payload(document, detail=True))

    rows = request.data.get('offices')
    if not isinstance(rows, list):
        return Response(
            {'error': 'Send the whole set of offices as a list.'}, status=400
        )
    if document.series_id is None and not rows:
        return Response({
            'error': (
                'This document has no series to inherit from, so an empty '
                'set would leave nobody able to propose changes to it.'
            ),
        }, status=400)

    _, error = _apply_links(ManualOffice, 'manual', document, rows)
    if error:
        return error

    if not document.offices_overridden:
        document.offices_overridden = True
        document.save(update_fields=['offices_overridden'])

    return Response(_document_payload(document, detail=True))
