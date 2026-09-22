"""The importer refuses the same bytes twice.

One master copy was once uploaded under a second name. It produced a
document with a different title, a worse extraction of the same text, and
nothing linking the two - the kind of thing nobody notices until a
revision is proposed against the wrong copy. A PDF's identity is its
contents, not its filename.
"""

import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from api.models import CustomUser, Department, Manual


TEMP_MEDIA = tempfile.mkdtemp(prefix="docuroute-import-tests-")

# A real PDF is not needed: the guard compares bytes, and the extraction
# that follows is allowed to find nothing. Using a minimal file keeps the
# test fast and independent of the OCR stack.
PDF_A = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"
PDF_B = b"%PDF-1.4\n1 0 obj\n<< /Type /Page >>\nendobj\ntrailer\n%%EOF\n"


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ImportDuplicateTests(TestCase):

    def setUp(self):
        self.source = Path(TEMP_MEDIA) / "mastercopies"
        if self.source.exists():
            shutil.rmtree(self.source)
        self.source.mkdir(parents=True)

        CustomUser.objects.create_user(
            username="import-admin", password="pw", role="admin",
            is_approved=True,
        )

    def write(self, name, data):
        (self.source / name).write_bytes(data)

    def run_import(self, *args):
        out = StringIO()
        call_command("import_mastercopies", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_the_same_bytes_under_a_second_name_are_refused(self):
        """The original failure, in miniature."""
        self.write("HRM_4.02.pdf", PDF_A)
        self.run_import()
        self.assertEqual(Manual.objects.count(), 1)

        self.write("HRM_4_MoGMsSE.02.pdf", PDF_A)
        output = self.run_import()

        self.assertEqual(Manual.objects.count(), 1)
        self.assertIn("dup", output)
        self.assertIn("HRM 4.02", output)

    def test_two_identical_files_in_one_run_import_once(self):
        """The database has nothing to say on a fresh clone, so the run
        has to notice its own duplicates."""
        self.write("FAM_6.02.pdf", PDF_A)
        self.write("FAM_6.02_copy.pdf", PDF_A)
        output = self.run_import()

        self.assertEqual(Manual.objects.count(), 1)
        self.assertIn("dup", output)

    def test_different_documents_still_import(self):
        """The guard must not over-apply: two real documents are two
        documents, however similar their names."""
        self.write("FAM_6.02.pdf", PDF_A)
        self.write("FAM_6.03.pdf", PDF_B)
        self.run_import()
        self.assertEqual(Manual.objects.count(), 2)

    def test_a_plain_re_run_reports_already_imported_not_duplicate(self):
        """Same bytes under the same title is an ordinary second run.
        Calling that a duplicate would make the word meaningless on the
        run where it matters."""
        self.write("FAM_6.02.pdf", PDF_A)
        self.run_import()
        output = self.run_import()

        self.assertIn("already imported", output)
        self.assertNotIn("dup ", output)
        self.assertEqual(Manual.objects.count(), 1)

    def test_a_dry_run_reports_the_duplicate_and_writes_nothing(self):
        self.write("FAM_6.02.pdf", PDF_A)
        self.write("FAM_6.02_again.pdf", PDF_A)
        output = self.run_import("--dry-run")

        self.assertEqual(Manual.objects.count(), 0)
        self.assertIn("dup", output)
        self.assertIn("dry run", output)

    def test_the_dry_run_and_the_real_run_agree(self):
        """A preview that reports two imports where the real run does one
        is worse than no preview."""
        self.write("FAM_6.02.pdf", PDF_A)
        self.write("FAM_6.02_again.pdf", PDF_A)

        preview = self.run_import("--dry-run")
        self.run_import()

        self.assertEqual(preview.count("would"), Manual.objects.count())
