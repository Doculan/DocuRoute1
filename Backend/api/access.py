"""Who can reach which manual, and who can propose against it.

Access used to be thirteen separate decisions: nine inline comparisons of
a section's department against the user's, scattered through the views,
and four queryset filters. Thirteen places to change, and a missed one
looks like nothing at all - the screen still works, it just shows the
wrong person the wrong document.

So the rules are written once, here, and the views ask.

### Two questions, not one

`can_reach` for opening a document, which the system admin and QMS staff
pass for every document, and `can_propose` for changing one, which they do
not: proposing is an office's act.

**Access is by position.** A person reaches the documents linked to the
offices where they currently hold a position - as owner, concurring or
reader - and proposes only where one of those offices concurs. Until
v4.1.0 a switch chose between this and the v3 rule of one department per
person and per manual; the switch and departments are gone.

`is_staff` is not consulted anywhere. It is Django's flag for the
`/admin/` site, and four views once used it as a cross-department escape
hatch while the application's own `role` field uses `'staff'` to mean the
opposite - so an account made with `createsuperuser` silently bypassed
scoping whatever its role said.
"""

from django.db.models import Q
from django.utils import timezone


def is_admin(user):
    """Reach across the whole corpus, regardless of office.

    `role`, not `is_staff`.
    """
    return bool(
        user and user.is_authenticated and getattr(user, 'role', None) == 'admin'
    )


def is_qms_staff(user):
    """QMS staff by system role - the portal, not what they may decide.

    Reading reach only. What they may *decide* comes from the IMR or
    Document Custodian position they hold, checked where the decision is
    made.
    """
    from .models import CustomUser
    return bool(
        user and user.is_authenticated
        and getattr(user, 'system_role', None) == CustomUser.QMS_STAFF
    )


def reads_everything(user):
    """Whole-corpus reading: the system admin and QMS staff. The Document
    Custodian controls every document, and the IMR decides requests on any
    of them; neither can do that from the handful linked to the QMS office."""
    return is_admin(user) or is_qms_staff(user)


def has_unit(user):
    """Is there anything to scope this person's lists by?

    A current office. Whole-corpus readers need none.
    """
    return reads_everything(user) or bool(current_offices(user))


def current_offices(user):
    """Offices where this person holds a position today.

    Started and not ended, on an active position at an active office. A
    post at a retired office authorises nothing - the office is not doing
    that work any more, which is what retiring it said.
    """
    from .models import PositionAssignment
    today = timezone.localdate()
    assignments = PositionAssignment.objects.filter(
        user=user,
        position__is_active=True,
        position__office__is_active=True,
        starts_on__lte=today,
    ).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=today)
    ).select_related('position__office')
    # De-duplicated by id: one person can hold Encoder and Head in the
    # same office, which is one office, not two.
    seen, offices = set(), []
    for assignment in assignments:
        office = assignment.position.office
        if office.pk not in seen:
            seen.add(office.pk)
            offices.append(office)
    return offices


def offices_for(user):
    """The offices this person works in.

    An empty list means "assigned to nothing", which is a real state and
    not an error - the caller decides whether that is a 403 or an
    explanatory screen.
    """
    if not (user and user.is_authenticated):
        return []
    return current_offices(user)


def _office_ids(user):
    return {office.pk for office in offices_for(user)}


# ─── One document, one person ────────────────────────────────

def _linked_offices(manual, relationships):
    """The offices related to a manual in any of `relationships`.

    Goes through the document's own resolution, so the series/override
    rules are applied in exactly one place.
    """
    return {
        link.office_id for link in manual.effective_office_links()
        if link.relationship in relationships
    }


def _owner_ids(manual):
    owner = manual.effective_owner
    return {owner.pk} if owner is not None else set()


def can_reach(user, manual):
    """May this person open this manual?

    The system admin and QMS staff may open anything. Otherwise: any office
    linked to the document in any way at all - owner, concurring or
    reader. Reading is the permissive question; the process depends on
    people being able to read the documents that govern their work.
    """
    if manual is None:
        return False
    if reads_everything(user):
        return True

    mine = _office_ids(user)
    if not mine:
        return False

    from .models import OfficeLink
    related = _owner_ids(manual) | _linked_offices(
        manual, (OfficeLink.CONCURRING, OfficeLink.READER)
    )
    return bool(mine & related)


def can_reach_section(user, section):
    """The same question asked from a section.

    Most callers hold a section, and `section.manual` is the only route
    between the two - written once so a null section behaves the same way
    everywhere rather than raising in five different views.
    """
    if section is None:
        return False
    return can_reach(user, section.manual)


def can_propose(user, manual):
    """May this person propose a change to this manual?

    No admin bypass: proposing is an office's act, and an admin is not an
    office.

    **Only a concurring office may propose.** A reader office may not, and
    an owning office may not *unless it is also listed as concurring* -
    which is allowed, and common: the VPSD owns the Student Development
    Manual and its own staff draft changes to it.

    The safeguard against an office approving its own proposal is not
    here. It is a configuration rule, checked when the configuration is
    set - see `Manual.owner_proposal_conflict`.
    """
    if manual is None:
        return False

    mine = _office_ids(user)
    if not mine:
        return False

    from .models import OfficeLink
    return bool(mine & _linked_offices(manual, (OfficeLink.CONCURRING,)))


# ─── Querysets ───────────────────────────────────────────────
#
# These answer "what belongs to my offices", which is the question the
# staff screens ask. QMS staff read the whole corpus; the system admin's
# own screens do not come through here.


def reachable_q(offices, prefix=''):
    """The reachability rule as a queryset filter.

    Kept beside `can_reach` on purpose. If the list and the gate ever
    disagree, a screen shows a manual that then refuses to open, and the
    two are far enough apart in the code that nobody would look.

    `prefix` walks in from a section (`manual__`).
    """
    from .models import OfficeLink

    def field(name):
        return f'{prefix}{name}'

    return (
        # Owner, set on the document or inherited from its series.
        Q(**{field('owning_office__in'): offices})
        | Q(**{
            field('owning_office__isnull'): True,
            field('series__owning_office__in'): offices,
        })
        # Working offices: the document's own rows when it overrides,
        # its series' otherwise.
        | Q(**{
            field('offices_overridden'): True,
            field('office_links__office__in'): offices,
            field('office_links__relationship__in'): (
                OfficeLink.CONCURRING, OfficeLink.READER,
            ),
        })
        | Q(**{
            field('offices_overridden'): False,
            field('series__office_links__office__in'): offices,
            field('series__office_links__relationship__in'): (
                OfficeLink.CONCURRING, OfficeLink.READER,
            ),
        })
    )


def _narrow(user, queryset, prefix):
    if is_qms_staff(user):
        return queryset
    # No office matches nothing: an empty list filters to an empty result.
    offices = current_offices(user) if (user and user.is_authenticated) else []
    # distinct(): a manual linked to two of the person's offices would
    # otherwise arrive twice, and a duplicated row in a list reads as a
    # duplicated document.
    return queryset.filter(reachable_q(offices, prefix)).distinct()


def manuals_for(user, queryset):
    return _narrow(user, queryset, '')


def sections_for(user, queryset):
    return _narrow(user, queryset, 'manual__')
