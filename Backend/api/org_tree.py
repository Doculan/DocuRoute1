"""The office tree in memory: descendants, branches, who concurs on what.

One query loads every office's id, parent and active flag; the tree is
walked in Python. Five hundred offices is a few kilobytes, and it saves
one query per node (spec §9: roll-ups in one pass, not per node).
"""

from .models import Manual, ManualOffice, ManualSeriesOffice, Office, OfficeLink


class Tree:
    def __init__(self):
        self.parent, self.active, self.name, self.children = {}, {}, {}, {}
        for pk, parent, active, name in Office.objects.values_list(
                'pk', 'parent_id', 'is_active', 'name'):
            self.parent[pk], self.active[pk], self.name[pk] = parent, active, name
            self.children.setdefault(parent, []).append(pk)

    def descendants(self, office_id):
        """Every office beneath this one (not itself), active or not."""
        found, stack = [], list(self.children.get(office_id, []))
        while stack:
            pk = stack.pop()
            if pk in found:      # a cycle in bad data must not hang a request
                continue
            found.append(pk)
            stack.extend(self.children.get(pk, []))
        return found

    def ancestors(self, office_id):
        seen, walk, current = set(), [], self.parent.get(office_id)
        while current is not None and current not in seen:
            seen.add(current)
            walk.append(current)
            current = self.parent.get(current)
        return walk

    def branch(self, office_id):
        """The top-level office this one sits under, for grouping."""
        walk = [office_id] + self.ancestors(office_id)
        return walk[-1]


def concurring_office_ids():
    """Active offices that concur on at least one document - through a
    series (for its documents that do not override it) or through a
    document's own override. Two queries."""
    through_series = ManualSeriesOffice.objects.filter(
        relationship=OfficeLink.CONCURRING, office__is_active=True,
        series__documents__offices_overridden=False,
    ).values_list('office_id', flat=True)
    own = ManualOffice.objects.filter(
        relationship=OfficeLink.CONCURRING, office__is_active=True,
        manual__offices_overridden=True,
    ).values_list('office_id', flat=True)
    return set(through_series) | set(own)


def concurring_offices_of(manual_ids):
    """{manual_id: [office_id, ...]} for these documents, by the same
    series/override rule as `Manual.effective_office_links`. Three queries
    for any number of documents."""
    manuals = list(Manual.objects.filter(pk__in=list(manual_ids))
                   .values_list('pk', 'series_id', 'offices_overridden'))
    by_series = {}
    for series_id, office_id in ManualSeriesOffice.objects.filter(
            relationship=OfficeLink.CONCURRING, office__is_active=True,
            series_id__in={s for _, s, o in manuals if s and not o},
    ).values_list('series_id', 'office_id'):
        by_series.setdefault(series_id, []).append(office_id)
    own = {}
    for manual_id, office_id in ManualOffice.objects.filter(
            relationship=OfficeLink.CONCURRING, office__is_active=True,
            manual_id__in=[m for m, _, o in manuals if o],
    ).values_list('manual_id', 'office_id'):
        own.setdefault(manual_id, []).append(office_id)
    return {
        pk: (own.get(pk, []) if overridden else by_series.get(series_id, []))
        for pk, series_id, overridden in manuals
    }


def expand_offices(office_ids_with_descendants, tree=None, concurring=None):
    """Office targets with "and everything beneath it": the office itself,
    plus every active descendant that concurs on a document."""
    tree = tree or Tree()
    concurring = concurring if concurring is not None else concurring_office_ids()
    result = set()
    for office_id, below in office_ids_with_descendants:
        result.add(office_id)
        if below:
            result |= {pk for pk in tree.descendants(office_id)
                       if tree.active.get(pk) and pk in concurring}
    return result

