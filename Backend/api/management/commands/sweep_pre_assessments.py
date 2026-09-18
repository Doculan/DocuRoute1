"""Delete pre-assessments nobody submitted.

The endpoint sweeps opportunistically whenever someone runs a check, which is
enough while the system is in use and does nothing at all while it is idle.
This command exists so the sweep can be run deliberately - from cron, or by
hand before a backup - without waiting for a staff member to press a button.

    py manage.py sweep_pre_assessments --dry-run
    py manage.py sweep_pre_assessments

Consumed rows are never touched: those are attached to a revision and are part
of its record.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from api import pre_assessment
from api.models import RevisionPreAssessment


class Command(BaseCommand):
    help = "Delete unconsumed pre-assessments older than the retention window."

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
            consumed_by__isnull=True, assessed_at__lt=cutoff
        )
        count = stale.count()
        kept = RevisionPreAssessment.objects.filter(
            consumed_by__isnull=False
        ).count()

        if options["dry_run"]:
            self.stdout.write(
                f"would delete {count} unconsumed pre-assessment(s) older than "
                f"{options['days']} days; {kept} consumed row(s) untouched"
            )
            return

        stale.delete()
        self.stdout.write(self.style.SUCCESS(
            f"deleted {count} unconsumed pre-assessment(s); "
            f"{kept} consumed row(s) untouched"
        ))
