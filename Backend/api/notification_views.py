"""The inbox: a person's notifications, and marking them read.

One endpoint serves the bell (the first few, and the count) and the
notifications page (filtered and paged). The count is one indexed query -
unread info plus action not yet done - polled about once a minute.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import notifications
from .models import Notification

PAGE_SIZE = 20
FILTERS = {
    'all': None,
    'action': Notification.ACTION,
    'info': Notification.INFO,
}


def _whole_number(raw, default):
    try:
        return int(raw if raw not in (None, '') else default)
    except (TypeError, ValueError):
        return None


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def inbox(request):
    """`?filter=all|action|info&page=<n>&open=1` - `open` keeps only what
    still counts on the bell."""
    which = request.query_params.get('filter', 'all')
    if which not in FILTERS:
        return Response({'error': 'Filter by action, info or all.',
                         'reason': 'invalid_filter'}, status=400)
    page = _whole_number(request.query_params.get('page'), 1)
    if page is None or page < 1:
        return Response({'error': 'Pages are numbered from 1.',
                         'reason': 'invalid_page'}, status=400)

    mine = Notification.objects.filter(recipient=request.user)
    shown = mine
    if FILTERS[which]:
        shown = shown.filter(severity=FILTERS[which])
    if request.query_params.get('open') in ('1', 'true'):
        shown = shown.filter(notifications.open_q())
    total = shown.count()
    rows = shown.order_by('-created_at', '-id')[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    return Response({
        'unread': mine.filter(notifications.open_q()).count(),
        'count': total,
        'page': page,
        'pages': max(1, -(-total // PAGE_SIZE)),
        'notifications': [notifications.payload(n) for n in rows],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_read(request):
    """All of this person's notices, one proposal's (`proposal_id`), or the
    ones listed (`ids`)."""
    proposal_id = request.data.get('proposal_id')
    if proposal_id is not None:
        try:
            proposal_id = int(proposal_id)
        except (TypeError, ValueError):
            return Response({'error': 'proposal_id must be a number.',
                             'reason': 'invalid_proposal'}, status=400)
    ids = request.data.get('ids')
    if ids is not None:
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return Response({'error': 'ids must be a list of numbers.',
                             'reason': 'invalid_ids'}, status=400)
    changed = notifications.mark_read(request.user, proposal_id=proposal_id, ids=ids)
    return Response({'marked': changed})
