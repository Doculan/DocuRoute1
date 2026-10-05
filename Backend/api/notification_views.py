"""The inbox: a person's notifications, and marking them read."""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import notifications
from .models import Notification

# Enough to cover a busy week; older notices are still in each proposal's
# own history, which is the record.
INBOX_LIMIT = 20


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def inbox(request):
    mine = Notification.objects.filter(user=request.user)
    rows = mine.select_related(
        'event', 'event__proposal', 'event__proposal__manual',
        'event__proposal__initiating_office',
    )[:INBOX_LIMIT]
    return Response({
        'unread': mine.filter(read_at__isnull=True).count(),
        'notifications': [notifications.payload(n) for n in rows],
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_read(request):
    """All of this person's notices, or one proposal's with `proposal_id`."""
    proposal_id = request.data.get('proposal_id')
    if proposal_id is not None:
        try:
            proposal_id = int(proposal_id)
        except (TypeError, ValueError):
            return Response({'error': 'proposal_id must be a number.'}, status=400)
    changed = notifications.mark_read(request.user, proposal_id=proposal_id)
    return Response({'marked': changed})
