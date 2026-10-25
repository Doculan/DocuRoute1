"""A Head on leave (spec §5.5; Phase 3C-2): delegation for a dated period.

The Head - or the system admin - names someone to act for the office's
Head between two dates, with a reason and the password. While it is
current the delegate:

- **acts as the Head**: `proposal_views._current_assignments` returns the
  Head post for them too, so every Head check (submit, concur or return,
  return to the Encoder, withdraw, Reviewed no change) admits them;
- **receives the Head's notices instead** (`notifications.current_posts`),
  addressed "(delegated)";
- **reads what the office reads** (`access.current_offices`);
- and every step they take is recorded as theirs, `acting_for` the Head
  (`AuditEvent.save`). Generated forms still print position titles only;
  the delegate signs on paper as the person present.

**Who may be a delegate** (Q-6): someone holding a current post in the
same office, or the Head of the office above.

**Maker-checker** (Q-6): a delegate may not submit, concur on or return a
proposal they drafted or sent to the Head - the Head's check would
collapse into the drafter's own.

Current means started, not yet past its end date, not ended early, and
the delegating Head still in post. Nothing is deleted: ending early
records who and when.
"""

from django.db.models import Q
from django.utils import timezone

from .models import AuditEvent, HeadDelegation, Position, PositionAssignment


def current(today=None):
    """Delegations in force today."""
    today = today or timezone.localdate()
    return HeadDelegation.objects.filter(
        starts_on__lte=today, ends_on__gte=today, ended_at__isnull=True,
        head_assignment__starts_on__lte=today,
    ).filter(Q(head_assignment__ends_on__isnull=True) | Q(head_assignment__ends_on__gte=today))


class Delegated:
    """The Head post, as a delegate holds it for the period: shaped like
    the `PositionAssignment` rows the Head checks read."""

    def __init__(self, delegation, position):
        self.pk = None
        self.delegation = delegation
        self.position = position
        self.position_id = position.pk
        self.user_id = delegation.delegate_id
        self.acting_for_id = delegation.head_assignment.user_id


def delegated_posts(user):
    """The Head posts this person holds by delegation today."""
    rows = current().filter(delegate=user).select_related(
        'head_assignment', 'head_assignment__position', 'head_assignment__position__office')
    return [Delegated(d, d.head_assignment.position) for d in rows
            if d.head_assignment.position.is_active and d.head_assignment.position.office.is_active]


def acting_for(user_id, position_id, today=None):
    """The Head this person acts for on that post, or None when they hold
    it themselves or not at all."""
    if not (user_id and position_id):
        return None
    today = today or timezone.localdate()
    holds = PositionAssignment.objects.filter(
        user_id=user_id, position_id=position_id, starts_on__lte=today,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today)).exists()
    if holds:
        return None
    return current(today).filter(
        delegate_id=user_id, head_assignment__position_id=position_id,
    ).values_list('head_assignment__user_id', flat=True).first()


def maker_checker_refusal(user, proposal, office):
    """A refusal when this person would check their own work as a
    delegate: they drafted the proposal, or sent it to the Head. None
    otherwise, and always None for the Head themselves."""
    head = Position.objects.filter(office=office, kind=Position.HEAD).first()
    if head is None or acting_for(user.pk, head.pk) is None:
        return None
    sent = proposal.events.filter(event=AuditEvent.SENT_TO_HEAD, actor=user).exists()
    if proposal.created_by_id == user.pk or sent:
        from rest_framework.response import Response
        return Response({
            'error': ('You drafted this proposal or sent it to the Head, so you cannot '
                      'also act as the Head on it. The Head, or another delegate, must.'),
            'reason': 'maker_checker',
        }, status=403)
    return None


def eligible(office, user, today=None):
    """May this person be the office's delegate? A current post in the
    office, or the Head of the office above."""
    today = today or timezone.localdate()
    posts = PositionAssignment.objects.filter(user=user, starts_on__lte=today).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=today)).filter(position__is_active=True)
    if posts.filter(position__office=office).exists():
        return True
    return bool(office.parent_id) and posts.filter(
        position__office_id=office.parent_id, position__kind=Position.HEAD).exists()


def overlapping(office, starts_on, ends_on, exclude=None):
    query = HeadDelegation.objects.filter(
        office=office, ended_at__isnull=True, starts_on__lte=ends_on, ends_on__gte=starts_on)
    if exclude is not None:
        query = query.exclude(pk=exclude)
    return query.exists()
