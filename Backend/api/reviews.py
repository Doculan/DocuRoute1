"""Reviewed, no change (spec §6.5), and the periodic-review step.

Not every deadline produces a revision, and ISO expects documents to be
reviewed. A Head of an office that concurs on a document may record that
it was reviewed and needs no change:

- **password**, since it commits the office; the note is optional;
- writes a `ManualReview`, and sets the document's last-reviewed date and
  the next review due (the interval in `MonitoringSetting`, Q-4: 12 months);
- **meets that office's open obligations** on the document, and its
  office-level ones (Q-1), as `reviewed`, and clears their notices;
- refused while the office has a proposal open on the document: an office
  cannot say "no change" and be changing it.

**Periodic review** (Q-5, off by default): once a month `run_monitoring`
gathers the documents past their review date into one deadline,
"Periodic document review — {month}".
"""

import calendar
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access, deadlines, system_log
from .models import (
    CustomUser, Deadline, DeadlineObligation, DeadlineTarget, DeadlineType, Manual,
    ManualReview, MonitoringSetting, OfficeLink, Proposal, SystemEvent,
)

NOTE_LIMIT = 1000
PERIODIC_TYPE = 'Periodic document review'
PERIODIC_DAYS = 30        # how long a periodic-review deadline gives


def add_months(day, months):
    """The same day `months` later, or the month's last day if shorter."""
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def record(manual, office, user, position, note='', now=None):
    """Write the review and its effects. Returns (review, obligation ids met)."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    with transaction.atomic():
        met = list(DeadlineObligation.objects.filter(
            state=DeadlineObligation.OPEN, deadline__active=True, office=office,
        ).filter(Q(manual=manual) | Q(manual__isnull=True)).values_list('pk', 'deadline_id'))
        review = ManualReview.objects.create(
            manual=manual, office=office, office_name_at_time=office.name,
            reviewed_by=user, position=position, note=note,
            obligations=[pk for pk, _ in met], at=now,
        )
        interval = MonitoringSetting.value(MonitoringSetting.REVIEW_INTERVAL_MONTHS)
        Manual.objects.filter(pk=manual.pk).update(
            last_reviewed_on=today, next_review_due=add_months(today, interval))
        if met:
            DeadlineObligation.objects.filter(pk__in=[pk for pk, _ in met]).update(
                state=DeadlineObligation.REVIEWED, office_met_at=now)
            deadlines.refresh_counts([d for _, d in met])
        system_log.record(
            SystemEvent.REVIEWED_NO_CHANGE, user=user, position=position, office=office,
            manual=manual, at=now,
            detail={'review': review.pk, 'obligations': [pk for pk, _ in met],
                    'next_review_due': add_months(today, interval).isoformat()},
        )
        if met:
            deadlines._clear_set_notices({(d, office.pk) for _, d in met}, user, now)
    return review, [pk for pk, _ in met]


def _refuse(message, reason, status=400):
    return Response({'error': message, 'reason': reason}, status=status)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reviewed_no_change(request, manual_id):
    """`{office_id?, note?}`, with the password. See the module."""
    from .concurrence_views import _head_of
    from .views import reauth_failure
    manual = Manual.objects.filter(pk=manual_id).select_related('series').first()
    if manual is None:
        return _refuse('Document not found.', 'not_found', 404)

    concurring = {link.office_id for link in manual.effective_office_links()
                  if link.relationship == OfficeLink.CONCURRING}
    mine = [o for o in access.current_offices(request.user) if o.pk in concurring]
    if not mine:
        return _refuse('Only an office that concurs on this document reviews it.',
                       'not_concurring', 403)
    heads = [(o, _head_of(request.user, o)) for o in mine]
    heads = [(o, p) for o, p in heads if p is not None]
    if not heads:
        return _refuse('Only the Head records a review for the office.', 'not_head', 403)
    wanted = request.data.get('office_id')
    if wanted:
        heads = [(o, p) for o, p in heads if str(o.pk) == str(wanted)]
        if not heads:
            return _refuse('You are not the Head of that office.', 'not_head', 403)
    elif len(heads) > 1:
        return _refuse('Choose which office you are reviewing for.', 'office_required')
    office, position = heads[0]

    note = (request.data.get('note') or '').strip()
    if len(note) > NOTE_LIMIT:
        return _refuse(f'Keep the note under {NOTE_LIMIT} characters.', 'note_too_long')
    if Proposal.objects.filter(manual=manual, initiating_office=office,
                               status__in=Proposal.OPEN_STATUSES).exists():
        return _refuse(f'{office.name} has a proposal open on this document. '
                       f'Finish or withdraw it first.', 'proposal_open', 409)
    failure = reauth_failure(request)
    if failure:
        return failure

    review, met = record(manual, office, request.user, position, note)
    manual.refresh_from_db(fields=['last_reviewed_on', 'next_review_due'])
    return Response({
        'review_id': review.pk, 'office': office.name, 'obligations_met': len(met),
        'last_reviewed_on': manual.last_reviewed_on, 'next_review_due': manual.next_review_due,
    })


def gather_due_reviews(now=None):
    """The optional monthly step. Returns 1 when it set this month's
    deadline, else 0: off, already set this month, nothing due, or no
    system admin to set it in the name of."""
    if not MonitoringSetting.value(MonitoringSetting.PERIODIC_REVIEW):
        return 0
    now = now or timezone.now()
    today = timezone.localdate(now)
    title = f'{PERIODIC_TYPE} — {today:%B %Y}'
    kind, _ = DeadlineType.objects.get_or_create(name=PERIODIC_TYPE,
                                                 defaults={'is_preset': True})
    if Deadline.objects.filter(type=kind, title=title).exists():
        return 0
    due = list(Manual.objects.filter(next_review_due__lte=today).values_list('pk', flat=True))
    setter = CustomUser.objects.filter(system_role=CustomUser.SYSTEM_ADMIN,
                                       is_active=True).order_by('pk').first()
    if not due or setter is None:
        return 0
    with transaction.atomic():
        deadline = Deadline.objects.create(
            title=title, type=kind, created_by=setter,
            due_on=today + timedelta(days=PERIODIC_DAYS),
            note='Documents past their review date: revise, or record "Reviewed, no change".')
        DeadlineTarget.objects.bulk_create([
            DeadlineTarget(deadline=deadline, kind=DeadlineTarget.MANUAL, manual_id=pk)
            for pk in due])
        deadlines.materialise(deadline, setter, now=now)
    return 1
