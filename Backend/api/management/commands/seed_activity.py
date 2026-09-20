"""Fill the dashboard's activity chart with demonstration data.

The chart only draws once revisions land on five or more separate days, and
a real database this early has four. Without something like this the chart
is never seen before a presentation - which is the worst moment to discover
a layout problem.

Every row it writes is tagged in `change_reason`, so removing them is exact
rather than a guess at which revisions were real:

    py manage.py seed_activity            # write 14 days of activity
    py manage.py seed_activity --days 30
    py manage.py seed_activity --clear    # remove every row it wrote

It writes nothing else. No manual, section or user is created or edited, so
`--clear` returns the database to exactly what it was.

**Demonstration data only.** Do not run this on a server.
"""

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import CustomUser, ManualRevision, ManualSection

# Written into change_reason so the rows can be found again exactly. A flag
# field would need a migration for something that is not part of the model.
MARKER = "[seeded demo activity]"

REASONS = [
    "Aligned the wording with the 2026 management review.",
    "Corrected the office named in the approval step.",
    "Added the retention period required by the records policy.",
    "Removed a step that duplicated the one above it.",
    "Clarified who signs when the head of office is away.",
    "Updated the form reference after the template changed.",
]


class Command(BaseCommand):
    help = "Create (or remove) demonstration revision activity for the dashboard."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=14,
            help="how many days back to spread activity over (default 14)",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="delete every revision this command created and stop",
        )
        parser.add_argument(
            "--seed", type=int, default=20260920,
            help="random seed, so two runs produce the same shape",
        )

    def handle(self, *args, **options):
        seeded = ManualRevision.objects.filter(change_reason__startswith=MARKER)

        if options["clear"]:
            count = seeded.count()
            seeded.delete()
            self.stdout.write(self.style.SUCCESS(
                f"removed {count} seeded revision(s). "
                f"{ManualRevision.objects.count()} real revisions remain."
            ))
            return

        if seeded.exists():
            self.stdout.write(
                f"{seeded.count()} seeded revisions are already present. "
                "Run --clear first to start over."
            )
            return

        sections = list(ManualSection.objects.select_related("manual")[:40])
        if not sections:
            self.stderr.write(
                "no sections in the database - run import_mastercopies first"
            )
            return

        staff = list(CustomUser.objects.filter(role="staff", is_approved=True))
        if not staff:
            self.stderr.write(
                "no approved staff - run seed_test_users first"
            )
            return

        reviewer = CustomUser.objects.filter(role="admin").order_by("id").first()
        rng = random.Random(options["seed"])
        today = timezone.localdate()
        days = max(1, options["days"])

        created = decided = 0
        with transaction.atomic():
            for offset in range(days - 1, -1, -1):
                day = today - timedelta(days=offset)

                # Not every day has traffic, and a chart where every point
                # is occupied looks like generated data rather than a
                # workload. Weekends are quiet for the same reason.
                if day.weekday() >= 5:
                    if rng.random() < 0.75:
                        continue
                elif rng.random() < 0.2:
                    continue

                for _ in range(rng.randint(1, 4)):
                    section = rng.choice(sections)
                    submitted = timezone.make_aware(
                        timezone.datetime.combine(
                            day, timezone.datetime.min.time()
                        )
                    ) + timedelta(hours=rng.randint(8, 16),
                                  minutes=rng.randint(0, 59))

                    revision = ManualRevision.objects.create(
                        section=section,
                        submitted_by=rng.choice(staff),
                        proposed_content=(section.content or "")
                        + "\n\nReviewed and reworded for clarity.",
                        status="pending",
                        change_reason=f"{MARKER} {rng.choice(REASONS)}",
                        diff_text="",
                    )
                    created += 1

                    # Most submissions get a decision within a few days, and
                    # a decision is dated when it was made - which is what
                    # the chart's second and third series are counting.
                    reviewed_at = None
                    status = "pending"
                    if rng.random() < 0.7:
                        lag = rng.randint(0, 3)
                        if offset - lag >= 0:
                            status = ("approved" if rng.random() < 0.65
                                      else "rejected")
                            reviewed_at = submitted + timedelta(
                                days=lag, hours=rng.randint(1, 6)
                            )
                            decided += 1

                    ManualRevision.objects.filter(pk=revision.pk).update(
                        submitted_at=submitted,
                        reviewed_at=reviewed_at,
                        reviewed_by=reviewer if reviewed_at else None,
                        status=status,
                        # Half the decided rows carry a stored verdict, and
                        # some of those disagree with the decision, so the
                        # "assessment said ..." marker is visible too.
                        ai_verdict=(
                            rng.choice(["approve", "needs_revision", "reject"])
                            if reviewed_at and rng.random() < 0.5 else ""
                        ),
                        ai_source="staff_precheck" if reviewed_at else "none",
                    )

        active_days = len({
            timezone.localtime(value).date()
            for value in ManualRevision.objects.filter(
                change_reason__startswith=MARKER
            ).values_list("submitted_at", flat=True)
        })

        self.stdout.write(self.style.SUCCESS(
            f"\ncreated {created} revisions across {active_days} days "
            f"({decided} decided)."
        ))
        self.stdout.write(
            "\nThe dashboard chart needs 5 active days; you now have "
            f"{active_days}.\n"
            "\nTo put the database back exactly as it was:\n"
            "    py manage.py seed_activity --clear"
        )
