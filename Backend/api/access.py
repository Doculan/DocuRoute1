"""Who can reach which manual, and who can propose against it.

Access used to be thirteen separate decisions: nine inline comparisons of
`section.manual.department != request.user.department` scattered through
the views, and four queryset filters. Thirteen places to change at the
switchover, and a missed one looks like nothing at all - the screen still
works, it just shows the wrong person the wrong document.

So the rules are written once, here, and the views ask. **Right now these
still return the v3 answer** - one department per person, one department
per manual - deliberately, so the refactor is behaviour-preserving and
the existing tests are a real check on it. At phase 1c the body of
`offices_for` changes to "offices where the user currently holds a
position", and nothing else has to move.

### Reading and proposing are two questions, not one

The thirteen sites were not thirteen copies of one rule. Four of them
(`list_sections`, `review_section`, `review_delete_section`,
`merge_sections`) let an admin through; the five submission paths
(`upload_revision`, `propose_text_revision`, `propose_merge`, and the two
pre-assessment endpoints) let nobody through - an admin outside the
department was refused like anyone else. Collapsing them into a single
helper would have handed admins the right to propose changes to any
manual in the university, which no v3 screen allowed.

So there are two: `can_reach` for opening a document, which admins pass,
and `can_propose` for changing one, which they do not. That split is also
what 1c needs, where an owning (approving-level) office and a reader
office can both open a manual and neither can propose against it.

### `is_staff` is no longer consulted

It is Django's flag for the `/admin/` site, and those four views were
using it as a cross-department escape hatch while the application's own
`role` field uses `'staff'` to mean the opposite - an ordinary user. An
account made with `createsuperuser` arrives with `is_staff=True` and was
silently bypassing department scoping whatever its role said. Admin reach
now comes from `role == 'admin'`, which is what every other endpoint in
the application already means by admin.
"""


def is_admin(user):
    """Reach across the whole corpus, regardless of office.

    `role`, not `is_staff`. At 1c this becomes `system_role`, once that
    field is authoritative rather than merely populated alongside.
    """
    return bool(
        user and user.is_authenticated and getattr(user, 'role', None) == 'admin'
    )


def offices_for(user):
    """The organisational units this person works in.

    v3 answer: the single department on their account, returned as a list
    so the shape is already what 1c needs. An empty list means "assigned
    to nothing", which is a real state and not an error - the caller
    decides whether that is a 403 or an explanatory screen.
    """
    department = getattr(user, 'department', None)
    return [department] if department is not None else []


def _office_ids(user):
    return {office.pk for office in offices_for(user) if office is not None}


# ─── Reading ─────────────────────────────────────────────────

def can_reach(user, manual):
    """May this person open this manual? Admins may open anything."""
    if manual is None:
        return False
    if is_admin(user):
        return True
    return manual.department_id in _office_ids(user)


def can_reach_section(user, section):
    """The same question asked from a section.

    Most callers hold a section, and `section.manual` is the only route
    between the two - written once so a null section behaves the same way
    everywhere rather than raising in five different views.
    """
    if section is None:
        return False
    return can_reach(user, section.manual)


# ─── Proposing ───────────────────────────────────────────────

def can_propose(user, manual):
    """May this person propose a change to this manual?

    No admin bypass, matching v3: the submission endpoints refused an
    admin outside the department exactly as they refused anyone else.
    Proposing is an office's act, and an admin is not an office.
    """
    if manual is None:
        return False
    return manual.department_id in _office_ids(user)


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

def _narrow(user, queryset, lookup):
    offices = [office for office in offices_for(user) if office is not None]
    if not offices:
        return queryset.none()
    return queryset.filter(**{f'{lookup}__in': offices})


def manuals_for(user, queryset):
    return _narrow(user, queryset, 'department')


def sections_for(user, queryset):
    return _narrow(user, queryset, 'manual__department')


def revisions_for(user, queryset):
    return _narrow(user, queryset, 'section__manual__department')
