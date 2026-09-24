"""Re-extract stored manuals from their master-copy files, in place.

`clean_section_content` re-runs the cleaner over text that is already stored,
which cannot recover anything the *extractor* lost. When a fix changes how the
PDF is read - a table row that used to be dropped, a wrapped row that is now
joined - the text has to come from the file again.

Sections are matched to their re-extracted counterparts by section number and
**updated in place**. Nothing is deleted: `SectionHistory.section` cascades
on delete, so recreating sections would take their history with them, and a
section a change request has touched cannot be deleted at all.

Dry run by default; pass --apply to write. Back the database up first.
"""

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import Manual, ManualSection
from ml.ocr_engine import extract_text

_NUMBER_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)")


def section_key(subtitle: str) -> str:
    """The section number, which is what stays stable across extractions."""
    match = _NUMBER_RE.match(subtitle or "")
    return match.group(1) if match else (subtitle or "").strip().lower()


class Command(BaseCommand):
    help = "Re-extract stored manuals from their files and update sections in place."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write the changes. Without this, only report them.")
        parser.add_argument("--manual", type=int, help="Limit to a single manual id.")
        parser.add_argument("--title", help="Limit to manuals whose title contains this.")
        parser.add_argument("--show", type=int, default=2,
                            help="How many before/after samples to print.")

    def handle(self, *args, **options):
        from api.views import _split_into_sections

        manuals = Manual.objects.all().order_by("id")
        if options["manual"]:
            manuals = manuals.filter(id=options["manual"])
        if options["title"]:
            manuals = manuals.filter(title__icontains=options["title"])

        totals = {"matched": 0, "changed": 0, "unmatched_stored": 0, "new": 0}
        shown = 0

        for manual in manuals:
            if not manual.file:
                continue
            try:
                with manual.file.open("rb") as handle:
                    raw = handle.read()
                text = extract_text(raw, manual.file.name)
            except Exception as error:      # noqa: BLE001 - reported, not raised
                self.stderr.write(f"  {manual.title}: could not read file ({error})")
                continue
            if not text.strip():
                self.stderr.write(f"  {manual.title}: extracted nothing, skipped")
                continue

            blocks = _split_into_sections(text, manual.title)
            fresh = {}
            for block in blocks:
                fresh.setdefault(section_key(block["subtitle"]), block)

            stored = list(manual.sections.all().order_by("id"))
            changed_here = []
            for section in stored:
                block = fresh.get(section_key(section.subtitle))
                if block is None:
                    totals["unmatched_stored"] += 1
                    continue
                totals["matched"] += 1
                if section.content == block["content"] and section.subtitle == block["subtitle"]:
                    continue
                changed_here.append((section, block))

            totals["changed"] += len(changed_here)
            stored_keys = {section_key(s.subtitle) for s in stored}
            totals["new"] += sum(1 for key in fresh if key not in stored_keys)

            if changed_here and shown < options["show"]:
                section, block = changed_here[0]
                shown += 1
                self.stdout.write(f"\n--- {manual.title} :: {section.subtitle}")
                self.stdout.write("  BEFORE:")
                for line in section.content.splitlines()[:5]:
                    self.stdout.write("    " + line[:120])
                self.stdout.write("  AFTER:")
                for line in block["content"].splitlines()[:5]:
                    self.stdout.write("    " + line[:120])

            if options["apply"] and changed_here:
                with transaction.atomic():
                    for section, block in changed_here:
                        section.subtitle = block["subtitle"]
                        section.content = block["content"]
                        section.save(update_fields=["subtitle", "content"])

        self.stdout.write("")
        self.stdout.write(f"matched to a re-extracted section : {totals['matched']}")
        self.stdout.write(f"content or subtitle differs       : {totals['changed']}")
        self.stdout.write(f"stored but not found in the file  : {totals['unmatched_stored']}")
        self.stdout.write(f"in the file but not stored        : {totals['new']}")
        if options["apply"]:
            self.stdout.write(self.style.SUCCESS(
                f"Updated {totals['changed']} section(s) in place. Nothing was deleted."
            ))
        else:
            self.stdout.write("Dry run. Re-run with --apply to write.")
