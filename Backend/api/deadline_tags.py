"""The deadline tag (spec §6.7): one helper for every screen that lists or
opens a manual, so no screen is missed and none counts rows per manual.

`deadline_tags_for(user, manual_ids)` answers {manual_id: tag} for a page.

**Queries.** One when no manual on the page owes anything - the common
case. Otherwise two: the obligations, and every office's place in the
tree with the viewer's posts marked on it. A third only when the page
holds a manual the viewer neither owes nor oversees, to ask whether their
office concurs on it or reads it. None grows with the page.

**Who sees what** (§6.7):
- the office that owes it: "Deadline upcoming 12 Nov 2026", with the note
- Heads of offices above it, QMS staff and the admin: "Advised: {Office}
  · deadline upcoming 12 Nov 2026" - up to two offices, then "+n"
- offices that concur on the manual or read it: the muted "Revision
  advised for {Office}", because they will be asked to concur
- anyone else, another branch included: nothing

Only obligations naming a manual tag it (Q-3): an office-wide obligation
would tag every document the office concurs on, and shows in the banner
and the Deadlines panel instead. A met obligation shows as "Submitted
10 Nov" - or "Reviewed, no change 10 Nov" - until its due date passes.
"""

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from . import access
from .deadlines import urgency
from .models import DeadlineObligation, Manual, Office, Position, PositionAssignment

OWN, ADVISED, RELATED = 'own', 'advised', 'related'
MET = ('submitted', 'reviewed')
VIEW_ORDER = {OWN: 0, ADVISED: 1, RELATED: 2}
SHOWN_OFFICES = 2


def _long(day):
    return f'{day.day} {day:%b %Y}'


def _short(day):
    return f'{day.day} {day:%b}'


class _Viewer:
    """The viewer's offices and the Heads they hold, on the office tree:
    one query, walked in memory."""

    def __init__(self, user):
        today = timezone.localdate()
        held = PositionAssignment.objects.filter(
            user=user, position__office=OuterRef('pk'), position__is_active=True,
            starts_on__lte=today,
        ).filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))
        self.parent, self.mine, self.heads = {}, set(), set()
        for pk, parent, active, holds, heads in Office.objects.annotate(
                holds=Exists(held),
                heads=Exists(held.filter(position__kind=Position.HEAD)),
        ).values_list('pk', 'parent_id', 'is_active', 'holds', 'heads'):
            self.parent[pk] = parent
            if active and holds:
                self.mine.add(pk)
            if active and heads:
                self.heads.add(pk)

    def oversees(self, office_id):
        seen, current = set(), self.parent.get(office_id)
        while current is not None and current not in seen:
            if current in self.heads:
                return True
            seen.add(current)
            current = self.parent.get(current)
        return False


def _when(state, due_on, days):
    if state == 'overdue':
        return f'Overdue · was due {_long(due_on)}'
    if state == 'today':
        return 'Deadline today'
    if state == 'soon':
        return f'Deadline upcoming {_long(due_on)} · {days} day{"s" if days != 1 else ""}'
    return f'Deadline upcoming {_long(due_on)}'


def _offices(names):
    shown = ', '.join(names[:SHOWN_OFFICES])
    rest = len(names) - SHOWN_OFFICES
    return f'{shown} +{rest}' if rest > 0 else shown


def _tag(view, deadline, rows, today):
    """One deadline on one manual, as this viewer sees it, or None."""
    open_rows = [r for r in rows if r.state == DeadlineObligation.OPEN]
    owing = sorted({r.office.name for r in (open_rows or rows)})
    if open_rows:
        state, days = urgency(deadline, today)
        state = 'upcoming' if state == 'later' else state
        when = _when(state, deadline.due_on, days)
    else:
        if view == RELATED:
            return None            # nothing left to ask of anyone
        # Met by a proposal, or by "Reviewed, no change" (3C) - said as such.
        reviewed = all(r.state == DeadlineObligation.REVIEWED for r in rows)
        state, days = ('reviewed' if reviewed else 'submitted'), (deadline.due_on - today).days
        word = 'Reviewed, no change' if reviewed else 'Submitted'
        met = max((r.office_met_at for r in rows if r.office_met_at), default=None)
        when = f'{word} {_short(timezone.localtime(met))}' if met else word

    tag = {
        'deadline_id': deadline.pk,
        'view': view,
        'state': 'advised' if view == RELATED else state,
        'due_on': deadline.due_on.isoformat(),
        'days_left': days,
        'type': deadline.type.name,
        'advised': owing[:SHOWN_OFFICES],
        'advised_more': max(len(owing) - SHOWN_OFFICES, 0),
        'muted': view == RELATED or state in MET,
        'more': 0,
    }
    if view == OWN:
        tag['label'] = when
        tag['note'] = deadline.note
    elif view == ADVISED:
        tag['label'] = f'Advised: {_offices(owing)} · {when[0].lower()}{when[1:]}'
    else:
        tag['label'] = f'Revision advised for {_offices(owing)}'
    return tag


def deadline_tags_for(user, manual_ids, today=None):
    """{manual_id: tag} for the manuals on a page; manuals with nothing to
    show are absent, and callers write `tags.get(pk)`."""
    ids = {pk for pk in manual_ids if pk}
    if not ids or not (user and user.is_authenticated):
        return {}
    today = today or timezone.localdate()
    rows = list(DeadlineObligation.objects.filter(
        manual_id__in=ids, deadline__active=True,
    ).filter(
        Q(state=DeadlineObligation.OPEN) | Q(deadline__due_on__gte=today),
    ).select_related('deadline__type', 'office'))
    if not rows:
        return {}

    everyone = access.reads_everything(user)
    viewer = None if everyone else _Viewer(user)
    groups, unplaced = {}, set()
    for row in rows:
        if everyone:
            view = ADVISED
        elif row.office_id in viewer.mine:
            view = OWN
        elif viewer.oversees(row.office_id):
            view = ADVISED
        else:
            view = RELATED
            unplaced.add(row.manual_id)
        groups.setdefault((row.manual_id, row.deadline_id), {}).setdefault(view, []).append(row)

    related = set()
    if unplaced and viewer.mine:
        related = set(Manual.objects.filter(pk__in=unplaced).filter(
            access.reachable_q(list(viewer.mine))).values_list('pk', flat=True))

    # A change freeze (3D) pauses an open deadline's overdue notices; the
    # tag says so. Loaded only when a page carries tags.
    from . import freeze
    in_force = freeze.InForce()
    series = dict(Manual.objects.filter(pk__in=ids).values_list('pk', 'series_id')) \
        if in_force else {}

    found = {}
    for (manual_id, _), by_view in groups.items():
        # The nearest view wins: an office that owes it sees its own tag
        # even where it also oversees an office below that owes it too.
        view = min(by_view, key=VIEW_ORDER.get)
        if view == RELATED and manual_id not in related:
            continue
        rows_here = by_view[view]
        tag = _tag(view, rows_here[0].deadline, rows_here, today)
        if tag:
            held = None
            if in_force and tag['state'] not in MET:
                owed = [freeze.Owed(manual_id, series.get(manual_id))]
                held = next((f for f in (in_force.pausing(r.office_id, owed) for r in rows_here
                                         if r.state == DeadlineObligation.OPEN) if f), None)
            tag['frozen'] = freeze.payload(held)
            found.setdefault(manual_id, []).append(tag)

    tags = {}
    for manual_id, candidates in found.items():
        candidates.sort(key=lambda t: (VIEW_ORDER[t['view']], t['state'] in MET,
                                       t['due_on']))
        tags[manual_id] = {**candidates[0], 'more': len(candidates) - 1}
    return tags


def tag_rows(user, rows, key='manual_id'):
    """Set `deadline` on each row of a page from its `key`; one call for
    the page. Returns the rows."""
    tags = deadline_tags_for(user, [row.get(key) for row in rows])
    for row in rows:
        row['deadline'] = tags.get(row.get(key))
    return rows
