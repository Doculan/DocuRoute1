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

    def __str__(self):
        return f"{self.title} ({self.department.name})"


class ManualSection(models.Model):
    TAG_CHOICES = [
        ('POLICY', 'Policy'),
        ('PROCEDURE', 'Procedure'),
        ('RESPONSIBILITY', 'Responsibility'),
        ('WORKING INSTRUCTION', 'Working Instruction'),
        ('UNTAGGED', 'Untagged'),
    ]
    manual = models.ForeignKey(
        Manual,
        on_delete=models.CASCADE,
        related_name='sections'
    )
    subtitle = models.CharField(max_length=255)  # admin defines this
    content = models.TextField()                  # OCR extracted text
    tag = models.CharField(
        max_length=50,
        choices=TAG_CHOICES,
        default='UNTAGGED'
    )                                             # SVM auto-tags this
    page_number = models.IntegerField(null=True, blank=True)
    order = models.IntegerField(default=0)        # section order in manual
    version = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.subtitle} [{self.tag}] — {self.manual.title}"

class SectionHistory(models.Model):
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
    uploaded_file = models.FileField(upload_to='revisions/')
    diff_text = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_notes = models.TextField(blank=True)

    def __str__(self):
        return f"Revision by {self.submitted_by} on {self.section.subtitle}"
