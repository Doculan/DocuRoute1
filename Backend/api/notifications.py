"""In-app notifications: who hears about which event.

Before this, a proposing office learned that
another office had concurred or returned its proposal only by opening the
proposal and looking - nothing told it to look.

| Event | Who is told |
|---|---|
| Submitted | Every concurring office |
| Concurred, returned | The proposing office |
| Locked | The proposing office |
| Completed signed DCR uploaded | The proposing office and current Document Custodian |

**Office notices reach everyone holding a current post there** -
the Encoder who drafted as well as the Head who signs -
because the person who has to redraft after a return is usually the
Encoder. Custodian handoffs additionally reach only current custodians,
not everyone in their office. The person who acted is left out: they know.

Routed from `concurrence_views._record`, inside the transaction that
writes the event, so an event that rolls back takes its notifications
with it. Events not in the table below notify nobody yet.
"""

from django.db.models import Q
from django.utils import timezone

from .models import (
    AuditEvent, CustomUser, Notification, Position, ProposalParticipant,
)


def holders_of(office_ids, kinds=None):
    """People holding a current post at any of these offices today."""
    if not office_ids:
        return CustomUser.objects.none()
    today = timezone.localdate()
    position_filter = {'position_assignments__position__kind__in': kinds} if kinds else {}
    return CustomUser.objects.filter(
        Q(position_assignments__ends_on__isnull=True)
        | Q(position_assignments__ends_on__gte=today),
        is_active=True,
        position_assignments__position__office_id__in=office_ids,
        position_assignments__position__is_active=True,
        position_assignments__position__office__is_active=True,
        position_assignments__starts_on__lte=today,
        **position_filter,
    ).distinct()


def _concurring_office_ids(proposal):
    return list(
        proposal.participants.filter(role=ProposalParticipant.CONCURRING)
        .values_list('office_id', flat=True)
    )


# Which offices hear about each event.
ROUTES = {
    AuditEvent.SUBMITTED: _concurring_office_ids,
    AuditEvent.CONCURRED: lambda p: [p.initiating_office_id],
    AuditEvent.RETURNED: lambda p: [p.initiating_office_id],
    AuditEvent.LOCKED: lambda p: [p.initiating_office_id],
}


def notify(event):
    """Write the inbox entries for one audit event. Returns how many."""
    if event.event == AuditEvent.APPROVAL_UPLOADED:
        office_people = holders_of([event.proposal.initiating_office_id])
        qms_offices = Position.objects.filter(kind=Position.DOCUMENT_CUSTODIAN).values_list('office_id', flat=True)
        custodians = holders_of(qms_offices, kinds=[Position.DOCUMENT_CUSTODIAN])
        recipients = (office_people | custodians).distinct().exclude(pk=event.actor_id)
        rows = [Notification(user=user, event=event) for user in recipients]
        Notification.objects.bulk_create(rows, ignore_conflicts=True)
        return len(rows)
    route = ROUTES.get(event.event)
    if route is None:
        return 0
    recipients = holders_of(route(event.proposal)).exclude(pk=event.actor_id)
    rows = [Notification(user=user, event=event) for user in recipients]
    Notification.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def message(event):
    """One line, as the inbox shows it."""
    proposal = event.proposal
    manual = proposal.manual.title
    office = event.office_name_at_time
    if event.event == AuditEvent.SUBMITTED:
        initiator = proposal.initiating_office.name
        return f'{initiator} asks your office to concur on {manual}.'
    if event.event == AuditEvent.CONCURRED:
        return f'{office} concurred on {manual}.'
    if event.event == AuditEvent.RETURNED:
        return f'{office} returned {manual} with feedback.'
    if event.event == AuditEvent.LOCKED:
        number = f' as {proposal.dcr_number}' if proposal.dcr_number else ''
        return f'{manual} is locked{number}.'
    if event.event == AuditEvent.APPROVAL_UPLOADED:
        by = 'the IMR' if event.position and event.position.kind == Position.IMR else office
        return (f'Signed DCR for {manual} uploaded by {by}; '
                'awaiting Document Custodian acceptance.')
    return f'{event.get_event_display()}: {manual}.'


def payload(notification):
    event = notification.event
    return {
        'id': notification.id,
        'proposal_id': event.proposal_id,
        'event': event.event,
        'message': message(event),
        # The returning office's feedback is what the drafter has to act
        # on, so it travels with the notice. Nothing else's detail does.
        'detail': event.detail if event.event == AuditEvent.RETURNED else '',
        'at': event.at,
        'read': notification.read_at is not None,
    }


def mark_read(user, proposal_id=None):
    """Mark this person's unread notices read - all of them, or one
    proposal's. Returns how many changed."""
    unread = Notification.objects.filter(user=user, read_at__isnull=True)
    if proposal_id is not None:
        unread = unread.filter(event__proposal_id=proposal_id)
    return unread.update(read_at=timezone.now())
