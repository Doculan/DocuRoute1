"""Long lists, paged on the server and built in a fixed number of queries.

Phase 3B-2 (spec §9, §11.1). Each screen that once loaded everything -
My Manuals, admin Manuals, Awaiting, Involving, Requests, the
organisation's documents - now asks for one page of 50, and every row on
the page is built from a handful of bulk queries, never one per row. The
row builders here give the same values the per-row code gave; tests check
them against it.
"""

from django.db.models import Count, OuterRef, Q, Subquery
from rest_framework.response import Response

from . import access, document_status
from .deadline_tags import tag_rows
from .models import (
    DeadlineObligation, Manual, ManualOffice, ManualSection, ManualSeriesOffice, Office,
    OfficeLink, ProposalVersion, SectionChange,
)

PAGE_SIZE = 50


def refuse(message, reason):
    return Response({'error': message, 'reason': reason}, status=400)


def page_number(params):
    """The `page` asked for, from 1; None when it is not a whole number
    from 1, which the caller refuses with `invalid_page`."""
    try:
        page = int(params.get('page', 1))
    except (TypeError, ValueError):
        return None
    return page if page >= 1 else None


def page_of(queryset, page, total=None):
    """(the rows of this page, the paging fields). Two queries: the count
    and the page."""
    total = queryset.count() if total is None else total
    rows = list(queryset[(page - 1) * PAGE_SIZE: page * PAGE_SIZE])
    return rows, {'count': total, 'page': page, 'page_size': PAGE_SIZE,
                  'pages': max(1, -(-total // PAGE_SIZE))}


# ─── Manuals ─────────────────────────────────────────────────

MANUAL_RELATED = ('series', 'series__owning_office', 'owning_office',
                  'current_status__proposal', 'uploaded_by')


def manuals_in_reach(user):
    """The manuals this person reads, as a query with no duplicates: every
    manual for the admin and QMS staff, otherwise by `access.reachable_q`
    through an id subquery, so a manual linked twice is still one row."""
    everything = Manual.objects.all()
    if access.reads_everything(user):
        return everything
    return everything.filter(pk__in=access.manuals_for(user, Manual.objects.all()).values('pk'))


def series_groups(manuals, open_series):
    """Series with their counts, and the manuals in no series as one more
    group. One query."""
    groups = [{
        'series_id': row['series_id'], 'code': row['series__code'],
        'title': row['series__title'], 'count': row['n'],
        'open_deadlines': open_series.get(row['series_id'], 0),
    } for row in manuals.values('series_id', 'series__code', 'series__title')
        .annotate(n=Count('pk')).order_by('series__code')]
    # Unassigned last: the series are what a reader looks for.
    return sorted(groups, key=lambda g: g['series_id'] is None)


def open_deadlines_by_series(user, manuals):
    """{series_id: manuals with an open deadline} - those this person's
    offices owe, or every office's for the admin and QMS staff. One query
    (plus the person's offices)."""
    owed = DeadlineObligation.objects.filter(
        state=DeadlineObligation.OPEN, deadline__active=True,
        manual__in=manuals.values('pk'),
    )
    if not access.reads_everything(user):
        owed = owed.filter(office__in=[o.pk for o in access.current_offices(user)])
    return dict(owed.values('manual__series_id')
                .annotate(n=Count('manual_id', distinct=True))
                .values_list('manual__series_id', 'n'))


def _relationships(user, manuals):
    """{manual_id: "Owner · Concurring"} as `views._relationship_for` words
    it, for a page at once: the person's offices, then their links to the
    page's series and to the page's documents that override them."""
    mine = {o.pk for o in access.current_offices(user)}
    if not mine:
        return {}
    by_series, by_manual = {}, {}
    for series_id, office_id, kind in (ManualSeriesOffice.objects.filter(
            series_id__in={m.series_id for m in manuals if m.series_id and not m.offices_overridden},
            office_id__in=mine).order_by('office__name')
            .values_list('series_id', 'office_id', 'relationship')):
        by_series.setdefault(series_id, []).append(kind)
    for manual_id, office_id, kind in (ManualOffice.objects.filter(
            manual_id__in=[m.pk for m in manuals if m.offices_overridden],
            office_id__in=mine).order_by('office__name')
            .values_list('manual_id', 'office_id', 'relationship')):
        by_manual.setdefault(manual_id, []).append(kind)

    words = {}
    for manual in manuals:
        labels = []
        owner = manual.effective_owner
        if owner is not None and owner.pk in mine:
            labels.append('Owner')
        kinds = (by_manual.get(manual.pk, []) if manual.offices_overridden
                 else by_series.get(manual.series_id, []))
        labels += ['Concurring' if k == OfficeLink.CONCURRING else 'Read only' for k in kinds]
        words[manual.pk] = ' · '.join(dict.fromkeys(labels)) or None
    return words


def manual_rows(user, manuals):
    """The rows My Manuals and admin Manuals show, tagged. Fixed queries:
    section counts, the relationships, the tags."""
    manuals = list(manuals)
    counts = dict(ManualSection.objects.filter(manual__in=[m.pk for m in manuals])
                  .values('manual_id').annotate(n=Count('pk')).values_list('manual_id', 'n'))
    relationship = _relationships(user, manuals)
    rows = [{
        'id': m.pk,
        'title': m.title,
        'series_id': m.series_id,
        'series': m.series.code if m.series_id else None,
        'series_title': m.series.title if m.series_id else None,
        'owner': str(m.effective_owner) if m.effective_owner else None,
        'relationship': relationship.get(m.pk),
        'uploaded_by': m.uploaded_by.username if m.uploaded_by_id else 'N/A',
        'uploaded_at': m.uploaded_at,
        'section_count': counts.get(m.pk, 0),
        'version': m.version,
        'revision': m.revision,
        'display_status': f"v{m.version} rev{m.revision}",
        'status': document_status.status_payload(m.current_status),
    } for m in manuals]
    return tag_rows(user, rows, key='id')


def search_manuals(manuals, q):
    return manuals.filter(Q(title__icontains=q) | Q(series__code__icontains=q))


# ─── Proposals ───────────────────────────────────────────────

PROPOSAL_RELATED = ('manual', 'manual__series', 'initiating_office', 'created_by')


def with_latest_version(proposals):
    latest = ProposalVersion.objects.filter(proposal=OuterRef('pk')).order_by('-number')
    return proposals.annotate(latest_version_id=Subquery(latest.values('pk')[:1]),
                              version_number=Subquery(latest.values('number')[:1]))


def proposal_rows(user, proposals):
    """A list row for each proposal, from `with_latest_version` rows: what
    the Proposals tabs show. One query for the changed sections, then the
    tags. The editor's fields (blockers, sections) stay on the detail."""
    proposals = list(proposals)
    changed = {}
    for version_id, old, new in SectionChange.objects.filter(
            version_id__in=[p.latest_version_id for p in proposals if p.latest_version_id],
    ).values_list('version_id', 'old_text', 'new_text'):
        if (new or '').strip() != (old or '').strip():
            changed[version_id] = changed.get(version_id, 0) + 1
    rows = [{
        'id': p.pk,
        'manual_id': p.manual_id,
        'manual': p.manual.title,
        'series': p.manual.series.code if p.manual.series_id else None,
        'initiating_office': str(p.initiating_office),
        'initiating_office_id': p.initiating_office_id,
        'status': p.status,
        'status_label': p.get_status_display(),
        'dcr_number': p.dcr_number,
        'created_by': p.created_by.username,
        'created_at': p.created_at,
        'updated_at': p.updated_at,
        'version': p.version_number,
        'changed_sections': changed.get(p.latest_version_id, 0),
    } for p in proposals]
    return tag_rows(user, rows)


# ─── The organisation's documents ────────────────────────────

class _Approving:
    """Each office's parent and approving flag, for the route checks the
    document rows make. One query."""

    def __init__(self):
        self.parent, self.approving = {}, {}
        for pk, parent, approving in Office.objects.values_list(
                'pk', 'parent_id', 'is_approving_level'):
            self.parent[pk], self.approving[pk] = parent, approving

    def has_approving_above(self, office_id):
        seen, current = set(), self.parent.get(office_id)
        while current is not None and current not in seen:
            if self.approving.get(current):
                return True
            seen.add(current)
            current = self.parent.get(current)
        return False


def _concurring_by_manual(documents):
    """{manual_id: [office, ...]} by the series/override rule. Two queries."""
    series = {d.series_id for d in documents if d.series_id and not d.offices_overridden}
    by_series = {}
    for link in ManualSeriesOffice.objects.filter(
            series_id__in=series, relationship=OfficeLink.CONCURRING).select_related('office'):
        by_series.setdefault(link.series_id, []).append(link.office)
    own = {}
    for link in ManualOffice.objects.filter(
            manual_id__in=[d.pk for d in documents if d.offices_overridden],
            relationship=OfficeLink.CONCURRING).select_related('office'):
        own.setdefault(link.manual_id, []).append(link.office)
    return {d.pk: (own.get(d.pk, []) if d.offices_overridden
                   else by_series.get(d.series_id, []) if d.series_id else [])
            for d in documents}


def _owner_conflict(document, owner, concurring, tree):
    """`Manual.owner_proposal_conflict`, from what is already loaded."""
    if owner is None or owner not in concurring:
        return None
    if not document.stops_at_owner:
        if tree.has_approving_above(owner.pk):
            return None
        return (
            f'{owner} may propose changes to this document and there is '
            f'no approving level above it, so it would approve its own '
            f'proposal. Give it a parent that is an approving level, or '
            f'remove it from the concurring offices.'
        )
    return (
        f'{owner} may propose changes to this document, but approval '
        f'stops at the owner - so it would approve its own proposal. '
        f'Either let the route continue above {owner}, or remove it '
        f'from the concurring offices.'
    )


def document_rows(user, documents, office_brief):
    """The organisation screen's document rows, as
    `series_views._document_payload` builds one, for a page at once."""
    documents = list(documents)
    counts = dict(ManualSection.objects.filter(manual__in=[d.pk for d in documents])
                  .values('manual_id').annotate(n=Count('pk')).values_list('manual_id', 'n'))
    concurring = _concurring_by_manual(documents)
    tree = _Approving() if documents else None
    rows = []
    for d in documents:
        owner = d.effective_owner
        offices = concurring[d.pk]
        rows.append({
            'id': d.pk,
            'title': d.title,
            'series_id': d.series_id,
            'series_code': d.series.code if d.series_id else None,
            'section_count': counts.get(d.pk, 0),
            'is_unassigned': d.is_unassigned,
            'owner_is_inherited': d.owner_is_inherited,
            'offices_overridden': d.offices_overridden,
            'approval_stops_at_owner': d.approval_stops_at_owner,
            'effective_owner': office_brief(owner) if owner else None,
            'can_be_proposed_against': bool(offices),
            'owner_may_propose': owner is not None and owner in offices,
            'owner_conflict': _owner_conflict(d, owner, offices, tree),
        })
    return tag_rows(user, rows, key='id')
