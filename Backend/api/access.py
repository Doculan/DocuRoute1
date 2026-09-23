"""Who can reach which manual, and who can propose against it.

Access used to be thirteen separate decisions: nine inline comparisons of
`section.manual.department != request.user.department` scattered through
the views, and four queryset filters. Thirteen places to change at the
switchover, and a missed one looks like nothing at all - the screen still
works, it just shows the wrong person the wrong document.

So the rules are written once, here, and the views ask.

### Two questions, not one

The thirteen sites were not thirteen copies of one rule. Four of them
(`list_sections`, `review_section`, `review_delete_section`,
`merge_sections`) let an admin through; the five submission paths
(`upload_revision`, `propose_text_revision`, `propose_merge`, and the two
pre-assessment endpoints) let nobody through - an admin outside the
department was refused like anyone else. Collapsing them into a single
helper would have handed admins the right to propose changes to any
manual in the university, which no v3 screen allowed.

So there are two: `can_reach` for opening a document, which admins pass,
and `can_propose` for changing one, which they do not.

### The switchover

`AccessMode.by_position` decides which answer every function here gives.

- **off (v3)** - one department per person, one per manual. Reading and
  proposing are the same question.
- **on (v4)** - the offices where the person currently holds a position,
  against the offices linked to the document. Reading and proposing come
  apart: an owning or reader office opens a document, only a concurring
  office may propose against it.

**Every function honours the flag, `can_propose` included.** Rollback has
to be total - a flag that restores *most* of the old behaviour is worse
than no flag, because the part it does not restore is the part nobody
thinks to check.

`is_staff` is not consulted anywhere. It is Django's flag for the
`/admin/` site, and four views were using it as a cross-department escape
hatch while the application's own `role` field uses `'staff'` to mean the
opposite - so an account made with `createsuperuser` silently bypassed
scoping whatever its role said.
"""

from django.db.models import Q
from django.utils import timezone


def by_position():
    """Is access scoped by position yet?

    Read per call rather than cached at import: the flag is flipped from a
    screen while the process is running, and a cached copy would leave
    some requests answering with the old rule.
    """
    from .models import AccessMode
    return AccessMode.current().by_position


def is_admin(user):
    """Reach across the whole corpus, regardless of office.

    `role`, not `is_staff`. At 1c-ii this becomes `system_role`, once the
    department branch below is gone and that field is authoritative.
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
    """Whole-corpus reading: the system admin, and - once access is by
    position - QMS staff. The Document Custodian controls every document,
    and the IMR decides requests on any of them; neither can do that from
    the handful linked to the QMS office."""
    return is_admin(user) or (is_qms_staff(user) and by_position())


def has_unit(user):
    """Is there anything to scope this person's lists by?

    Before the switch, a department. After it, a current office - the
    department is a v3 field that v4 accounts need not have, and asking
    for it turned away people who hold positions. Whole-corpus readers
    need neither.
    """
    if reads_everything(user):
        return True
    if by_position():
        return bool(current_offices(user))
    return getattr(user, 'department', None) is not None


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
    """The organisational units this person works in.

    An empty list means "assigned to nothing", which is a real state and
    not an error - the caller decides whether that is a 403 or an
    explanatory screen.
    """
    if not (user and user.is_authenticated):
        return []
    if by_position():
        return current_offices(user)
    department = getattr(user, 'department', None)
    return [department] if department is not None else []


def _office_ids(user):
    return {office.pk for office in offices_for(user) if office is not None}


# ─── One document, one person ────────────────────────────────

def _linked_offices(manual, relationships):
    """The offices related to a manual in any of `relationships`.

    Goes through the document's own resolution, so the series/override
    rules are applied in exactly one place.
    """
    from .models import OfficeLink   # noqa: F401  (vocabulary lives there)
    return {
        link.office_id for link in manual.effective_office_links()
        if link.relationship in relationships
    }


def _owner_ids(manual):
    owner = manual.effective_owner
    return {owner.pk} if owner is not None else set()


def can_reach(user, manual):
    """May this person open this manual?

    Admins may open anything. Otherwise: their department (v3), or any
    office linked to the document in any way at all - owner, concurring or
    reader (v4). Reading is the permissive question; the process depends
    on people being able to read the documents that govern their work.
    """
    if manual is None:
        return False
    if reads_everything(user):
        return True

    mine = _office_ids(user)
    if not mine:
        return False

    if not by_position():
        return manual.department_id in mine

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

    No admin bypass, matching v3: the submission endpoints refused an
    admin outside the department exactly as they refused anyone else.
    Proposing is an office's act, and an admin is not an office.

    Once scoped by position, **only a concurring office may propose**. A
    reader office may not, and an owning office may not *unless it is also
    listed as concurring* - which is allowed, and common: the VPSD owns
    the Student Development Manual and its own staff draft changes to it.

    The safeguard against an office approving its own proposal is not
    here. It is a configuration rule, checked when the configuration is
    set - see `Manual.owner_proposal_conflict`.
    """
    if manual is None:
        return False

    mine = _office_ids(user)
    if not mine:
        return False

    if not by_position():
        return manual.department_id in mine

    from .models import OfficeLink
    return bool(mine & _linked_offices(manual, (OfficeLink.CONCURRING,)))


def can_propose_to_section(user, section):
    if section is None:
        return False
    return can_propose(user, section.manual)


# ─── Querysets ───────────────────────────────────────────────
#
# These answer "what belongs to my offices", which is the question the
# staff screens ask. No admin bypass: in v3 an admin calling a staff
# endpoint saw their own department's manuals and nothing else, and
# widening that here would change what those screens show.


def reachable_q(offices, prefix=''):
    """The reachability rule as a queryset filter.

    Kept beside `can_reach` on purpose. If the list and the gate ever
    disagree, a screen shows a manual that then refuses to open, and the
    two are far enough apart in the code that nobody would look.

    `prefix` walks in from a section (`manual__`) or a revision
    (`section__manual__`).
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


def _narrow(user, queryset, department_lookup, prefix, mode=None):
    """`mode` forces an answer instead of reading the flag.

    Only the switchover preview passes it, and it exists so that preview
    does not have to flip the real flag to work out what "after" would
    look like. Flipping it - even for a moment, even inside a try/finally
    - would mean a staff member loading a page during the preview got the
    other rule.
    """
    positional = by_position() if mode is None else (mode == 'position')

    # QMS staff read the whole corpus under position-based access. Only
    # then: in the department preview they have no such reach, and saying
    # otherwise would misreport what the switch changes for them.
    if positional and is_qms_staff(user):
        return queryset

    if positional:
        offices = [office for office in current_offices(user)] if (
            user and user.is_authenticated
        ) else []
        if not offices:
            return queryset.none()
        # distinct(): a manual linked to two of the person's offices would
        # otherwise arrive twice, and a duplicated row in a list reads as
        # a duplicated document.
        return queryset.filter(reachable_q(offices, prefix)).distinct()

    department = getattr(user, 'department', None)
    if department is None:
        return queryset.none()
    return queryset.filter(**{f'{department_lookup}__in': [department]})


def manuals_for(user, queryset, mode=None):
    return _narrow(user, queryset, 'department', '', mode)


def sections_for(user, queryset, mode=None):
    return _narrow(user, queryset, 'manual__department', 'manual__', mode)


def revisions_for(user, queryset, mode=None):
    return _narrow(
        user, queryset, 'section__manual__department', 'section__manual__', mode
    )
