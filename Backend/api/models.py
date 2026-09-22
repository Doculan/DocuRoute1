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
        return f"{self.user} — {self.position}"

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

    Only read when `Manual.offices_overridden` is set. The owner is on
    `Manual.owning_office` and is deliberately not duplicated here: it is
    approval authority, a different thing from the working relationships
    below, and one row that can only ever have one value does not belong
    in a join table.
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
    version = models.IntegerField(default=1)  # major QMS version
    revision = models.IntegerField(default=0)  # minor revision counter

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
        when someone tries."""
        return bool(self.concurring_offices())


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
