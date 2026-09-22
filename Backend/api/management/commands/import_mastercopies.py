"""Load the master copies into an empty database.

`db.sqlite3` is not in version control - it holds the extracted manual text,
it cannot be merged, and the repository is public - so a fresh clone has the
PDFs but no database. Rebuilding by hand means uploading nineteen files
through the admin screen one at a time, which nobody will do correctly twice.

Deliberately reuses `upload_manual`'s extraction path rather than
reimplementing it: the sections this produces have to be the same sections
the application would have produced, or a teammate's checkout quietly
diverges from everyone else's.

    py manage.py import_mastercopies
    py manage.py import_mastercopies --dry-run
    py manage.py import_mastercopies --replace

Refuses to import the same bytes twice. One master copy was once uploaded
under two names, which produced a second document with a different title,
a worse extraction of the same text, and no sign that the two were
related - the kind of thing nobody notices until a revision is proposed
against the wrong one. Titles and filenames are not a reliable identity
for a PDF; its contents are.
"""

import hashlib
import re
from pathlib import Path

from django.conf import settings

from django.core.management.base import BaseCommand

from api.models import CustomUser, Department, Manual, ManualSection
from api.views import _split_into_sections
from ml.ocr_engine import extract_text
from ml.svm_model import predict_section

# The filename prefix is the owning office: ASM_3.0.pdf -> ASM. Derived
# rather than hard-coded per file, so adding a master copy needs no change
# here, and reproducible on every machine - which a hand-made mapping in one
# person's database is not.
_PREFIX_RE = re.compile(r"^([A-Za-z]+)[_\s-]")

DEPARTMENT_NAMES = {
    "ASM": "ASM",
    "FAM": "FAM",
    "HRM": "HRM",
    "SDM": "SDM",
}

def _department_for(filename: str) -> str:
    match = _PREFIX_RE.match(filename)
    prefix = (match.group(1).upper() if match else "")
    return DEPARTMENT_NAMES.get(prefix, "Unassigned")

def _digest(data: bytes) -> str:
    """MD5, and only for spotting an identical file.

    Not a security claim - nobody is defending against a crafted
    collision here. The question is whether these are literally the same
    bytes as something already imported, and for that it is fast and
    sufficient.
    """
    return hashlib.md5(data).hexdigest()


def _existing_digests():
    """Every document already in the database, by the digest of its file.

    Built from what is on disk rather than from a stored hash: there is no
    hash column, and adding one to solve a problem an import-time read
    already solves would be a migration for nothing.
    """
    seen = {}
    for manual in Manual.objects.exclude(file=''):
        try:
            with manual.file.open('rb') as handle:
                seen[_digest(handle.read())] = manual
        except (FileNotFoundError, OSError, ValueError):
            # A manual whose file has gone is a separate problem, and not
            # one an importer should fail on.
            continue
    return seen


def _title_for(filename: str) -> str:
    """ASM_3.0.pdf -> "ASM 3.0"; the trailing description is dropped, since
    the document number is what people refer to.

    A dot is required in the number. Without it "HRM_4_MoGMsSE.02.pdf" - a
    name whose number is split across underscores - reads its second part as
    the whole number and becomes "HRM 4", which is a different document.
    """
    stem = Path(filename).stem
    parts = stem.split("_")
    if len(parts) >= 2 and re.match(r"^\d+\.\d+$", parts[1]):
        return f"{parts[0]} {parts[1]}"
    return stem.replace("_", " ")

class Command(BaseCommand):
    help = "Import the PDFs in media/mastercopies/ as manuals with sections."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="list what would be imported, write nothing",
        )
        parser.add_argument(
            "--replace", action="store_true",
            help="delete and re-import a manual that already exists",
        )

    def handle(self, *args, **options):
        source = Path(settings.MEDIA_ROOT) / "mastercopies"
        if not source.is_dir():
            self.stderr.write(f"no such directory: {source}")
            return

        pdfs = sorted(p for p in source.glob("*.pdf"))
        if not pdfs:
            self.stderr.write(f"no PDFs in {source}")
            return

        owner = (CustomUser.objects.filter(role="admin").order_by("id").first()
                 or CustomUser.objects.filter(is_superuser=True).first())
        if owner is None:
            self.stderr.write(
                "no admin user exists yet - create one first:\n"
                "    py manage.py createsuperuser\n"
                "    py manage.py make_admin <username>"
            )
            return

        self.stdout.write(f"{len(pdfs)} master copies in {source}\n")
        imported = skipped = duplicates = 0

        # Two lookups, because a duplicate can arrive from either
        # direction: the same bytes already in the database, or the same
        # bytes twice in this directory under different names. The second
        # matters on a fresh clone, where the first has nothing to say.
        by_digest = _existing_digests()
        seen_this_run = {}

        for path in pdfs:
            title = _title_for(path.name)
            department_name = _department_for(path.name)

            file_bytes = path.read_bytes()
            digest = _digest(file_bytes)

            already = by_digest.get(digest)
            if already is not None and not options["replace"]:
                # Same bytes under the same title is an ordinary re-run.
                # Same bytes under a *different* title is the thing worth
                # naming - two documents that are secretly one.
                if already.title == title:
                    self.stdout.write(
                        f"  skip    {title:<34} already imported"
                    )
                    skipped += 1
                else:
                    self.stdout.write(
                        f"  dup     {title:<34} same file as \"{already.title}\""
                    )
                    duplicates += 1
                continue

            twin = seen_this_run.get(digest)
            if twin is not None:
                self.stdout.write(
                    f"  dup     {title:<34} same file as {twin}"
                )
                duplicates += 1
                continue

            existing = Manual.objects.filter(title=title).first()
            if existing and not options["replace"]:
                self.stdout.write(f"  skip    {title:<34} already imported")
                skipped += 1
                continue

            if options["dry_run"]:
                # Recorded here too, or a dry run would report two
                # identical files as two imports and the real run would
                # then disagree with its own preview.
                seen_this_run[digest] = path.name
                self.stdout.write(
                    f"  would   {title:<34} -> {department_name}"
                )
                continue

            if existing:
                existing.delete()

            department, _ = Department.objects.get_or_create(name=department_name)

            # Point at the file already on disk instead of saving a copy.
            # `Manual.file` has upload_to='mastercopies/', which is the very
            # directory being scanned, so handing Django a File object makes
            # it write a second copy next to the original - and because the
            # name is taken, it appends a random suffix. Nineteen PDFs became
            # forty-eight, and the mangled names ("FAM_4_2s7frgp.01.pdf")
            # then parsed as a different document. The bytes are already in
            # the right place; only the reference is missing.
            manual = Manual.objects.create(
                title=title, department=department, uploaded_by=owner,
            )
            manual.file.name = f"mastercopies/{path.name}"
            manual.save(update_fields=["file"])

            try:
                text = extract_text(file_bytes, path.name)
            except Exception as error:
                self.stderr.write(f"  FAILED  {title:<34} {error}")
                manual.delete()
                continue

            count = 0
            if text.strip():
                created = []
                for index, block in enumerate(_split_into_sections(text, title)):
                    try:
                        tag = (predict_section(block["content"])
                               if block["content"].strip() else "UNTAGGED")
                    except Exception:
                        tag = "UNTAGGED"

                    parent = None
                    parent_index = block.get("parent_index")
                    if parent_index is not None and 0 <= parent_index < len(created):
                        parent = created[parent_index]

                    created.append(ManualSection.objects.create(
                        manual=manual, subtitle=block["subtitle"],
                        content=block["content"], tag=tag,
                        page_number=block.get("page_number"), order=index,
                        parent=parent, is_reviewed=False,
                    ))
                    count += 1

            imported += 1
            seen_this_run[digest] = path.name
            self.stdout.write(
                f"  ok      {title:<34} {department_name:<6} {count} sections"
            )

        if duplicates:
            self.stdout.write(
                f"\nskipped {duplicates} file(s) whose contents already exist. "
                f"A PDF is identified by its bytes here, not its name."
            )

        if options["dry_run"]:
            self.stdout.write("\ndry run - nothing was written")
            return

        self.stdout.write(self.style.SUCCESS(
            f"\nimported {imported}, skipped {skipped}. "
            f"{Manual.objects.count()} manuals and "
            f"{ManualSection.objects.count()} sections in the database."
        ))
        self.stdout.write(
            "\nNow clean the extracted text:\n"
            "    py manage.py reextract_manuals --apply"
        )
