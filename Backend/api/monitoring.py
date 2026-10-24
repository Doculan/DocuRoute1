"""Time-based work: proposals stalled in a stage, posts with nobody in them.

Run by `manage.py run_monitoring` every few minutes, and opportunistically
when a dashboard loads, so a stopped scheduler never leaves something
silently unflagged.

**Idempotent.** Every notice has a dedupe key and the database refuses a
second one per person, so a second run - or two at once - tells nobody
twice. The run lock only saves the work.

**Short transactions.** Candidates are read first, outside any
transaction, then handled 200 at a time, each batch in its own
transaction, with the lock extended after each. SQLite holds its write lock
for one batch, not one run, so the web requests in between are not starved.

Phase 3C adds the deadline ladder (`deadline_ladder`: reminders, due,
overdue, escalation, weekly) and the optional monthly periodic review
(`reviews.gather_due_reviews`, off by default) as further steps.
"""

import os
import socket
import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, Max, OuterRef, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import notifications, system_log
from .generation.common import position_title
from .models import (
    AuditEvent, Concurrence, CustomUser, JobLock, JobRun, MonitoringSetting,
    Notification, Position, PositionAssignment, Proposal, ProposalParticipant,
    ProposalVersion, SystemEvent,
)
from .notifications import ACTION, INFO, Recipient

LOCK = 'monitoring'
LOCK_MINUTES = 10
BATCH = 200
# A dashboard runs the steps itself only if the scheduler has not for this long.
DASHBOARD_AFTER = timedelta(minutes=15)

# status -> (threshold stage, events that put a proposal in that status)
STAGES = {
    Proposal.WITH_HEAD: (MonitoringSetting.WITH_HEAD, [AuditEvent.SENT_TO_HEAD]),
    Proposal.CONCURRENCE: (MonitoringSetting.CONCURRENCE, [AuditEvent.SUBMITTED]),
    Proposal.AWAITING_SIGNATURE: (MonitoringSetting.AWAITING_SIGNATURE,
                                  [AuditEvent.DOCUMENTS_GENERATED, AuditEvent.LOCKED]),
    Proposal.PACKAGE_RETURNED: (MonitoringSetting.AWAITING_SIGNATURE,
                                [AuditEvent.PACKAGE_RETURNED]),
    Proposal.READY_FOR_IMR: (MonitoringSetting.WITH_IMR, [AuditEvent.PACKAGE_COMPLETE]),
    Proposal.AWAITING_APPROVAL: (MonitoringSetting.WITH_IMR, [AuditEvent.IMR_ACCEPTED]),
    Proposal.WITH_CUSTODIAN: (MonitoringSetting.WITH_CUSTODIAN,
                              [AuditEvent.APPROVAL_UPLOADED, AuditEvent.PACKAGE_COMPLETE]),
}

STAGE_LABEL = {
    MonitoringSetting.WITH_HEAD: 'with the Head',
    MonitoringSetting.CONCURRENCE: 'in concurrence',
    MonitoringSetting.AWAITING_SIGNATURE: 'awaiting signed copies',
    MonitoringSetting.WITH_IMR: 'with the IMR',
    MonitoringSetting.WITH_CUSTODIAN: 'with the Document Custodian',
}

# Posts whose absence stops the process. Several Encoders may exist, and an
# office without one can still draft through its Head.
WATCHED_POSTS = (Position.HEAD, Position.IMR, Position.DOCUMENT_CUSTODIAN)


# ─── The lock ────────────────────────────────────────────────

def _holder():
    return f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'


def acquire(holder, now=None):
    """Take the lock if it has expired. One conditional UPDATE: two runs
    cannot both see it free."""
    now = now or timezone.now()
    JobLock.objects.get_or_create(name=LOCK, defaults={'expires_at': now - timedelta(seconds=1)})
    return JobLock.objects.filter(name=LOCK, expires_at__lt=now).update(
        holder=holder, acquired_at=now, expires_at=now + timedelta(minutes=LOCK_MINUTES),
    ) == 1


def extend(holder):
    JobLock.objects.filter(name=LOCK, holder=holder).update(
        expires_at=timezone.now() + timedelta(minutes=LOCK_MINUTES))


def release(holder):
    JobLock.objects.filter(name=LOCK, holder=holder).update(expires_at=timezone.now())


def _batches(ids, holder):
    for start in range(0, len(ids), BATCH):
        yield ids[start:start + BATCH]
        extend(holder)


# ─── Stalls ──────────────────────────────────────────────────

def _entered(queryset, status):
    """Annotate when each proposal entered `status`: the latest event that
    put it there, or its last update for rows older than the events."""
    _, events = STAGES[status]
    return queryset.annotate(entered=Coalesce(
        Max('events__at', filter=Q(events__event__in=events)), 'updated_at',
    ))


def _scoped(queryset, offices):
    if offices is None:
        return queryset
    return queryset.filter(
        Q(initiating_office__in=offices) | Q(participants__office__in=offices)
    ).distinct()


def stall_key(proposal_id, stage, entered):
    return f'stalled:{proposal_id}:{stage}:{entered:%Y%m%d%H%M}'


def _undecided(proposals):
    """For proposals in concurrence: the concurring offices that have not
    concurred on the current version. Three queries for the batch."""
    ids = [p.pk for p in proposals]
    latest = dict(ProposalVersion.objects.filter(proposal_id__in=ids)
                  .values('proposal_id').annotate(v=Max('number')).values_list('proposal_id', 'v'))
    concurred = set(Concurrence.objects.filter(
        version__proposal_id__in=ids, decision=Concurrence.CONCUR,
    ).values_list('version__proposal_id', 'version__number', 'office_id'))
    waiting = {}
    for p in ProposalParticipant.objects.filter(
            proposal_id__in=ids, role=ProposalParticipant.CONCURRING).select_related('office'):
        if (p.proposal_id, latest.get(p.proposal_id), p.office_id) not in concurred:
            waiting.setdefault(p.proposal_id, []).append(p.office)
    return waiting


def _holders(proposal, status, waiting):
    """Who holds the proposal now, as recipients, and what they are called."""
    if status == Proposal.WITH_HEAD:
        office = proposal.initiating_office
        heads = notifications.office_recipients([office.pk], head=ACTION, encoder=None)
        if heads:
            return heads, [f'the Head of {office.name}']
        above = (notifications.office_recipients([office.parent_id], head=ACTION, encoder=None)
                 if office.parent_id else [])
        return above + system_admins(), [f'a Head for {office.name} (none appointed)']
    if status == Proposal.CONCURRENCE:
        offices = waiting.get(proposal.pk, [])
        return (notifications.office_recipients([o.pk for o in offices], head=ACTION, encoder=INFO),
                [o.name for o in offices])
    if status in (Proposal.AWAITING_SIGNATURE, Proposal.PACKAGE_RETURNED):
        return (notifications.office_recipients([proposal.initiating_office_id]),
                [proposal.initiating_office.name])
    if status in (Proposal.READY_FOR_IMR, Proposal.AWAITING_APPROVAL):
        return notifications.qms_recipients(Position.IMR), ['the IMR']
    return notifications.qms_recipients(Position.DOCUMENT_CUSTODIAN), ['the Document Custodian']


def find_stalls(offices=None, now=None):
    """(proposal id, status, stage, entered) for everything past its threshold."""
    now = now or timezone.now()
    thresholds = MonitoringSetting.thresholds()
    found = []
    for status, (stage, _) in STAGES.items():
        cutoff = now - timedelta(days=thresholds[stage])
        rows = _entered(_scoped(Proposal.objects.filter(status=status), offices), status)
        found += [(pk, status, stage, entered) for pk, entered in
                  rows.filter(entered__lte=cutoff).values_list('pk', 'entered')]
    return found


def flag_stalls(holder, offices=None, max_batches=None, now=None):
    now = now or timezone.now()
    thresholds = MonitoringSetting.thresholds()
    stalls = find_stalls(offices, now)
    keys = {stall_key(pk, stage, entered): (pk, status, stage, entered)
            for pk, status, stage, entered in stalls}
    done = set(Notification.objects.filter(dedupe_key__in=list(keys))
               .values_list('dedupe_key', flat=True).distinct())
    todo = [k for k in keys if k not in done]
    flagged = 0
    for number, batch in enumerate(_batches(todo, holder)):
        if max_batches is not None and number >= max_batches:
            break
        with transaction.atomic():
            proposals = {p.pk: p for p in Proposal.objects.filter(
                pk__in=[keys[k][0] for k in batch]).select_related('manual', 'initiating_office')}
            waiting = _undecided([p for p in proposals.values()
                                  if p.status == Proposal.CONCURRENCE])
            for key in batch:
                pk, status, stage, entered = keys[key]
                proposal = proposals[pk]
                days = (now - entered).days
                holders, names = _holders(proposal, status, waiting)
                if not holders:
                    continue        # a vacant post: the vacancy step reports it
                event = system_log.record(
                    SystemEvent.STALLED, proposal=proposal, manual=proposal.manual, at=now,
                    detail={'stage': stage, 'status': status, 'days': days,
                            'threshold': thresholds[stage], 'waiting_on': names},
                )
                initiator = notifications.office_recipients(
                    [proposal.initiating_office_id], head=INFO, encoder=INFO)
                notifications.create(
                    Notification.STALLED, holders + initiator,
                    title=f'{proposal.manual.title}: {days} days {STAGE_LABEL[stage]}',
                    body=f'Waiting on {", ".join(names)}. The limit is {thresholds[stage]} days.',
                    dedupe_key=key, proposal=proposal, manual=proposal.manual,
                    system_event=event, now=now,
                )
                flagged += 1
    return flagged


def clear_ended_stalls(now=None):
    """Stall notices whose proposal has since left that stay in its stage."""
    open_notices = Notification.objects.filter(
        kind=Notification.STALLED, severity=ACTION, acted_at__isnull=True)
    open_keys = set(open_notices.values_list('dedupe_key', flat=True))
    if not open_keys:
        return 0
    current = {stall_key(pk, stage, entered) for pk, _, stage, entered in
               find_stalls(now=now)}
    ended = [k for k in open_keys if k not in current]
    if not ended:
        return 0
    return len(notifications.resolve(open_notices.filter(dedupe_key__in=ended),
                                     now=now, reason='left the stage'))


# ─── Vacancies ───────────────────────────────────────────────

def _current_holder():
    today = timezone.localdate()
    return PositionAssignment.objects.filter(
        position=OuterRef('pk'), starts_on__lte=today, user__is_active=True,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))


def find_vacancies(offices=None):
    query = Position.objects.filter(
        kind__in=WATCHED_POSTS, is_active=True, office__is_active=True,
    ).exclude(Exists(_current_holder())).annotate(
        last_end=Max('assignments__ends_on'),
    ).select_related('office', 'office__parent')
    if offices is not None:
        query = query.filter(Q(office__in=offices) | Q(office__parent__in=offices))
    return list(query)


def vacancy_key(position, since):
    return f'vacant:{position.pk}:{since:%Y%m%d}'


def _since(position):
    if position.last_end is not None:
        return position.last_end + timedelta(days=1)
    return timezone.localtime(position.created_at).date()


def system_admins():
    return [Recipient(u.pk, None, None, 'System administrator', ACTION)
            for u in CustomUser.objects.filter(system_role=CustomUser.SYSTEM_ADMIN,
                                               is_active=True)]


def flag_vacancies(holder, offices=None, max_batches=None, now=None):
    now = now or timezone.now()
    vacant = {vacancy_key(p, _since(p)): p for p in find_vacancies(offices)}
    done = set(Notification.objects.filter(dedupe_key__in=list(vacant))
               .values_list('dedupe_key', flat=True).distinct())
    todo = [k for k in vacant if k not in done]
    flagged = 0
    for number, batch in enumerate(_batches(todo, holder)):
        if max_batches is not None and number >= max_batches:
            break
        with transaction.atomic():
            for key in batch:
                position = vacant[key]
                office = position.office
                title = position_title(office.name, position.kind)
                since = _since(position)
                event = system_log.record(
                    SystemEvent.POSITION_VACANT, office=office, at=now,
                    detail={'position': position.pk, 'title': title,
                            'since': since.isoformat()},
                )
                parent_head = (notifications.office_recipients(
                    [office.parent_id], head=ACTION, encoder=None) if office.parent_id else [])
                notifications.create(
                    Notification.POSITION_VACANT, parent_head + system_admins(),
                    title=f'{title} has no holder',
                    body=f'Vacant since {since:%d %b %Y}. Assign someone in People.',
                    dedupe_key=key, office_level=True, target=('office', office.pk),
                    system_event=event, now=now,
                )
                flagged += 1
    return flagged


def clear_filled_vacancies(now=None):
    open_notices = Notification.objects.filter(
        kind=Notification.POSITION_VACANT, severity=ACTION, acted_at__isnull=True)
    keys = set(open_notices.values_list('dedupe_key', flat=True))
    if not keys:
        return 0
    still = {vacancy_key(p, _since(p)) for p in find_vacancies()}
    filled = [k for k in keys if k not in still]
    if not filled:
        return 0
    return len(notifications.resolve(open_notices.filter(dedupe_key__in=filled),
                                     now=now, reason='post filled'))


# ─── A run ───────────────────────────────────────────────────

STEPS = ('stalls', 'vacancies', 'deadlines', 'periodic_review')


def run(trigger=JobRun.SCHEDULED, only=None, offices=None, max_batches=None):
    """One pass of every step. Returns the counts, or None if another run
    holds the lock."""
    holder = _holder()
    if not acquire(holder):
        return None
    started = timezone.now()
    job = JobRun.objects.create(trigger=trigger, started_at=started)
    counts = {}
    try:
        steps = only or STEPS
        if 'stalls' in steps:
            counts['stalls_cleared'] = clear_ended_stalls()
            counts['stalls_flagged'] = flag_stalls(holder, offices, max_batches)
        if 'vacancies' in steps:
            counts['vacancies_cleared'] = clear_filled_vacancies()
            counts['vacancies_flagged'] = flag_vacancies(holder, offices, max_batches)
        if 'deadlines' in steps:
            from . import deadline_ladder
            counts['deadline_notices_cleared'] = deadline_ladder.clear_met()
            counts['deadline_notices_sent'] = deadline_ladder.send(
                lambda: extend(holder), offices, max_batches)
        if 'periodic_review' in steps and offices is None:
            from . import reviews
            counts['periodic_review_set'] = reviews.gather_due_reviews()
    except Exception as error:     # recorded, then raised: a run must not fail silently
        JobRun.objects.filter(pk=job.pk).update(
            finished_at=timezone.now(), counts=counts, error=repr(error))
        raise
    finally:
        release(holder)
    JobRun.objects.filter(pk=job.pk).update(finished_at=timezone.now(), counts=counts)
    return counts


def last_finished():
    return (JobRun.objects.filter(finished_at__isnull=False)
            .order_by('-finished_at').values_list('finished_at', flat=True).first())


def maybe_run_for(offices=None):
    """From a dashboard: if the scheduler has not run lately, do one batch
    of each step for these offices. Never waits for the lock and never
    breaks the page it was called from."""
    finished = last_finished()
    if finished is not None and timezone.now() - finished < DASHBOARD_AFTER:
        return None
    try:
        return run(trigger=JobRun.DASHBOARD, offices=offices, max_batches=1)
    except Exception:
        return None
