import os
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.contrib.auth.models import AbstractUser

class Department(models.Model):
    """The v3 organisation: one flat list, no hierarchy.

    Superseded by `Office`. Kept until nothing reads it (phase 1c), because
    access scoping, three foreign keys and most of the admin screens still
    depend on it. Do not add to it.
    """
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# ─── ORGANISATION (v4) ───────────────────────────────────────
#
# Structure is code; content is data. Nothing here names a university
# office, and these tables ship empty - the system admin enters every
# office, manual link and position through screens.
#
# Nothing in this section is ever deleted. Offices are deactivated or
# merged, people are deactivated, assignments are ended with a date.
# Note in particular that no relationship below cascades *from* the
# organisation: deleting a Department today destroys its manuals, their
# sections and every revision against them, which is exactly what this
# must not repeat.


class Office(models.Model):
    """A unit in the university, at any level.

    One table for every level - a department, a college and the Office of
    the President differ only by where they sit in the tree and whether
    they are an approving level. A separate "higher office" table would
    have to be kept in step with this one, and the hierarchy already says
    everything that distinction says.
    """

    name = models.CharField(max_length=255)
    abbreviation = models.CharField(max_length=32, blank=True)

    # PROTECT, not CASCADE: an office cannot be deleted at all, and if one
    # ever were, taking its children with it would silently remove units
    # that still exist in the university.
    parent = models.ForeignKey(
        'self', on_delete=models.PROTECT,
        null=True, blank=True, related_name='children',
    )

    # Marks VP, President, COO, CAO and the like. These sign; they do not
    # propose or concur. A flag rather than a level number, because the
    # hierarchy has no fixed depth.
    is_approving_level = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)

    # Set when this office was merged into another. The office itself
    # stays, inactive, so past records still resolve.
    merged_into = models.ForeignKey(
        'self', on_delete=models.PROTECT,
        null=True, blank=True, related_name='merged_from',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.abbreviation or self.name

    def ancestors(self):
        """Parents upward, nearest first. Stops rather than looping if the
        data is ever cyclic, so a bad row cannot hang a request."""
        seen, walk, current = set(), [], self.parent
        while current is not None and current.pk not in seen:
            seen.add(current.pk)
            walk.append(current)
            current = current.parent
        return walk

    def clean(self):
        # An office cannot be its own ancestor. This has to be checked in
        # Python: SQL has no way to express "walk the parent chain", and a
        # cycle is created by an edit that looks locally valid - each row
        # has one parent, and only the path is wrong.
        if self.parent_id:
            if self.parent_id == self.pk:
                raise ValidationError({'parent': 'An office cannot be its own parent.'})
            if self.pk and any(a.pk == self.pk for a in self.parent.ancestors()):
                raise ValidationError(
                    {'parent': 'That would put the office inside its own hierarchy.'}
                )
        if self.merged_into_id and self.merged_into_id == self.pk:
            raise ValidationError({'merged_into': 'An office cannot be merged into itself.'})


class AccessMode(models.Model):
    """Whether access is scoped by department (v3) or by position (v4).

    One row. A database row rather than a setting, because flipping it
    changes who can see which documents - that should be done from a
    screen, by a named person, at a recorded time, not by a redeploy
    nobody can point at afterwards.

    It exists because the organisation ships empty. Positions cannot be
    assigned until offices have been entered, so the switch is an
    operation the system admin performs when the data is ready, and the
    system has to be able to say whether it is.

    **Everything scoped reads this**, including `can_propose` - so
    flipping it back restores v3 behaviour completely rather than mostly.
    """

    by_position = models.BooleanField(default=False)
    switched_at = models.DateTimeField(null=True, blank=True)
    switched_by = models.ForeignKey(
        'CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='switchovers',
    )
    # What the admin accepted at the time. Warnings can be passed;
    # blockers cannot, so this records what was knowingly overlooked.
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'access mode'

    def __str__(self):
        return 'by position' if self.by_position else 'by department'

    @classmethod
    def current(cls):
        """The single row, created on first read.

        `get_or_create` rather than a migration that inserts it: a fresh
        clone and an existing database then behave the same, and the
        default is the safe one either way.
        """
        mode, _ = cls.objects.get_or_create(pk=1)
        return mode


class Position(models.Model):
    """A role within an office that the process refers to.

    The process never names a person - it names a position, and asks who
    holds it. IMR and Document Custodian are positions like any other,
    attached to whichever office the system admin chooses, so there is no
    hardcoded QMS office.
    """

    ENCODER = 'encoder'
    HEAD = 'head'
    IMR = 'imr'
    DOCUMENT_CUSTODIAN = 'document_custodian'

    KIND_CHOICES = [
        (ENCODER, 'Encoder'),                      # form: "Requested by"
        (HEAD, 'Head'),                            # form: "Department/Unit Head"
        (IMR, 'Integrated Management Representative'),   # form: section 3
        (DOCUMENT_CUSTODIAN, 'Document Custodian'),      # form: To/For, section 5
    ]

    # The two that make someone QMS staff rather than an ordinary user.
    QMS_KINDS = (IMR, DOCUMENT_CUSTODIAN)

    # Positions only one person may hold at a time. Decided: exactly one
    # current Head per office, several Encoders allowed. IMR and Custodian
    # are left out deliberately - nothing has said whether a university
    # may have two, and guessing would encode a rule nobody agreed.
    SOLE_HOLDER_KINDS = (HEAD,)

    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name='positions',
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['office__name', 'kind']
        constraints = [
            models.UniqueConstraint(
                fields=['office', 'kind'], name='one_position_row_per_office_and_kind',
            ),
        ]

    def __str__(self):
        return f"{self.office} — {self.get_kind_display()}"

    def save(self, *args, **kwargs):
        # `kind` is identity, not a setting. Changing it would silently
        # re-point every assignment ever made against this row - someone
        # recorded as the office's Encoder in 2024 would become its Head -
        # and would leave `PositionAssignment.sole_holder` stale on rows
        # that no longer match it. Make a new Position instead.
        if self.pk:
            previous = Position.objects.filter(pk=self.pk).values_list(
                'kind', flat=True
            ).first()
            if previous is not None and previous != self.kind:
                raise ValidationError({
                    'kind': (
                        "A position's kind cannot be changed. Deactivate "
                        "this one and create the position you need."
                    )
                })
        super().save(*args, **kwargs)


class PositionAssignmentQuerySet(models.QuerySet):
    """Keeps `sole_holder` true to `position.kind` on the bulk paths.

    `save()` recomputes it, but `bulk_create()` and `QuerySet.update()`
    never call `save()`. Left alone, both would write rows with the field
    at its default of False - and False there means the partial unique
    index does not apply, so two current Heads for one office would go in
    without complaint.

    That is the failure mode worth naming: the flag exists only to carry
    the constraint across a join, so a path that leaves it stale does not
    raise anything. It quietly switches off the rule the flag was
    invented for.
    """

    def _sole_holder_for(self, position_id):
        kind = Position.objects.filter(pk=position_id).values_list(
            'kind', flat=True
        ).first()
        return kind in Position.SOLE_HOLDER_KINDS

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        for obj in objs:
            obj.sole_holder = self._sole_holder_for(obj.position_id)
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        # Only a change of `position` can change the answer: the flag
        # depends on that position's kind and on nothing else. Ending or
        # reopening an assignment leaves it correct, and the constraint
        # then does its own work.
        position = kwargs.get('position_id', kwargs.get('position'))
        if position is not None and 'sole_holder' not in kwargs:
            position_id = getattr(position, 'pk', position)
            kwargs['sole_holder'] = self._sole_holder_for(position_id)
        return super().update(**kwargs)


class PositionAssignment(models.Model):
    """Who holds a position, and when they held it.

    Dated rather than a simple pointer, because the question the audit
    trail asks is "who held this on the date of that record" - and a
    pointer can only answer "who holds it now".
    """

    user = models.ForeignKey(
        'CustomUser', on_delete=models.PROTECT, related_name='position_assignments',
    )
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, related_name='assignments',
    )
    starts_on = models.DateField()
    # Null while current. Ending an assignment sets this; nothing is deleted.
    ends_on = models.DateField(null=True, blank=True)

    # Acting or officer-in-charge. The form has one signature block for
    # the Department/Unit Head, and somebody signs it while a post is
    # vacant - so the system has to be able to say the appointment was
    # temporary rather than pretend it was permanent or refuse to record
    # it at all.
    #
    # It does not change what the holder may do. An OIC concurs for the
    # office exactly as a substantive head does; the difference is what
    # the record says afterwards, which is the whole reason for keeping
    # dated assignments.
    is_acting = models.BooleanField(default=False)

    assigned_by = models.ForeignKey(
        'CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assignments_made',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Copied from `position.kind`, and only so the constraint below can
    # see it. A constraint's condition cannot cross a join - Django
    # refuses with "Joined field references are not permitted in this
    # query" - and `kind` lives on Position.
    #
    # Three paths write it and all three maintain it: `save()` recomputes
    # it, and the manager above does the same for `bulk_create()` and
    # `update()`. `Position.save()` refuses a change of `kind` so an
    # existing row's answer cannot move underneath it. A fourth writer
    # would be a hole rather than an inconvenience.
    sole_holder = models.BooleanField(default=False, editable=False)

    objects = PositionAssignmentQuerySet.as_manager()

    class Meta:
        ordering = ['-starts_on', 'position__office__name']
        constraints = [
            # Exactly one current Head per office. `Position` is already
            # unique per (office, kind), so one current assignment to a
            # head position *is* one current head for that office.
            #
            # A real partial index rather than a check in a view, because
            # the rule should hold against the shell, a management
            # command, and two requests arriving at the same moment.
            models.UniqueConstraint(
                fields=['position'],
                condition=Q(ends_on__isnull=True, sole_holder=True),
                name='one_current_holder_of_a_sole_holder_position',
            ),
            models.CheckConstraint(
                condition=Q(ends_on__isnull=True) | Q(ends_on__gte=models.F('starts_on')),
                name='assignment_ends_after_it_starts',
            ),
        ]

    def save(self, *args, **kwargs):
        self.sole_holder = self.position.kind in Position.SOLE_HOLDER_KINDS
        # A partial save would otherwise drop the value just computed, and
        # the constraint would be enforcing a stale flag.
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'sole_holder' not in update_fields:
            kwargs['update_fields'] = list(update_fields) + ['sole_holder']
        super().save(*args, **kwargs)

    def __str__(self):
        acting = " (acting)" if self.is_acting else ""
        return f"{self.user} — {self.position}{acting}"

    @property
    def is_current(self):
        return self.ends_on is None


class ManualSeries(models.Model):
    """A family of documents that share an owner and a set of offices.

    What the application has always called a "manual" is really a
    *document within a manual series*: the blank format's header keeps
    MANUAL TITLE ("Finance and Administration Manual") and DOCUMENT NO.
    ("FAM 6.02") in separate cells, and ten FAM documents in this database
    sit in two different v3 departments. "Department" was naming the
    document family and naming who works on it at the same time; those are
    two axes, and this is the first of them.

    Practically, it is what stops the system admin entering the same owner
    and the same office links nineteen times.
    """

    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=255)

    # The office that signs. Must be an approving level; null while the
    # series has not been given one yet.
    owning_office = models.ForeignKey(
        Office, on_delete=models.PROTECT,
        null=True, blank=True, related_name='owned_series',
    )

    # Provisional, pending the QMS office (workflow plan section 8,
    # question 5). False - the default - runs the approval route from the
    # owner up through every approving level above it.
    approval_stops_at_owner = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name_plural = 'manual series'

    def __str__(self):
        return self.code

    def clean(self):
        if self.owning_office_id and not self.owning_office.is_approving_level:
            raise ValidationError({
                'owning_office': (
                    'A manual is owned by an approving-level office - the one '
                    'that signs. Mark the office as an approving level, or '
                    'choose one that already is.'
                )
            })


class OfficeLink(models.Model):
    """Shared shape for the two office-link tables.

    `ManualSeriesOffice` and `ManualOffice` hold the same pair of values
    for different owners, and later phases read them through one helper.
    Declaring the vocabulary once keeps the two from drifting apart in a
    way that would be invisible until a concurrence list came out wrong.
    """

    CONCURRING = 'concurring'
    READER = 'reader'

    RELATIONSHIP_CHOICES = [
        (CONCURRING, 'Concurring — can propose, must concur'),
        (READER, 'Reader — read only, never blocks'),
    ]

    relationship = models.CharField(max_length=16, choices=RELATIONSHIP_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class ManualSeriesOffice(OfficeLink):
    """The offices a whole series relates to, inherited by its documents."""

    series = models.ForeignKey(
        ManualSeries, on_delete=models.CASCADE, related_name='office_links',
    )
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name='series_links',
    )

    class Meta:
        ordering = ['series__code', 'office__name']
        constraints = [
            models.UniqueConstraint(
                fields=['series', 'office'],
                name='one_relationship_per_series_and_office',
            ),
        ]

    def __str__(self):
        return f"{self.office} — {self.get_relationship_display()} — {self.series}"


class ManualOffice(OfficeLink):
    """How an office relates to one document, when it differs from the series.

    Only read when `Manual.offices_overridden` is set.

    **The owner may appear here too.** Ownership is approval authority and
    is held on `Manual.owning_office`; being listed here is a working
    relationship, and an office can have both - the VPSD owns the Student
    Development Manual and its own staff draft changes to it. The two are
    different facts about the same office, so neither implies the other
    and neither excludes it.

    What that does require is a route that does not end at the proposer.
    See `Manual.owner_proposal_conflict`.
    """

    CONCURRING = OfficeLink.CONCURRING
    READER = OfficeLink.READER

    manual = models.ForeignKey(
        'Manual', on_delete=models.CASCADE, related_name='office_links',
    )
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name='manual_links',
    )
    class Meta:
        ordering = ['manual__title', 'office__name']
        constraints = [
            models.UniqueConstraint(
                fields=['manual', 'office'], name='one_relationship_per_manual_and_office',
            ),
        ]

    def __str__(self):
        return f"{self.office} — {self.get_relationship_display()} — {self.manual}"


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('staff', 'Staff'),
    ]

    # v4. Roles decide which portal; positions decide what can be done
    # inside it. Someone is QMS staff in practice only while holding a
    # current IMR or Custodian assignment - the role routes them, the
    # position authorises them.
    SYSTEM_ADMIN = 'system_admin'
    QMS_STAFF = 'qms_staff'
    USER = 'user'

    SYSTEM_ROLE_CHOICES = [
        (SYSTEM_ADMIN, 'System administrator'),
        (QMS_STAFF, 'QMS staff'),
        (USER, 'User'),
    ]

    # The v3 role. Still what every existing permission check reads, so it
    # stays authoritative until 1c; `system_role` is populated alongside it
    # and takes over at the switchover.
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='staff')

    system_role = models.CharField(
        max_length=20, choices=SYSTEM_ROLE_CHOICES, default=USER,
    )

    # The process prints position titles, never names - but a person still
    # has to be identifiable to the system admin approving them, and
    # `username` is a login, not a name.
    full_name = models.CharField(max_length=255, blank=True)

    is_approved = models.BooleanField(default=False)
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members'
    )

    def __str__(self):
        return self.username


class Manual(models.Model):
    title = models.CharField(max_length=255)
    # PROTECT, not CASCADE. This used to destroy every manual in a
    # department, their sections, and every revision proposed against
    # them - controlled documents and their history - as a side effect of
    # removing one organisation row. The API route that did it is
    # disabled, but the Django admin and the shell reach the same code, so
    # the guarantee belongs on the relationship rather than on one view.
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name='manuals'
    )
    # `blank=True` to match `null=True`. Without it the database accepts a
    # manual with no uploader while `full_clean()` refuses one, so any code
    # that validates before saving fails on rows the ORM created happily -
    # which is exactly what happened the first time the organisation
    # screens tried to validate a document.
    uploaded_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_manuals'
    )
    # v4. The document's series - "FAM 6.02" belongs to "FAM". Null means
    # unassigned, which is where every existing document starts: the
    # organisation ships empty and the system admin links them by hand.
    series = models.ForeignKey(
        ManualSeries, on_delete=models.PROTECT,
        null=True, blank=True, related_name='documents',
    )

    # **Null means inherit from the series.** A document with no series and
    # no owner is what "unassigned" means. PROTECT, because an office is
    # never deleted anyway and a cascade here would destroy controlled
    # documents.
    owning_office = models.ForeignKey(
        Office, on_delete=models.PROTECT,
        null=True, blank=True, related_name='owned_manuals',
    )

    # False: this document uses its series' office links. True: it uses its
    # own, which replace the series' set entirely rather than adding to it.
    #
    # Replace-all rather than per-office exclusion because the concurrence
    # list, the notifications, the frozen participant list and the audit
    # trail all read this, and one branch is something four readers can get
    # right where a set difference is something four readers can get
    # subtly differently. Its cost - a later series-level addition skipping
    # overridden documents - is real, so the series screen names the
    # documents that will not receive the change.
    offices_overridden = models.BooleanField(default=False)

    # Null means inherit from the series. Three states, not two: inherit,
    # stop at the owner, continue upward. Provisional, pending the QMS
    # office (workflow plan section 8, question 5).
    approval_stops_at_owner = models.BooleanField(null=True, blank=True, default=None)

    file = models.FileField(upload_to='mastercopies/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    # v3's own counters. Still incremented, for compatibility, but no longer
    # shown to readers: the official number, version, revision and
    # effectivity date are recorded by the custodian, in `current_status`.
    version = models.IntegerField(default=1)  # major QMS version
    revision = models.IntegerField(default=0)  # minor revision counter
    current_status = models.ForeignKey(
        'DocumentStatus', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )

    def __str__(self):
        return f"{self.title} ({self.department.name})"

    # ── Inheritance ──────────────────────────────────────────
    #
    # Read through these, never off the columns directly. Every later
    # phase asks the same three questions - who owns this, who concurs on
    # it, who signs it - and each one answered separately from raw fields
    # is a chance for two screens to disagree about the same document.

    def clean(self):
        if self.owning_office_id and not self.owning_office.is_approving_level:
            raise ValidationError({
                'owning_office': (
                    'A document is owned by an approving-level office - the '
                    'one that signs. An override is held to the same rule as '
                    'the series it overrides.'
                )
            })

    @property
    def effective_owner(self):
        """The office that signs, whether set here or inherited."""
        if self.owning_office_id:
            return self.owning_office
        return self.series.owning_office if self.series_id else None

    @property
    def owner_is_inherited(self):
        """For the screen: an inherited value and a value that happens to
        match are different things, and the admin has to see which."""
        return self.owning_office_id is None and self.series_id is not None

    @property
    def is_unassigned(self):
        """No series and no owner. All nineteen documents start here."""
        return self.series_id is None and self.owning_office_id is None

    def effective_office_links(self):
        """The (office, relationship) pairs that actually apply.

        The document's own rows when it overrides, the series' otherwise.
        Replace, not merge - see `offices_overridden`.

        Named `effective_` rather than `office_links` because that name is
        already the reverse accessor for `ManualOffice`, and a method with
        the same name is silently shadowed by it - the kind of collision
        that reads as correct and returns a manager.
        """
        if self.offices_overridden:
            return list(
                ManualOffice.objects.filter(manual=self).select_related('office')
            )
        if self.series_id is None:
            return []
        return list(
            ManualSeriesOffice.objects.filter(
                series_id=self.series_id
            ).select_related('office')
        )

    def concurring_offices(self):
        return [
            link.office for link in self.effective_office_links()
            if link.relationship == OfficeLink.CONCURRING
        ]

    def reader_offices(self):
        return [
            link.office for link in self.effective_office_links()
            if link.relationship == OfficeLink.READER
        ]

    @property
    def stops_at_owner(self):
        if self.approval_stops_at_owner is not None:
            return self.approval_stops_at_owner
        return self.series.approval_stops_at_owner if self.series_id else False

    def approval_route(self):
        """The owner, then the approving levels above it, nearest first.

        Empty when the document has no owner yet - which is the honest
        answer, not an error: an unassigned document has no route because
        nobody has said who signs it.
        """
        owner = self.effective_owner
        if owner is None:
            return []
        if self.stops_at_owner:
            return [owner]
        return [owner] + [
            office for office in owner.ancestors() if office.is_approving_level
        ]

    def can_be_proposed_against(self):
        """A document with no concurring office cannot be changed by
        anyone, which is worth flagging on screen rather than discovering
        when someone tries.

        An owning office listed as concurring counts: it can propose, so
        the document is not stranded.
        """
        return bool(self.concurring_offices())

    def owner_proposal_conflict(self):
        """The one configuration the owner-as-proposer rule cannot allow.

        If the owning office may propose, the approval route must continue
        *above* it - otherwise the office that drafted the change is also
        the office that approves it, and the signature means nothing.

        Returns an explanation, or None when the configuration is sound.
        Checked rather than silently corrected: which of the two settings
        is wrong is the admin's call, not the system's.
        """
        owner = self.effective_owner
        if owner is None or owner not in self.concurring_offices():
            return None
        if not self.stops_at_owner:
            # The route carries on to the approving levels above the
            # owner, so somebody else signs. That is the intended shape.
            higher = [o for o in owner.ancestors() if o.is_approving_level]
            if higher:
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


class ManualSection(models.Model):
    TAG_CHOICES = [
    ('POLICY', 'Policy'),
    ('PROCEDURE', 'Procedure'),
    ('RESPONSIBILITY', 'Responsibility'),
    ('WORKING INSTRUCTION', 'Working Instruction'),
    ('PAGE_HEADER', 'Page Header'),
    ('UNTAGGED', 'Untagged'),
]

    manual = models.ForeignKey(
        Manual,
        on_delete=models.CASCADE,
        related_name='sections'
    )
    subtitle = models.CharField(max_length=255)
    content = models.TextField()
    tag = models.CharField(
        max_length=50,
        choices=TAG_CHOICES,
        default='UNTAGGED'
    )
    page_number = models.IntegerField(null=True, blank=True)
    order = models.IntegerField(default=0)
    version = models.IntegerField(default=1)  # ✅ section-level version
    # The recorded status under which this section last changed through a
    # request - what readers see as its revision and effectivity date.
    # Null for a section no request has changed: it shows nothing of its
    # own, and the document header carries the baseline.
    status_changed = models.ForeignKey(
        'DocumentStatus', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sections_changed',
    )

    # Hierarchy (parent/child sections)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )

    # Review workflow
    is_reviewed = models.BooleanField(default=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        'CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_sections'
    )

    def __str__(self):
        return f"{self.subtitle} [{self.tag}] — {self.manual.title}"


class SectionHistory(models.Model):
    """Snapshot of a section before each edit.

    Every version was already recorded, but no version could say *why* it
    existed: an approved revision and an admin typing into the edit box
    produced identical rows. For a controlled document that is the part
    that matters - clause 7.5.3 is about knowing what changed, who changed
    it and on what authority, and the first two were the only ones here.
    """

    # How this version came about. Deliberately not inferred from whether a
    # revision happens to exist: a revision can be deleted, and the history
    # has to stay true afterwards.
    SOURCE_CHOICES = [
        ('revision', 'Approved revision'),
        ('proposal', 'Change request made effective'),
        ('direct', 'Direct edit by an admin'),
        ('merge', 'Merged with another section'),
        ('extraction', 'Re-extracted from the master copy'),
        ('unknown', 'Recorded before edits were attributed'),
    ]

    section = models.ForeignKey(
        ManualSection,
        on_delete=models.CASCADE,
        related_name='history'
    )
    version = models.IntegerField()
    subtitle = models.CharField(max_length=255)
    content = models.TextField()
    tag = models.CharField(max_length=50)
    edited_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    edited_at = models.DateTimeField(auto_now_add=True)

    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        # Rows written before this field existed genuinely are unknown.
        # Defaulting them to 'direct' would be a guess recorded as a fact,
        # which is worse than an honest gap in an audit trail.
        default='unknown',
    )
    change_reason = models.TextField(
        blank=True,
        help_text="Why this change was made. Carried over from the "
                  "submitter's reason on an approved revision, typed by "
                  "the admin on a direct edit.",
    )
    # Set when this version came from a revision, so the history can point
    # back at the submission and its assessment. SET_NULL rather than
    # CASCADE: deleting a revision must not delete the record that the
    # document changed.
    revision = models.ForeignKey(
        'ManualRevision',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='section_versions',
    )
    # The v4 equivalent: the change request this version came from.
    proposal = models.ForeignKey(
        'Proposal',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='section_versions',
    )

    class Meta:
        ordering = ['version']

    def __str__(self):
        return f"{self.section.subtitle} — v{self.version}"


class ManualRevision(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    section = models.ForeignKey(
        ManualSection,
        on_delete=models.CASCADE,
        related_name='revisions'
    )
    submitted_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='revisions'
    )
    uploaded_file = models.FileField(upload_to='revisions/', blank=True, null=True)
    proposed_content = models.TextField(blank=True)
    merge_section_ids = models.JSONField(blank=True, null=True)  # List of section IDs to merge into this one
    merge_type = models.CharField(max_length=20, blank=True)  # 'merge' for merge operations
    diff_text = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_revisions'
    )
    reviewer_notes = models.TextField(blank=True)

    # Why the submitter is making this change. ISO 9001 clause 6.3 expects
    # changes to be planned, so Layer 1 treats an empty reason as a hard fail.
    change_reason = models.TextField(blank=True)

    # Advisory output of the revision-assessment pipeline. Persisted so an
    # admin's view of the assessment matches what the model actually said at
    # submission time, rather than being recomputed on every page load.
    ai_verdict = models.CharField(max_length=32, blank=True)
    ai_issues = models.JSONField(default=list, blank=True)
    ai_explanation = models.TextField(blank=True)
    ai_trace = models.JSONField(default=dict, blank=True)

    AI_SOURCE_CHOICES = [
        # The submitter ran the check before submitting and this is what they
        # read. The only way a new revision gets an assessment.
        ('staff_precheck', 'Checked by the submitter before submitting'),
        # Produced by a reviewer pressing an assess button, which is how it
        # worked before the check moved to the staff side. Kept so old rows
        # are not passed off as something the submitter saw.
        ('admin_legacy', 'Assessed by the reviewer under the previous workflow'),
        ('none', 'Not assessed'),
    ]
    ai_source = models.CharField(
        max_length=20, choices=AI_SOURCE_CHOICES, default='none'
    )

    # The same findings addressed to the submitter. Stored rather than
    # re-rendered so a reviewer can see what the submitter was actually told
    # before choosing to submit anyway.
    ai_explanation_staff = models.TextField(blank=True)
    ai_confidence = models.FloatField(null=True, blank=True)
    ai_change_type = models.CharField(max_length=40, blank=True)
    ai_hard_fails = models.JSONField(default=list, blank=True)
    ai_advisories = models.JSONField(default=list, blank=True)

    # When the assessment was made, against which weights, and of exactly what.
    # The reviewer needs all three: a long gap between check and submission is
    # worth seeing, and the section may have moved since.
    ai_assessed_at = models.DateTimeField(null=True, blank=True)
    ai_model_fingerprint = models.CharField(max_length=64, blank=True)
    ai_content_hash = models.CharField(max_length=64, blank=True)
    ai_section_content_hash = models.CharField(max_length=64, blank=True)

    # When the submitter last opened the reviewer's feedback. Drives the badge
    # on My Revisions: feedback exists and is newer than the last time they
    # looked. Null means they have never opened it.
    feedback_seen_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Revision by {self.submitted_by} on {self.section.subtitle}"


class DemoRecord(models.Model):
    """One row the demo seeder created, or one field it changed.

    The seeder has to be exactly reversible, and "delete everything that
    looks like demo data" is not exact - a name can be typed by hand and a
    real office can share a name with a fictional one. So it records what
    it did, object by object, and `--clear` undoes precisely that.

    A marker table rather than an `is_demo` flag on Office, CustomUser and
    the rest: a demo convenience has no business adding a column to the
    models that hold the university's real organisation, where it would
    then have to be considered by every query for ever.
    """

    CREATED = 'created'
    CHANGED = 'changed'

    KIND_CHOICES = [
        (CREATED, 'Created by the seeder'),
        (CHANGED, 'Existing row the seeder modified'),
    ]

    label = models.CharField(max_length=64)          # "api.Office"
    object_id = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    # For CHANGED rows: the field values as they were, so clearing puts
    # them back instead of guessing at a default.
    previous = models.JSONField(default=dict, blank=True)
    # Creation order, so clearing can walk backwards - everything in the
    # organisation is PROTECT, so the order is not optional.
    sequence = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sequence']

    def __str__(self):
        return f"{self.kind} {self.label}#{self.object_id}"


# ─── PROPOSALS (v4 phase 2) ──────────────────────────────────
#
# The university's actual process, up to agreement. An office drafts a
# proposal for a **whole document**, each changed section carries its own
# AI check, every concurring office agrees or sends it back, and full
# agreement locks the content.
#
# `ManualRevision` above is the v3 shape: one section, one submitter, one
# reviewer, one decision. It stays and keeps working while the access
# switch is off. Nothing here migrates from it - the development data was
# cleared, so there is nothing to carry across.
#
# **Until P4, a locked proposal does not change the manual.** Locking
# freezes the text that was agreed; applying it is the custodian's act.


class Proposal(models.Model):
    """One office's proposed change to one document."""

    DRAFT = 'draft'
    CONCURRENCE = 'concurrence'
    LOCKED = 'locked'
    AWAITING_SIGNATURE = 'awaiting_signature'
    READY_FOR_IMR = 'ready_for_imr'
    DENIED = 'denied'
    AWAITING_APPROVAL = 'awaiting_approval'
    WITH_CUSTODIAN = 'with_custodian'
    PACKAGE_RETURNED = 'package_returned'
    EFFECTIVE = 'effective'
    WITHDRAWN = 'withdrawn'

    STATUS_CHOICES = [
        (DRAFT, 'Draft'),
        (CONCURRENCE, 'Out for concurrence'),
        (LOCKED, 'Locked'),
        (AWAITING_SIGNATURE, 'Awaiting signature'),
        (READY_FOR_IMR, 'Ready for the IMR'),
        (DENIED, 'Denied by the IMR'),
        (AWAITING_APPROVAL, 'Awaiting the approving authority'),
        (WITH_CUSTODIAN, 'With the Document Custodian'),
        (PACKAGE_RETURNED, 'Returned for package defects'),
        (EFFECTIVE, 'Effective'),
        (WITHDRAWN, 'Withdrawn'),
    ]

    # `LOCKED` means the content is frozen. `AWAITING_SIGNATURE` means
    # frozen **and** the documents to be signed exist. They are separate
    # because a lock that froze the text but produced nothing to sign is a
    # dead end, and the difference has to be visible rather than inferred
    # from whether any rows happen to be in `attachments`.
    #
    # From 3b the two happen in one transaction, so nothing new rests in
    # `LOCKED`; rows locked before then legitimately do.
    FROZEN_STATUSES = (
        LOCKED, AWAITING_SIGNATURE, READY_FOR_IMR,
        AWAITING_APPROVAL, WITH_CUSTODIAN, PACKAGE_RETURNED,
    )

    # Finished, one way or another. Nothing further happens to these.
    CLOSED_STATUSES = (DENIED, EFFECTIVE, WITHDRAWN)

    # Signed copies may be uploaded or replaced only here: after the
    # documents exist, and before the IMR decides. Once P4 adds the IMR's
    # decision the request moves past these, and replacing a scan the IMR
    # has already judged is refused - reopening it is the IMR's act.
    SCAN_STATUSES = (AWAITING_SIGNATURE, READY_FOR_IMR)

    # Still open for work: drafting or concurring. What can be edited,
    # returned and withdrawn.
    OPEN_STATUSES = (DRAFT, CONCURRENCE)

    # Holding its sections: everything not yet closed. A locked request is
    # still on its way to being made effective, and until then nobody else
    # may start changing the same text - or two agreed changes would meet
    # at the custodian's desk, and one would silently overwrite the other.
    # Found in the Phase 4 survey: the hold used to end at the lock.
    HOLDING_STATUSES = OPEN_STATUSES + FROZEN_STATUSES

    manual = models.ForeignKey(
        Manual, on_delete=models.PROTECT, related_name='proposals',
    )
    # The office acting, not the person. Someone holding positions in two
    # offices chooses which one they are drafting for, and the record has
    # to say which - the DCR is signed by an office.
    initiating_office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name='proposals_initiated',
    )
    status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=DRAFT,
    )

    created_by = models.ForeignKey(
        'CustomUser', on_delete=models.PROTECT, related_name='proposals_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    locked_at = models.DateTimeField(null=True, blank=True)

    # The number the paper form carries, allocated when the content
    # freezes - there is no request to number before that. Blank, not
    # null, so the partial unique index below has one thing to exclude
    # rather than two.
    dcr_number = models.CharField(max_length=32, blank=True)

    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        'CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='proposals_withdrawn',
    )
    withdrawn_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['dcr_number'], condition=~Q(dcr_number=''),
                name='one_proposal_per_dcr_number',
            ),
            # One open proposal per office per document, in the database
            # rather than only in the view. The view's check reads, then
            # inserts, and two requests arriving together both passed it:
            # one click made two drafts. The statuses are OPEN_STATUSES,
            # spelled out because a nested class cannot see the outer one.
            models.UniqueConstraint(
                fields=['manual', 'initiating_office'],
                condition=Q(status__in=['draft', 'concurrence']),
                name='one_open_proposal_per_office_and_document',
            ),
        ]

    def __str__(self):
        return f"{self.manual.title} — {self.get_status_display()}"

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def holds_sections(self):
        return self.status in self.HOLDING_STATUSES

    def current_version(self):
        """The version being worked on or decided.

        Derived from the rows rather than stored as a pointer: a stored
        "current" that disagreed with the highest number would be a bug
        nobody could see, and there is no cheaper question than max().
        """
        return self.versions.order_by('-number').first()

    def refresh_open_changes(self):
        """Keep `SectionChange.is_open` true to this proposal's state.

        A change is open - holds its section - when its proposal is not yet
        closed **and** it belongs to the current version. Not only while
        drafting: a locked request holds its sections until it is made
        effective, denied or withdrawn. Superseded versions are history: the office
        agreed to text that no longer exists, and their sections are free
        for somebody else.

        Called whenever the status changes or a version is added. It is a
        denormalisation, so every path that could invalidate it has to say
        so - a stale True blocks a section nobody is working on, and a
        stale False lets two proposals edit the same section at once.
        """
        current = self.current_version()
        open_now = self.holds_sections and current is not None

        SectionChange.objects.filter(version__proposal=self).exclude(
            version=current
        ).update(is_open=False)
        if current is not None:
            SectionChange.objects.filter(version=current).update(
                is_open=open_now
            )


class ProposalVersion(models.Model):
    """One draft of the whole proposal.

    Every redraft is a new version, because an office concurred with
    particular text and that text no longer exists.
    """

    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name='versions',
    )
    number = models.PositiveIntegerField()

    # The DCR's single "reason for the change" field. Required to submit,
    # and checked by the existing clause 6.3 tiers.
    overall_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    submitted_by = models.ForeignKey(
        'CustomUser', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='proposal_versions_submitted',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['proposal', 'number']
        constraints = [
            models.UniqueConstraint(
                fields=['proposal', 'number'], name='one_row_per_proposal_version',
            ),
        ]

    def __str__(self):
        return f"{self.proposal.manual.title} v{self.number}"


class SectionChangeQuerySet(models.QuerySet):
    """Keeps `is_open` true on the paths that skip `save()`.

    Same shape as `PositionAssignmentQuerySet`, and for the same reason: a
    partial unique index cannot cross a join to `Proposal.status`, so the
    fact is copied onto the row - and a copied fact that some writer
    forgets to maintain does not raise, it silently switches the
    constraint off.

    Here that would mean two offices editing the same section at once and
    neither knowing.
    """

    def _open_for(self, version_id):
        version = ProposalVersion.objects.select_related('proposal').filter(
            pk=version_id
        ).first()
        if version is None:
            return False
        proposal = version.proposal
        current = proposal.current_version()
        return proposal.holds_sections and current is not None and current.pk == version.pk

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        for obj in objs:
            obj.is_open = self._open_for(obj.version_id)
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        # Moving a change to a different version can change the answer;
        # `is_open` passed explicitly is the recompute itself, and is left
        # alone so `refresh_open_changes` can do its job.
        version = kwargs.get('version_id', kwargs.get('version'))
        if version is not None and 'is_open' not in kwargs:
            kwargs['is_open'] = self._open_for(getattr(version, 'pk', version))
        return super().update(**kwargs)


class SectionChange(models.Model):
    """One changed section inside one version of a proposal.

    **Existing sections only in P2.** There is no `action` field, because
    adding and deleting sections is later work and a field nothing sets
    would be an invitation to half-implement it.
    """

    version = models.ForeignKey(
        ProposalVersion, on_delete=models.CASCADE, related_name='changes',
    )
    section = models.ForeignKey(
        ManualSection, on_delete=models.PROTECT, related_name='proposed_changes',
    )

    # The section's text when this version was drafted, stored rather than
    # read live: the diff a reviewer sees has to be the diff the drafter
    # saw, and the section can move underneath both of them.
    old_text = models.TextField(blank=True)
    new_text = models.TextField(blank=True)
    note = models.TextField(blank=True)

    # The check for *this* section. One assessment per changed section,
    # made once and displayed thereafter - never recomputed.
    assessment = models.OneToOneField(
        'RevisionPreAssessment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='section_change',
    )
    # Bound to the text that was checked. Editing the section clears the
    # check by leaving this behind.
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    section_content_hash = models.CharField(max_length=64, blank=True)

    # Copied from the proposal so the constraint below can see it. See
    # `SectionChangeQuerySet`.
    is_open = models.BooleanField(default=False, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SectionChangeQuerySet.as_manager()

    class Meta:
        ordering = ['version', 'section__order']
        constraints = [
            models.UniqueConstraint(
                fields=['version', 'section'],
                name='one_change_per_section_per_version',
            ),
            # One open proposal per section. A real index rather than a
            # check in a view, because two people submitting at the same
            # moment is exactly when a view-level check fails.
            models.UniqueConstraint(
                fields=['section'],
                condition=Q(is_open=True),
                name='one_open_change_per_section',
            ),
        ]

    def __str__(self):
        return f"{self.section.subtitle} @ {self.version}"

    def save(self, *args, **kwargs):
        self.is_open = SectionChange.objects.all()._open_for(self.version_id)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'is_open' not in update_fields:
            kwargs['update_fields'] = list(update_fields) + ['is_open']
        super().save(*args, **kwargs)

    @property
    def has_changed(self):
        return (self.new_text or '').strip() != (self.old_text or '').strip()

    def text_hash(self):
        """A fingerprint of the two texts this change is about.

        Over the section's text and the proposed text only - **not** the
        overall reason. Editing one box must clear only that box's check,
        and folding the shared reason in would mean changing it cleared
        every section at once. The reason is still checked, at submission,
        by the existing clause 6.3 tiers.
        """
        from api import pre_assessment
        return pre_assessment.content_hash(
            self.section_id, self.old_text or '', self.new_text or '', '',
        )

    @property
    def check_is_current(self):
        """Is the stored check still about this text?

        Compares a fingerprint of the text **as it is now** against the
        one taken when the check ran. Comparing two stored values would
        compare the check with itself, which is always true and says
        nothing - the first version of this did exactly that and reported
        every edited section as checked.
        """
        return bool(
            self.assessment_id and self.content_hash
            and self.content_hash == self.text_hash()
        )


class ProposalParticipant(models.Model):
    """An office that must agree, or that signs. **Frozen at submission.**

    A reorganisation mid-request must never change who has to agree to it,
    so the list is written once when the proposal is submitted and read
    afterwards - including `office_name_at_time`, because an office that
    is renamed later must still read correctly on an old request.
    """

    CONCURRING = 'concurring'
    APPROVING = 'approving'

    ROLE_CHOICES = [
        (CONCURRING, 'Must concur'),
        (APPROVING, 'Signs'),
    ]

    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name='participants',
    )
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name='proposal_participations',
    )
    office_name_at_time = models.CharField(max_length=255)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    # Position in the approval route; null for concurring offices, which
    # have no order among themselves.
    route_order = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['proposal', 'role', 'route_order', 'office_name_at_time']
        constraints = [
            models.UniqueConstraint(
                fields=['proposal', 'office', 'role'],
                name='one_participation_per_office_and_role',
            ),
        ]

    def __str__(self):
        return f"{self.office_name_at_time} — {self.get_role_display()}"


class Concurrence(models.Model):
    """One office's decision on one version.

    Against a **version**, not the proposal: an office agreed to
    particular text, so a redraft resets every decision rather than
    carrying agreement forward to something nobody read.
    """

    CONCUR = 'concur'
    RETURN = 'return'

    DECISION_CHOICES = [
        (CONCUR, 'Concurs'),
        (RETURN, 'Returned with feedback'),
    ]

    version = models.ForeignKey(
        ProposalVersion, on_delete=models.CASCADE, related_name='concurrences',
    )
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name='concurrences',
    )
    decision = models.CharField(max_length=16, choices=DECISION_CHOICES)
    feedback = models.TextField(blank=True)
    # Feedback may point at one section without being about only that one.
    section = models.ForeignKey(
        ManualSection, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='concurrence_feedback',
    )

    # Both the person and the position they held, because the position is
    # what the process refers to and the person is who to ask.
    recorded_by = models.ForeignKey(
        'CustomUser', on_delete=models.PROTECT, related_name='concurrences_recorded',
    )
    recorded_by_position = models.ForeignKey(
        Position, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='concurrences_recorded',
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['version', 'office__name']
        constraints = [
            models.UniqueConstraint(
                fields=['version', 'office'],
                name='one_decision_per_office_per_version',
            ),
        ]

    def __str__(self):
        return f"{self.office} — {self.get_decision_display()}"


class AuditEvent(models.Model):
    """Every transition, with who did it and on whose behalf.

    Append-only by intent: nothing in the application updates or deletes
    one. It is the answer to "what happened to this request", and a record
    that can be edited answers nothing.
    """

    CREATED = 'created'
    SUBMITTED = 'submitted'
    CONCURRED = 'concurred'
    RETURNED = 'returned'
    REDRAFTED = 'redrafted'
    LOCKED = 'locked'
    DOCUMENTS_GENERATED = 'documents_generated'
    SCAN_UPLOADED = 'scan_uploaded'
    SCAN_REPLACED = 'scan_replaced'
    PACKAGE_COMPLETE = 'package_complete'
    IMR_ACCEPTED = 'imr_accepted'
    IMR_DENIED = 'imr_denied'
    APPROVAL_UPLOADED = 'approval_uploaded'
    PACKAGE_RETURNED = 'package_returned'
    MADE_EFFECTIVE = 'made_effective'
    WITHDRAWN = 'withdrawn'

    EVENT_CHOICES = [
        (CREATED, 'Created'),
        (SUBMITTED, 'Submitted for concurrence'),
        (CONCURRED, 'Concurred'),
        (RETURNED, 'Returned with feedback'),
        (REDRAFTED, 'Redrafted'),
        (LOCKED, 'Locked'),
        (DOCUMENTS_GENERATED, 'Documents generated'),
        (SCAN_UPLOADED, 'Signed copy uploaded'),
        (SCAN_REPLACED, 'Signed copy replaced'),
        (PACKAGE_COMPLETE, 'Signed copies complete'),
        (IMR_ACCEPTED, 'Accepted by the IMR'),
        (IMR_DENIED, 'Denied by the IMR'),
        (APPROVAL_UPLOADED, 'Approving authority signed'),
        (PACKAGE_RETURNED, 'Returned for package defects'),
        (MADE_EFFECTIVE, 'Made effective'),
        (WITHDRAWN, 'Withdrawn'),
    ]

    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name='events',
    )
    version = models.ForeignKey(
        ProposalVersion, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='events',
    )
    event = models.CharField(max_length=32, choices=EVENT_CHOICES)

    actor = models.ForeignKey(
        'CustomUser', on_delete=models.PROTECT, related_name='proposal_events',
    )
    position = models.ForeignKey(
        Position, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='proposal_events',
    )
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name='proposal_events',
    )
    office_name_at_time = models.CharField(max_length=255, blank=True)

    detail = models.TextField(blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['proposal', 'at']

    def __str__(self):
        return f"{self.get_event_display()} — {self.office_name_at_time}"


class QmsDecision(models.Model):
    """What the IMR or the Document Custodian decided about a request.

    Append-only, like the audit trail: a decision that could be edited
    afterwards would not be a record of one. The person and the position
    they held are both kept - the position as it read at the time, because
    a later reassignment must not change who is recorded as deciding.
    """

    IMR = 'imr'
    CUSTODIAN = 'custodian'
    STAGE_CHOICES = [(IMR, 'IMR'), (CUSTODIAN, 'Document Custodian')]

    ACCEPT = 'accept'
    DENY = 'deny'
    RETURN = 'return'
    EFFECTIVE = 'effective'
    OUTCOME_CHOICES = [
        (ACCEPT, 'Accepted'),
        (DENY, 'Denied'),
        (RETURN, 'Returned for package defects'),
        (EFFECTIVE, 'Made effective'),
    ]

    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name='qms_decisions',
    )
    version = models.ForeignKey(
        ProposalVersion, on_delete=models.CASCADE, related_name='qms_decisions',
    )
    stage = models.CharField(max_length=16, choices=STAGE_CHOICES)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES)
    comments = models.TextField(blank=True)
    # For a custodian's return: which signed copies are defective, so that
    # only those can be replaced.
    returned_kinds = models.JSONField(default=list, blank=True)

    decided_by = models.ForeignKey(
        'CustomUser', on_delete=models.PROTECT, related_name='qms_decisions',
    )
    decided_as = models.CharField(max_length=255)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['proposal', 'decided_at']

    def __str__(self):
        return f"{self.get_stage_display()}: {self.get_outcome_display()}"


class DocumentStatus(models.Model):
    """A document's official status: DCR section 5, or a recorded baseline.

    The manuals already carry real revisions on paper, so the custodian
    may record where a document stands before any request touches it - a
    baseline, with no request behind it. After that, each request made
    effective adds a row. `Manual.current_status` points at the latest;
    the rows are the history.

    Version and revision are text, as the paper form writes them ("01",
    "Rev. 2"). Where both old and new are plain numbers the system refuses
    to go backwards; anything else it records as written.
    """

    manual = models.ForeignKey(
        Manual, on_delete=models.PROTECT, related_name='statuses',
    )
    # Null for a baseline.
    proposal = models.OneToOneField(
        Proposal, on_delete=models.PROTECT,
        null=True, blank=True, related_name='document_status',
    )
    document_number = models.CharField(max_length=64)
    version = models.CharField(max_length=32)
    revision = models.CharField(max_length=32)
    effective_on = models.DateField()
    # Section 5's "Date updated in the IDS". Not asked of a baseline.
    updated_in_ids_on = models.DateField(null=True, blank=True)

    recorded_by = models.ForeignKey(
        'CustomUser', on_delete=models.PROTECT, related_name='document_statuses',
    )
    recorded_as = models.CharField(max_length=255)
    recorded_at = models.DateTimeField(auto_now_add=True)

    # A baseline corrected by the custodian - allowed only until a request
    # has been made effective on the document. The mistaken row is kept,
    # pointing at the one that corrected it, never overwritten: what
    # readers were shown, and for how long, stays on record.
    superseded_by = models.OneToOneField(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='supersedes',
    )
    superseded_at = models.DateTimeField(null=True, blank=True)
    # Why the correction was made, on the row that makes it.
    correction_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['manual', 'recorded_at']
        verbose_name_plural = 'document statuses'

    @property
    def is_baseline(self):
        return self.proposal_id is None

    def __str__(self):
        return f"{self.document_number} v{self.version} rev {self.revision}"


def attachment_path(instance, filename):
    """Where an attachment's bytes land.

    The name on disk is generated, never the name the browser sent. An
    uploaded filename is attacker-controlled: it can traverse directories,
    collide with another upload, or - as `Manual.file` once did - be
    written back into the very folder something else is scanning. The name
    the person chose is kept in `original_filename`, where it is data
    rather than a path.
    """
    suffix = os.path.splitext(filename)[1].lower()[:10]
    return f"proposals/{instance.proposal_id}/{uuid.uuid4().hex}{suffix}"


class Attachment(models.Model):
    """A document belonging to a request: generated, or a signed scan.

    **The system stores and records; it does not verify.** It cannot tell
    whether a scan shows the right document, whether the signature is
    genuine, or whether the person who signed held the position. The QMS
    office checks that against the physical copies. So every field here is
    a fact about the upload - who, when, what the file was called, what
    type it claimed to be - and none is a judgement about its contents.

    **Replacement supersedes; it never overwrites.** A scan is evidence
    that a piece of paper was signed. Quietly replacing the bytes would
    leave the record saying something different from what it said
    yesterday, with nothing to show that it had changed.
    """

    DCR_GENERATED = 'dcr_generated'
    PAGES_GENERATED = 'pages_generated'
    CONCURRENCE_RECORD = 'concurrence_record'
    SIGNED_DCR = 'signed_dcr'
    SIGNED_PAGES = 'signed_pages'
    APPROVED_DCR = 'approved_dcr'

    KIND_CHOICES = [
        (DCR_GENERATED, 'Document Change Request (generated)'),
        (PAGES_GENERATED, 'Draft copy of the document (generated)'),
        (CONCURRENCE_RECORD, 'Record of concurrence (generated)'),
        (SIGNED_DCR, 'Signed Document Change Request'),
        (SIGNED_PAGES, 'Signed draft copy'),
        (APPROVED_DCR, 'DCR signed by the approving authority'),
    ]

    # Made by the system, from frozen content. Never replaced: the content
    # cannot change, so a second generation could only either repeat
    # itself or disagree with the paper already in somebody's hand.
    GENERATED_KINDS = (DCR_GENERATED, PAGES_GENERATED, CONCURRENCE_RECORD)
    # Came in from a scanner. These are the ones that get replaced. The
    # approving authority's signed DCR arrives later than the others -
    # after the IMR accepts - but is a signed copy like them.
    SCAN_KINDS = (SIGNED_DCR, SIGNED_PAGES, APPROVED_DCR)

    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name='attachments',
    )
    # Against the version, like a concurrence: the documents were made
    # from particular text, and a redraft makes them wrong.
    version = models.ForeignKey(
        ProposalVersion, on_delete=models.CASCADE, related_name='attachments',
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)

    # Which section this one is about, for the per-section kinds. Kept as
    # a foreign key for reading and as `slot` for the index below, because
    # SQLite counts NULLs as distinct and a unique index over a nullable
    # column would let the same section through twice.
    section = models.ForeignKey(
        ManualSection, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='attachments',
    )
    slot = models.CharField(max_length=32, blank=True)

    file = models.FileField(upload_to=attachment_path)
    # What the browser called it, what it claimed to be, how big it was.
    # Recorded, not trusted.
    original_filename = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        'CustomUser', on_delete=models.PROTECT, related_name='attachments_created',
    )
    # The position the uploader held, as it read at the time - "Accounting
    # Office — Encoder". Written once: someone who is later made Head must
    # not have their earlier upload start saying so. Blank for generated
    # documents, which nobody uploaded.
    created_as = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    supersedes = models.ForeignKey(
        'self', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='superseded_by',
    )
    superseded_at = models.DateTimeField(null=True, blank=True)
    replacement_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['proposal', 'kind', 'created_at']
        constraints = [
            # One live file per slot. The superseded ones stay, so the
            # condition is what makes the index mean "current".
            models.UniqueConstraint(
                fields=['version', 'kind', 'slot'],
                condition=Q(superseded_at__isnull=True),
                name='one_current_attachment_per_slot',
            ),
            # A replaced file has exactly one replacement. Two rows both
            # claiming to supersede it would make the chain unreadable.
            models.UniqueConstraint(
                fields=['supersedes'],
                condition=Q(supersedes__isnull=False),
                name='one_replacement_per_attachment',
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.proposal_id}"

    @property
    def is_current(self):
        return self.superseded_at is None

    @property
    def is_generated(self):
        return self.kind in self.GENERATED_KINDS


class Announcement(models.Model):
    """Something the admin wants staff to see.

    One model for two widgets, because they are the same thing at different
    distances: an item with a date is upcoming, an item without one is an
    announcement. Splitting them would mean two models, two endpoints and a
    decision at the point of writing about which kind a message is - when
    the only real difference is whether it happens on a day.

    A null department means everyone; otherwise only that department sees it.
    """

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    # Dated items appear under Upcoming and drop off after their day.
    # Undated items are the banner.
    date = models.DateField(null=True, blank=True)
    # PROTECT rather than SET_NULL, which would be actively wrong here:
    # null does not mean "no department", it means **show this to
    # everyone**. Clearing the field on a departmental notice would
    # silently broadcast it to the whole university, which is worse than
    # either keeping it or losing it.
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, null=True, blank=True,
        related_name='announcements',
        help_text="Leave empty to show this to every department.",
    )

    # v4. Read instead of `department` once access is scoped by position,
    # so notices and access switch together rather than leaving the system
    # scoping documents by office and announcements by department.
    #
    # Null means everyone, exactly as the department field does - and for
    # the same reason it is PROTECT rather than SET_NULL, since clearing
    # it would silently broadcast a targeted notice to the whole
    # university.
    office = models.ForeignKey(
        'Office', on_delete=models.PROTECT, null=True, blank=True,
        related_name='announcements',
        help_text="Leave empty to show this to every office.",
    )
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='announcements',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(
        default=True,
        help_text="Uncheck to hide without deleting.",
    )

    class Meta:
        ordering = ['date', '-created_at']

    def __str__(self):
        when = self.date.isoformat() if self.date else 'announcement'
        return f"{self.title} ({when})"


class AnnouncementDismissal(models.Model):
    """One person has closed one banner.

    Per user and per announcement rather than a single "dismissed" flag, so
    a new announcement reappears for someone who dismissed the last one.
    """

    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name='dismissals'
    )
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='dismissed_announcements'
    )
    dismissed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('announcement', 'user')


class RecentlyOpened(models.Model):
    """What this person last looked at, for getting back to it.

    Server-side on purpose: browser storage would lose the list on a
    different device, which is exactly when someone most wants to pick up
    where they left off. Capped per user - see views._record_recently_opened.
    """

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='recently_opened'
    )
    manual = models.ForeignKey(
        Manual, on_delete=models.CASCADE, related_name='recently_opened'
    )
    # Null when a whole manual was opened rather than one section.
    section = models.ForeignKey(
        ManualSection, on_delete=models.CASCADE, null=True, blank=True,
        related_name='recently_opened',
    )
    opened_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-opened_at']
        # Re-opening something moves it up the list rather than adding a
        # second row, so the list stays a set of places, not a log.
        unique_together = ('user', 'manual', 'section')

    def __str__(self):
        return f"{self.user} -> {self.section or self.manual}"


class RevisionPreAssessment(models.Model):
    """One assessment of content that has not been submitted yet.

    The submitter presses "Check with AI", the result is written here, and the
    submitter is handed only this row's id. At submit the server recomputes the
    content hash and compares: matching means the reviewer will read exactly
    what the submitter read, and that guarantee is the whole point of the
    table. Nothing about the result is ever accepted from the client.

    Rows are working state, not a record - a submitter who checks and closes
    the tab leaves one behind - so unconsumed rows are swept after
    ``pre_assessment.RETENTION_DAYS``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section = models.ForeignKey(
        ManualSection, on_delete=models.CASCADE, related_name='pre_assessments'
    )
    submitted_by = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='pre_assessments'
    )

    # What was assessed. change_reason is part of the hash because Layer 1
    # judges it under clause 6.3, so changing it means the revision has
    # genuinely not been assessed.
    content_hash = models.CharField(max_length=64, db_index=True)
    section_content_hash = models.CharField(max_length=64)
    proposed_content = models.TextField(blank=True)
    change_reason = models.TextField(blank=True)

    verdict = models.CharField(max_length=32, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    change_type = models.CharField(max_length=40, blank=True)
    issues = models.JSONField(default=list, blank=True)
    hard_fails = models.JSONField(default=list, blank=True)
    advisories = models.JSONField(default=list, blank=True)
    explanation_reviewer = models.TextField(blank=True)
    explanation_staff = models.TextField(blank=True)
    trace = models.JSONField(default=dict, blank=True)

    model_fingerprint = models.CharField(max_length=64, blank=True)
    pipeline_version = models.CharField(max_length=8, blank=True)
    assessed_at = models.DateTimeField(auto_now_add=True)
    # Which sections retrieval pulled in when this check ran.
    #
    # Recorded because the coordinated-change advisory has to know whether
    # a `contradicts_manual` concern points at a section that is *also*
    # being changed in the same proposal - and the pipeline's trace does
    # not keep it. Written by the view, which already has the retrieved
    # sections in hand, so nothing under `ml/` changes and Layer 2
    # receives exactly what it received before.
    retrieved_section_ids = models.JSONField(default=list, blank=True)

    consumed_by = models.OneToOneField(
        ManualRevision, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pre_assessment',
    )

    class Meta:
        indexes = [
            models.Index(fields=['submitted_by', 'section', 'content_hash']),
        ]
        ordering = ['-assessed_at']

    def __str__(self):
        return f"Pre-assessment {self.verdict} for section {self.section_id}"
