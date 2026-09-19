import uuid

from django.db import models
from django.contrib.auth.models import AbstractUser

class Department(models.Model):
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('staff', 'Staff'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='staff')
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
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name='manuals'
    )
    uploaded_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_manuals'
    )
    file = models.FileField(upload_to='mastercopies/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    version = models.IntegerField(default=1)  # major QMS version
    revision = models.IntegerField(default=0)  # minor revision counter

    def __str__(self):
        return f"{self.title} ({self.department.name})"


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
    """Snapshot of a section before each edit."""
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
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, null=True, blank=True,
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
