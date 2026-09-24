"""Delete AI checks no proposal section points at any more.

Editing a section box and checking again leaves the earlier check behind -
working state, not a record. This command clears those after the retention
window, from cron or by hand before a backup.

    py manage.py sweep_pre_assessments --dry-run
    py manage.py sweep_pre_assessments

**A check a section change points at is never touched**: it is the stored
result every reader of that proposal sees, and part of the request's record.
This used to select by `consumed_by` - set only by the v3 single-section
flow - so every proposal check looked unsubmitted, and a sweep would have
deleted them all.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from api import pre_assessment
from api.models import RevisionPreAssessment


class Command(BaseCommand):
    help = "Delete AI checks no proposal section points at, older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=pre_assessment.RETENTION_DAYS,
            help=f"retention window (default {pre_assessment.RETENTION_DAYS})",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="report what would go, delete nothing",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timezone.timedelta(days=options["days"])
        stale = RevisionPreAssessment.objects.filter(
            section_change__isnull=True, assessed_at__lt=cutoff
        )
        count = stale.count()
        kept = RevisionPreAssessment.objects.filter(
            section_change__isnull=False
        ).count()

        if options["dry_run"]:
            self.stdout.write(
                f"would delete {count} superseded check(s) older than "
                f"{options['days']} days; {kept} in use untouched"
            )
            return

        stale.delete()
        self.stdout.write(self.style.SUCCESS(
            f"deleted {count} superseded check(s); {kept} in use untouched"
        ))
