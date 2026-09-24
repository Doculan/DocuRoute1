"""Bring already-stored section content up to the current extraction rules.

Sections extracted before the Markdown-aware cleaner landed still carry
pymupdf4llm artifacts — <br> soft wraps, "- " bullet prefixes, stray "#" and
repeated page-header bands — which is why the same manual looks different
depending on when it was uploaded.

This rewrites section content in place rather than re-extracting, because
recreating sections would lose them: SectionHistory.section cascades on
delete, taking the section's history with it, and a section a change
request has touched cannot be deleted at all (SectionChange.section is
PROTECT).

Dry run by default; pass --apply to write.
"""

from django.core.management.base import BaseCommand
from api.models import ManualSection
from ml.ocr_engine import clean_extracted_text


class Command(BaseCommand):
    help = "Re-clean stored ManualSection content using the current extraction rules."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without this the command only reports them.",
        )
        parser.add_argument(
            "--manual",
            type=int,
            help="Limit to a single manual id.",
        )
        parser.add_argument(
            "--show",
            type=int,
            default=3,
            help="How many before/after samples to print (default 3).",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        manual_id = options["manual"]
        show = options["show"]

        sections = ManualSection.objects.all().order_by("manual_id", "order")
        if manual_id:
            sections = sections.filter(manual_id=manual_id)

        changed = []
        emptied = []

        for section in sections:
            original = section.content or ""
            cleaned = clean_extracted_text(original)

            if cleaned == original:
                continue

            # Cleaning a section down to nothing means it held only page-header
            # or markup lines. Leave it alone and report it rather than blanking
            # content a human may still need to look at.
            if original.strip() and not cleaned.strip():
                emptied.append(section)
                continue

            changed.append((section, original, cleaned))

        self._report(changed, emptied, show)

        if not changed:
            self.stdout.write(self.style.SUCCESS("Nothing to change."))
            return

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run — {len(changed)} section(s) would be updated. "
                    "Re-run with --apply to write."
                )
            )
            return

        for section, _original, cleaned in changed:
            section.content = cleaned
            section.save(update_fields=["content"])

        self.stdout.write(self.style.SUCCESS(f"\nUpdated {len(changed)} section(s)."))

    def _report(self, changed, emptied, show):
        self.stdout.write(f"Sections needing cleanup: {len(changed)}")
        if emptied:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {len(emptied)} section(s) that would be emptied entirely: "
                    + ", ".join(f"#{s.id} {s.subtitle[:30]!r}" for s in emptied[:5])
                )
            )

        for section, original, cleaned in changed[:show]:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"--- section #{section.id} · {section.subtitle[:50]}"
            ))
            for label, text in (("BEFORE", original), ("AFTER", cleaned)):
                self.stdout.write(f"  {label}:")
                for line in text.split("\n")[:6]:
                    self.stdout.write(f"    {line[:110]}")
