"""Deadlines: from what the admin targeted to what each office owes.

**Materialised.** Targets become `DeadlineObligation` rows when a deadline
is saved - one per office, or per office and manual where the target named
manuals - so banners, tags and monitoring read rows instead of resolving
targets on every request. The deadline keeps its own counts, updated in
the same transaction as any change to its obligations (spec §9).

**Met** (decision 1, Checkpoint 0; Q-1 and change 2, Phase 3 approval):

- a manual-level obligation, when the office submits a proposal for that
  manual for concurrence;
- an office-level one, when the office submits any proposal;
- and in both cases at creation, if such a proposal is already in flight.

Each records the proposal that met it. Withdrawing that proposal reopens
it - or hands it to another proposal still in flight; a denial does not.
Made effective is the document milestone, recorded beside it.
"""

from django.db.models import Count, Q
from django.utils import timezone

from . import notifications, system_log
from .models import (
    Deadline, DeadlineObligation, DeadlineTarget, Manual, Notification, Position,
    PositionAssignment, Proposal, SystemEvent,
)
from .org_tree import Tree, concurring_office_ids, concurring_offices_of, expand_offices

# Submitted for concurrence and not yet closed: a proposal in flight.
IN_FLIGHT = (Proposal.CONCURRENCE,) + Proposal.FROZEN_STATUSES
BATCH = 500


# ─── From targets to obligations ─────────────────────────────

def resolve(targets):
    """The (office_id, manual_id or None) pairs these targets mean.

    `targets` are `DeadlineTarget` rows or unsaved ones of the same shape.
    """
    concurring = concurring_office_ids()
    tree = Tree()
    pairs, offices, manual_ids = set(), [], set()
    for target in targets:
        if target.kind == DeadlineTarget.ALL:
            pairs |= {(o, None) for o in concurring}
        elif target.kind == DeadlineTarget.OFFICE:
            offices.append((target.office_id, target.include_descendants))
        elif target.kind == DeadlineTarget.SERIES:
            manual_ids |= set(Manual.objects.filter(series_id=target.series_id)
                              .values_list('pk', flat=True))
        elif target.kind == DeadlineTarget.MANUAL:
            manual_ids.add(target.manual_id)
    pairs |= {(o, None) for o in expand_offices(offices, tree, concurring)}
    for manual_id, office_ids in concurring_offices_of(manual_ids).items():
        pairs |= {(o, manual_id) for o in office_ids}
    return pairs


def holders(office_ids):
    """Current Heads and Encoders of these offices, as user ids."""
    today = timezone.localdate()
    return set(PositionAssignment.objects.filter(
        position__office_id__in=list(office_ids),
        position__kind__in=[Position.HEAD, Position.ENCODER],
        position__is_active=True, user__is_active=True, starts_on__lte=today,
    ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))
        .values_list('user_id', flat=True))


def preview(targets):
    """What saving would do: offices and people told, and what to warn."""
    pairs = resolve(targets)
    offices = {o for o, _ in pairs}
    warnings = []
    if pairs and all(m is None for _, m in pairs):
        warnings.append('No manuals named: any proposal this office submits will count.')
    concurring = concurring_office_ids()
    idle = [o for o in offices if o not in concurring]
    if idle:
        warnings.append(f'{len(idle)} targeted office(s) concur on no document, so '
                        f'no proposal of theirs can meet it.')
    return {
        'offices': len(offices),
        'people': len(holders(offices)),
        'obligations': len(pairs),
        'warnings': warnings,
    }


def _in_flight(office_ids):
    """The latest in-flight proposal per (office, manual) and per office."""
    by_pair, by_office = {}, {}
    for pk, office, manual in (Proposal.objects
                               .filter(initiating_office_id__in=list(office_ids),
                                       status__in=IN_FLIGHT)
                               .order_by('updated_at', 'pk')
                               .values_list('pk', 'initiating_office_id', 'manual_id')):
        by_pair[(office, manual)] = pk
        by_office[office] = pk
    return by_pair, by_office


def materialise(deadline, actor, now=None):
    """Bring the obligations into line with the targets. Returns the ones
    created. Open obligations no longer targeted go; met ones stay, since
    they are a record of work done. Call inside a transaction."""
    now = now or timezone.now()
    wanted = resolve(deadline.targets.all())
    existing = {(ob.office_id, ob.manual_id): ob for ob in deadline.obligations.all()}
    gone = [ob.pk for key, ob in existing.items()
            if key not in wanted and ob.state == DeadlineObligation.OPEN]
    if gone:
        DeadlineObligation.objects.filter(pk__in=gone).delete()

    fresh = sorted(wanted - set(existing), key=lambda pair: (pair[0], pair[1] or 0))
    by_pair, by_office = _in_flight({o for o, _ in fresh})
    rows = []
    for office, manual in fresh:
        proposal = by_pair.get((office, manual)) if manual else by_office.get(office)
        rows.append(DeadlineObligation(
            deadline=deadline, office_id=office, manual_id=manual, created_at=now,
            state=DeadlineObligation.SUBMITTED if proposal else DeadlineObligation.OPEN,
            office_met_at=now if proposal else None, met_by_proposal_id=proposal,
        ))
    DeadlineObligation.objects.bulk_create(rows, batch_size=BATCH)
    refresh_counts([deadline.pk])
    created = list(deadline.obligations.filter(created_at=now))
    _notify_set(deadline, created, actor, now)
    return created


def refresh_counts(deadline_ids):
    """The deadline's three counts, from its obligations. One query per
    deadline touched, inside the caller's transaction."""
    for deadline_id in set(deadline_ids):
        counts = DeadlineObligation.objects.filter(deadline_id=deadline_id).aggregate(
            total=Count('pk'),
            open=Count('pk', filter=Q(state=DeadlineObligation.OPEN)),
        )
        Deadline.objects.filter(pk=deadline_id).update(
            obligations_total=counts['total'], obligations_open=counts['open'],
            obligations_met=counts['total'] - counts['open'],
        )


# ─── Notices ─────────────────────────────────────────────────

def _owed(manual_titles, limit=3):
    shown = ', '.join(manual_titles[:limit])
    more = len(manual_titles) - limit
    return f'Owed: {shown}' + (f' (+{more} more)' if more > 0 else '')


def _notify_set(deadline, obligations, actor, now):
    """One notice per Head and Encoder of each office given an open
    obligation, in one batch, with one `deadline_set` cause in the log."""
    open_ones = [ob for ob in obligations if ob.state == DeadlineObligation.OPEN]
    if not open_ones:
        return
    titles = dict(Manual.objects.filter(
        pk__in={ob.manual_id for ob in open_ones if ob.manual_id}).values_list('pk', 'title'))
    per_office = {}
    for ob in open_ones:
        per_office.setdefault(ob.office_id, []).append(ob.manual_id)
    event = system_log.record(
        SystemEvent.DEADLINE_SET, user=actor, label='System administrator', at=now,
        detail={'deadline': deadline.pk, 'title': deadline.title,
                'due_on': deadline.due_on.isoformat(), 'offices': len(per_office)},
    )
    title = f'{deadline.title} — due {deadline.due_on:%d %b %Y}'
    entries = []
    recipients = notifications.office_recipients(list(per_office))
    for office_id, manual_ids in per_office.items():
        named = sorted(titles[m] for m in manual_ids if m)
        entries.append({
            'recipients': [r for r in recipients if r.office.pk == office_id],
            'title': title,
            'body': (_owed(named) if named else
                     'Any proposal your office submits will count.'),
            # Names its manual when the office owes exactly one; otherwise
            # it is about the office's obligations as a whole.
            'manual_id': manual_ids[0] if len(manual_ids) == 1 else None,
        })
    notifications.create_batch(
        Notification.DEADLINE_SET, entries, dedupe_key=f'deadline:{deadline.pk}:set',
        system_event=event, target=('deadline', deadline.pk), now=now,
    )


def _clear_set_notices(pairs, by, now):
    """An office whose obligations on a deadline are all met: its "deadline
    set" notice and every reminder of the ladder are done."""
    from .deadline_ladder import clear
    clear(pairs, by=by, now=now)


# ─── Priority manuals (spec §6.4) ────────────────────────────

def set_priority(deadline, office, manuals, actor, now=None):
    """Mark these manuals priority for this office under the deadline: the
    pair's obligation is created if the targets did not make one (met at
    once if a proposal is already in flight), and flagged. The office is
    told. Call inside a transaction. Returns the obligations flagged."""
    now = now or timezone.now()
    existing = {ob.manual_id: ob for ob in deadline.obligations.filter(
        office=office, manual__in=manuals)}
    by_pair, _ = _in_flight({office.pk})
    fresh = []
    for manual in manuals:
        if manual.pk in existing:
            continue
        proposal = by_pair.get((office.pk, manual.pk))
        fresh.append(DeadlineObligation(
            deadline=deadline, office=office, manual=manual, priority=True, created_at=now,
            state=DeadlineObligation.SUBMITTED if proposal else DeadlineObligation.OPEN,
            office_met_at=now if proposal else None, met_by_proposal_id=proposal,
        ))
    DeadlineObligation.objects.bulk_create(fresh)
    DeadlineObligation.objects.filter(pk__in=[ob.pk for ob in existing.values()]).update(priority=True)
    refresh_counts([deadline.pk])
    flagged = list(deadline.obligations.filter(office=office, manual__in=manuals))
    titles = sorted(m.title for m in manuals)
    event = system_log.record(
        SystemEvent.PRIORITY_SET, user=actor, label='System administrator', office=office, at=now,
        detail={'deadline': deadline.pk, 'obligations': [ob.pk for ob in flagged],
                'manuals': [m.pk for m in manuals]},
    )
    if any(ob.state == DeadlineObligation.OPEN for ob in flagged):
        notifications.create(
            Notification.DEADLINE_SET, notifications.office_recipients([office.pk]),
            title=f'Priority for {deadline.title} — due {deadline.due_on:%d %b %Y}',
            body=_owed(titles), manual=manuals[0] if len(manuals) == 1 else None,
            office_level=len(manuals) != 1, target=('deadline', deadline.pk),
            # Under the office's unit, so meeting the deadline clears it.
            dedupe_key=f'deadline:{deadline.pk}:office:{office.pk}:priority:{now:%Y%m%d%H%M%S%f}',
            system_event=event, now=now,
        )
    return flagged


# ─── From proposal transitions ───────────────────────────────

def on_submitted(proposal, user, now=None):
    """The office submitted: its matching open obligations are met."""
    now = now or timezone.now()
    open_ones = DeadlineObligation.objects.filter(
        state=DeadlineObligation.OPEN, deadline__active=True,
        office_id=proposal.initiating_office_id,
    ).filter(Q(manual_id=proposal.manual_id) | Q(manual__isnull=True))
    met = list(open_ones.values_list('pk', 'deadline_id'))
    if not met:
        return []
    DeadlineObligation.objects.filter(pk__in=[pk for pk, _ in met]).update(
        state=DeadlineObligation.SUBMITTED, office_met_at=now, met_by_proposal=proposal)
    refresh_counts([d for _, d in met])
    system_log.record(SystemEvent.OBLIGATION_MET, user=user, proposal=proposal,
                      manual=proposal.manual, at=now,
                      detail={'obligations': [pk for pk, _ in met], 'by': 'submitted'})
    _clear_set_notices({(d, proposal.initiating_office_id) for _, d in met}, user, now)
    return [pk for pk, _ in met]


def on_withdrawn(proposal, user, now=None):
    """The proposal that met obligations is withdrawn: each goes to
    another proposal of the office still in flight, or reopens."""
    now = now or timezone.now()
    held = list(DeadlineObligation.objects.filter(
        met_by_proposal=proposal, state=DeadlineObligation.SUBMITTED))
    if not held:
        return []
    by_pair, by_office = _in_flight({proposal.initiating_office_id})
    reopened = []
    for ob in held:
        other = (by_pair.get((ob.office_id, ob.manual_id)) if ob.manual_id
                 else by_office.get(ob.office_id))
        if other:
            ob.met_by_proposal_id = other
        else:
            ob.state, ob.office_met_at, ob.met_by_proposal = DeadlineObligation.OPEN, None, None
            reopened.append(ob.pk)
    DeadlineObligation.objects.bulk_update(held, ['state', 'office_met_at', 'met_by_proposal'])
    refresh_counts([ob.deadline_id for ob in held])
    if reopened:
        system_log.record(SystemEvent.OBLIGATION_REOPENED, user=user, proposal=proposal,
                          manual=proposal.manual, at=now,
                          detail={'obligations': reopened, 'by': 'withdrawn'})
    return reopened


def on_effective(proposal, now=None):
    """The document milestone, on the obligations this proposal met."""
    now = now or timezone.now()
    return DeadlineObligation.objects.filter(
        met_by_proposal=proposal, state=DeadlineObligation.SUBMITTED,
    ).update(state=DeadlineObligation.EFFECTIVE, effective_at=now)


# ─── For banners and panels ──────────────────────────────────

def urgency(deadline, today=None):
    """overdue, today, soon (inside the first reminder) or later."""
    today = today or timezone.localdate()
    days = (deadline.due_on - today).days
    window = max(deadline.reminder_days or [0])
    if days < 0:
        return 'overdue', days
    if days == 0:
        return 'today', days
    if days <= window:
        return 'soon', days
    return 'later', days


URGENCY_ORDER = {'overdue': 0, 'today': 1, 'soon': 2, 'later': 3}


def open_for(office_ids):
    """Open obligations of these offices on active deadlines."""
    return DeadlineObligation.objects.filter(
        office_id__in=list(office_ids), state=DeadlineObligation.OPEN, deadline__active=True,
    ).select_related('deadline', 'deadline__type', 'manual', 'office')

