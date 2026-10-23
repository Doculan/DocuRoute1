"""The admin's Proposals list: every proposal, paged and filtered.

A stop-gap until the Phase 5 rebuild (MONITORING_UPDATE_SPEC.md §8). The
screen used to read the dashboard's six most recent proposals, so the
seventh was invisible to the admin and "All" meant "the last six".

Filtered and paged on the server, and built in a fixed number of queries
whatever the page holds - the version and concurrence counts come from
subqueries, not from a loop over the rows (§9).
"""

from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import Concurrence, Proposal, ProposalParticipant, ProposalVersion
from .views import IsAdminRole

PAGE_SIZE = 50

# Groups the screen offers besides the single statuses. "open" is every
# status still on its way, frozen ones included - the paperwork is still
# to come.
STATUS_GROUPS = {
    'open': Proposal.HOLDING_STATUSES,
    'closed': Proposal.CLOSED_STATUSES,
    'all': None,
}
STATUSES = {value for value, _ in Proposal.STATUS_CHOICES}


def _refuse(message, reason):
    return Response({'error': message, 'reason': reason}, status=400)


def _whole_number(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _count(queryset, key):
    """A per-proposal count as a subquery, so it costs no query per row."""
    return Coalesce(
        Subquery(
            queryset.values(key).annotate(n=Count('pk')).values('n')[:1],
            output_field=IntegerField(),
        ),
        0,
    )


@api_view(['GET'])
@permission_classes([IsAdminRole])
def admin_proposals(request):
    """`?status=open|closed|all|<status>&office=<id>&series=<id>&page=<n>`"""
    params = request.query_params
    queryset = Proposal.objects.all()

    status = params.get('status') or 'open'
    if status in STATUS_GROUPS:
        if STATUS_GROUPS[status] is not None:
            queryset = queryset.filter(status__in=STATUS_GROUPS[status])
    elif status in STATUSES:
        queryset = queryset.filter(status=status)
    else:
        return _refuse('Unknown status.', 'invalid_status')

    for name, field in (('office', 'initiating_office_id'),
                        ('series', 'manual__series_id')):
        if params.get(name):
            value = _whole_number(params[name])
            if value is None:
                return _refuse(f'Choose a {name} from the list.', f'invalid_{name}')
            queryset = queryset.filter(**{field: value})

    page = _whole_number(params.get('page', 1))
    if page is None or page < 1:
        return _refuse('Pages are numbered from 1.', 'invalid_page')

    total = queryset.count()
    latest = ProposalVersion.objects.filter(
        proposal=OuterRef('pk')).order_by('-number')
    rows = (
        queryset
        .select_related('manual', 'manual__series', 'initiating_office')
        .annotate(
            latest_version_id=Subquery(latest.values('pk')[:1]),
            version_number=Subquery(latest.values('number')[:1]),
            concurring_total=_count(ProposalParticipant.objects.filter(
                proposal=OuterRef('pk'), role=ProposalParticipant.CONCURRING,
            ), 'proposal'),
        )
        .annotate(concurred_total=_count(Concurrence.objects.filter(
            version=OuterRef('latest_version_id'), decision=Concurrence.CONCUR,
        ), 'version'))
        .order_by('-updated_at', '-id')
    )[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    return Response({
        'count': total,
        'page': page,
        'page_size': PAGE_SIZE,
        'pages': max(1, -(-total // PAGE_SIZE)),
        'results': [{
            'id': p.id,
            'manual_id': p.manual_id,
            'manual': p.manual.title,
            'series': p.manual.series.code if p.manual.series_id else None,
            'office_id': p.initiating_office_id,
            'office': str(p.initiating_office),
            'status': p.status,
            'status_label': p.get_status_display(),
            'dcr_number': p.dcr_number,
            'version': p.version_number,
            'concurred': p.concurred_total,
            'of': p.concurring_total,
            'updated_at': p.updated_at,
        } for p in rows],
    })
