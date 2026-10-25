"""The deadline ladder in `run_monitoring` (Phase 3C, spec §5.4):
reminders, due day, overdue, escalation and its weekly repeat.

The unit is one office's open obligations on one deadline: an office that
owes three manuals on a deadline is reminded once, with the three named,
priority manuals first.

| Rung | When | Who |
|---|---|---|
| reminder | each of the deadline's `reminder_days` before the due date | the office's Head and Encoders (action) |
| due | the due date | the same |
| overdue | from the day after | the same, and the Head of the office above (info) |
| escalated | from 7 days after | the Head of the nearest approving office above, and the IMR and Custodian (info) |
| weekly | from 14 days after, once each ISO week | the escalation's recipients |

**Fallbacks** (Checkpoint 0, decision 3): with no approving office above,
the root approving offices (the President's office); an approving office
with no Head, the system admin.

**Once each.** A rung's notice has its own dedupe key
(`deadline:{d}:office:{o}:{rung}`), so a second run, or two at once, tells
nobody twice. A reminder whose day fell before the obligation existed is
skipped - an office given a deadline nine days out is not reminded "14
days" the same day. A run that missed a day sends the rung it missed.

**Cleared when met**: every open action notice of the unit, when the
office has no open obligation left on the deadline (`clear_met`, and at
once from `deadlines.on_submitted` and "Reviewed, no change").
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import notifications, system_log
from .models import (
    CustomUser, DeadlineObligation, Notification, Office, Position, SystemEvent,
)
from .notifications import ACTION, INFO, Recipient

ESCALATE_AFTER = 7       # days past due
WEEKLY_AFTER = 14        # days past due, the first weekly repeat

KINDS = {
    'reminder': (Notification.DEADLINE_REMINDER, SystemEvent.DEADLINE_REMINDER),
    'due': (Notification.DEADLINE_DUE, SystemEvent.DEADLINE_DUE),
    'overdue': (Notification.DEADLINE_OVERDUE, SystemEvent.DEADLINE_OVERDUE),
    'escalated': (Notification.DEADLINE_ESCALATED, SystemEvent.DEADLINE_ESCALATED),
    'weekly': (Notification.DEADLINE_ESCALATED, SystemEvent.DEADLINE_ESCALATED),
}
LADDER_NOTICES = [kind for kind, _ in KINDS.values()]
# Notices under a unit's key: the ladder's, and a priority notice.
UNIT_NOTICES = LADDER_NOTICES + [Notification.DEADLINE_SET]


def unit_key(deadline_id, office_id):
    return f'deadline:{deadline_id}:office:{office_id}:'


def rungs(deadline, created_on, today):
    """The (key suffix, rung, days left) due for a unit today."""
    days = (deadline.due_on - today).days
    if days > 0:
        reached = [n for n in (deadline.reminder_days or []) if n >= days]
        if reached:
            n = min(reached)
            if deadline.due_on - timedelta(days=n) >= created_on:
                return [(f'remind{n}', 'reminder', days)]
        return []
    if days == 0:
        return [('due', 'due', 0)]
    found = [('overdue', 'overdue', days)]
    if -days >= ESCALATE_AFTER:
        found.append(('escalated', 'escalated', days))
    if -days >= WEEKLY_AFTER:
        year, week, _ = today.isocalendar()
        found.append((f'weekly:{year}-{week:02}', 'weekly', days))
    return found


class _Offices:
    """Every active office's parent and approving flag, once per run."""

    def __init__(self):
        self.rows = {pk: (parent, approving) for pk, parent, approving in
                     Office.objects.filter(is_active=True)
                     .values_list('pk', 'parent_id', 'is_approving_level')}
        self.roots = [pk for pk, (parent, approving) in self.rows.items()
                      if approving and parent is None]

    def parent(self, office_id):
        return self.rows.get(office_id, (None,))[0]

    def approving_above(self, office_id):
        """The nearest approving office above, or the root approving
        offices when there is none (the President's office)."""
        seen, current = set(), self.parent(office_id)
        while current is not None and current not in seen:
            if self.rows.get(current, (None, False))[1]:
                return [current]
            seen.add(current)
            current = self.parent(current)
        return [pk for pk in self.roots if pk != office_id]


def _admins():
    return [Recipient(u.pk, None, None, 'System administrator', INFO)
            for u in CustomUser.objects.filter(system_role=CustomUser.SYSTEM_ADMIN,
                                               is_active=True)]


def _units(offices=None):
    """{(deadline_id, office_id): [obligations]} still open on active
    deadlines. One query."""
    query = DeadlineObligation.objects.filter(
        state=DeadlineObligation.OPEN, deadline__active=True,
    ).select_related('deadline', 'manual').order_by('deadline_id', 'office_id', '-priority', 'pk')
    if offices is not None:
        query = query.filter(office__in=offices)
    units = {}
    for ob in query:
        units.setdefault((ob.deadline_id, ob.office_id), []).append(ob)
    return units


def due_now(offices=None, today=None):
    """{dedupe key: (unit, rung, days)} for every rung due today."""
    today = today or timezone.localdate()
    found = {}
    for unit, obligations in _units(offices).items():
        deadline = obligations[0].deadline
        created = min(timezone.localtime(ob.created_at).date() for ob in obligations)
        for suffix, rung, days in rungs(deadline, created, today):
            found[unit_key(*unit) + suffix] = (unit, obligations, rung, days)
    return found


def _owed(obligations):
    named = [('Priority: ' if ob.priority else '') + ob.manual.title
             for ob in obligations if ob.manual_id]
    if not named:
        return 'Any proposal your office submits will count.'
    shown = ', '.join(named[:3])
    return f'Owed: {shown}' + (f' (+{len(named) - 3} more)' if len(named) > 3 else '')


def _words(rung, deadline, office_name, days):
    due = f'{deadline.due_on.day} {deadline.due_on:%b %Y}'
    if rung == 'reminder':
        return f'{deadline.title} — due in {days} day{"s" if days != 1 else ""} ({due})'
    if rung == 'due':
        return f'{deadline.title} — due today'
    if rung == 'overdue':
        return f'{deadline.title} — overdue since {due}'
    return f'{office_name}: {deadline.title} is {-days} days overdue (due {due})'


BATCH = 200


PAUSED_BY_FREEZE = ('overdue', 'escalated', 'weekly')


def plan(offices=None, max_batches=None, now=None, paused=None):
    """What a run would send, a batch at a time, writing nothing: lists of
    `Planned` (the unit, the rung, the deadline, the office, the
    obligations and the recipients). `send` writes exactly these; the
    dry run (`run_monitoring --dry-run`) prints them.

    A change freeze (3D) pauses overdue, escalation and the weekly repeat
    for the units it covers: their keys go to `paused`, unsent, so they
    are sent - caught up - by the first run after it is lifted."""
    from . import freeze
    now = now or timezone.now()
    today = timezone.localdate(now)
    due = due_now(offices, today)
    sent = set(Notification.objects.filter(dedupe_key__in=list(due))
               .values_list('dedupe_key', flat=True).distinct())
    todo = [k for k in due if k not in sent]
    in_force = freeze.InForce() if todo else None
    if in_force:
        held = [k for k in todo if due[k][2] in PAUSED_BY_FREEZE and in_force.pausing(
            due[k][0][1], [ob.manual for ob in due[k][1] if ob.manual_id])]
        if paused is not None:
            paused.extend(held)
        todo = [k for k in todo if k not in set(held)]
    if not todo:
        return
    tree = _Offices()
    qms = (notifications.qms_recipients(Position.IMR, INFO)
           + notifications.qms_recipients(Position.DOCUMENT_CUSTODIAN, INFO))
    admins = _admins()
    for number, start in enumerate(range(0, len(todo), BATCH)):
        if max_batches is not None and number >= max_batches:
            break
        keys = todo[start:start + BATCH]
        # The posts of every office this batch reaches, in one query.
        reach = set()
        for key in keys:
            (_, office_id), _, rung, _ = due[key]
            reach.add(office_id)
            reach.add(tree.parent(office_id))
            reach.update(tree.approving_above(office_id))
        office_rows = Office.objects.in_bulk([o for o in reach if o])
        posts = {}
        for assignment in notifications.current_posts(
                [o for o in reach if o], [Position.HEAD, Position.ENCODER]):
            posts.setdefault(assignment.position.office_id, []).append(assignment)

        def heads(office_id, severity):
            return [notifications._recipient(a, severity) for a in posts.get(office_id, [])
                    if a.position.kind == Position.HEAD]

        def owing(office_id):
            return [notifications._recipient(a, ACTION) for a in posts.get(office_id, [])]

        def escalated_to(office_id):
            """The approving offices above (or the President's), their
            Heads - the system admin where one has none - and the QMS."""
            found = []
            for above in tree.approving_above(office_id) or [None]:
                found += (heads(above, INFO) if above else []) or admins
            return found + qms

        planned = []
        for key in keys:
            (deadline_id, office_id), obligations, rung, days = due[key]
            if rung in ('reminder', 'due', 'overdue'):
                recipients = owing(office_id)
                if rung == 'overdue' and tree.parent(office_id):
                    recipients += heads(tree.parent(office_id), INFO)
            else:
                recipients = escalated_to(office_id)
            if recipients:      # a vacant post: the vacancy step reports it
                planned.append(Planned(key, rung, days, obligations[0].deadline,
                                       office_rows[office_id], obligations, recipients))
        yield planned


class Planned:
    def __init__(self, key, rung, days, deadline, office, obligations, recipients):
        self.key, self.rung, self.days, self.deadline = key, rung, days, deadline
        self.office, self.obligations, self.recipients = office, obligations, recipients
        self.manuals = [ob.manual for ob in obligations if ob.manual_id]

    @property
    def step(self):
        return self.key[len(unit_key(self.deadline.pk, self.office.pk)):]

    @property
    def title(self):
        return _words(self.rung, self.deadline, self.office.name, self.days)


def send(holder_extend, offices=None, max_batches=None, now=None, paused=None):
    """Send every rung due today that has not been sent. Returns the count."""
    now = now or timezone.now()
    count = 0
    for planned in plan(offices, max_batches, now, paused):
        with transaction.atomic():
            for item in planned:
                manual = item.manuals[0] if len(item.manuals) == 1 else None
                notice_kind, event_kind = KINDS[item.rung]
                event = system_log.record(
                    event_kind, office=item.office, manual=manual, at=now,
                    detail={'deadline': item.deadline.pk, 'rung': item.step,
                            'days_left': item.days,
                            'obligations': [ob.pk for ob in item.obligations]},
                )
                notifications.create(
                    notice_kind, item.recipients, title=item.title,
                    body=_owed(item.obligations), dedupe_key=item.key, manual=manual,
                    office_level=len(item.manuals) != 1, target=('deadline', item.deadline.pk),
                    system_event=event, now=now,
                )
                count += 1
        holder_extend()
    return count


def clear(pairs, by=None, now=None):
    """The open action notices of these (deadline, office) units, now
    that the office owes nothing more on the deadline."""
    now = now or timezone.now()
    still = set(DeadlineObligation.objects.filter(
        state=DeadlineObligation.OPEN,
        deadline_id__in={d for d, _ in pairs}, office_id__in={o for _, o in pairs},
    ).values_list('deadline_id', 'office_id'))
    done = [(d, o) for d, o in pairs if (d, o) not in still]
    if not done:
        return []
    query = Q()
    for deadline_id, office_id in done:
        query |= Q(kind__in=UNIT_NOTICES, dedupe_key__startswith=unit_key(deadline_id, office_id))
        query |= Q(kind=Notification.DEADLINE_SET, dedupe_key=f'deadline:{deadline_id}:set',
                   addressed_office_id=office_id)
    return notifications.resolve(Notification.objects.filter(query), by=by, now=now,
                                 reason='deadline met')


def clear_met(now=None):
    """From `run_monitoring`: units whose obligations were met, or whose
    deadline was set inactive, without a notice being cleared."""
    open_notices = Notification.objects.filter(
        kind__in=UNIT_NOTICES, severity=ACTION, acted_at__isnull=True,
        dedupe_key__contains=':office:',
    ).values_list('dedupe_key', flat=True).distinct()
    pairs = set()
    for key in open_notices:
        _, deadline_id, _, office_id = key.split(':')[:4]
        pairs.add((int(deadline_id), int(office_id)))
    if not pairs:
        return 0
    live = set(DeadlineObligation.objects.filter(
        state=DeadlineObligation.OPEN, deadline__active=True,
        deadline_id__in={d for d, _ in pairs},
    ).values_list('deadline_id', 'office_id'))
    gone = [pair for pair in pairs if pair not in live]
    if not gone:
        return 0
    query = Q()
    for deadline_id, office_id in gone:
        query |= Q(kind__in=UNIT_NOTICES, dedupe_key__startswith=unit_key(deadline_id, office_id))
    return len(notifications.resolve(Notification.objects.filter(query), now=now,
                                      reason='deadline met or withdrawn'))
