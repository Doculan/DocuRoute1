"""The check is mandatory on the upload and merge paths too.

Both differ from the text path in the same way: the submitter is agreeing to
content they did not type. An upload is judged on whatever the extractor pulls
out of the file, and a merge on text the server builds. So both endpoints hand
that content back with the result - assessing text nobody has seen would be
worse than not assessing at all.
"""

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.models import (
    CustomUser, Department, Manual, ManualRevision, ManualSection,
)

REASON = "Consolidated after the August 2026 management review."


# Uploads land in MEDIA_ROOT, and MEDIA_ROOT in tests is the real media
# directory - so every run left a revision*.txt behind in the working tree
# and git slowly filled with test debris. A temporary root per run keeps the
# repository clean.
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="docuroute-tests-"))
class UploadPathTests(TestCase):

    UPLOADED = (
        "The Accounting Staff-4 may verify the request within ten days.\n"
        "The Cashier releases the cheque on approval.\n"
    )

    def setUp(self):
        self.department = Department.objects.create(name="Finance")
        self.user = CustomUser.objects.create_user(
            username="uploader", password="pw", role="staff",
            is_approved=True, department=self.department,
        )
        self.manual = Manual.objects.create(
            title="Financial Administrative Manual", department=self.department,
        )
        self.section = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES",
            content="The Accounting Staff-4 shall verify the request within five days.",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def a_file(self, text=None):
        return SimpleUploadedFile(
            "revision.txt", (text or self.UPLOADED).encode("utf-8"),
            content_type="text/plain",
        )

    def check(self, text=None, reason=REASON):
        return self.client.post(
            "/api/revisions/pre-assess/{}/".format(self.section.id),
            {"file": self.a_file(text), "change_reason": reason},
            format="multipart",
        )

    def upload(self, assessment_id=None, text=None, reason=REASON):
        body = {"file": self.a_file(text), "change_reason": reason}
        if assessment_id is not None:
            body["assessment_id"] = assessment_id
        return self.client.post(
            "/api/revisions/upload/{}/".format(self.section.id),
            body, format="multipart",
        )

    def test_the_check_returns_what_the_extractor_read(self):
        """The submitter agrees to the extracted text, so they must see it."""
        response = self.check()
        self.assertEqual(response.status_code, 200)
        self.assertIn("extracted_text", response.data)
        self.assertIn("Accounting Staff-4", response.data["extracted_text"])
        self.assertIn(response.data["verdict"],
                      ("approve", "needs_revision", "reject"))

    def test_uploading_without_checking_is_refused(self):
        response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason"], "missing")
        self.assertEqual(ManualRevision.objects.count(), 0)

    def test_a_checked_upload_goes_through_and_carries_the_snapshot(self):
        checked = self.check()
        response = self.upload(assessment_id=checked.data["assessment_id"])
        self.assertEqual(response.status_code, 201)
        revision = ManualRevision.objects.get()
        self.assertEqual(revision.ai_source, "staff_precheck")
        self.assertEqual(revision.ai_verdict, checked.data["verdict"])

    def test_uploading_a_different_file_needs_another_check(self):
        checked = self.check()
        response = self.upload(
            assessment_id=checked.data["assessment_id"],
            text=self.UPLOADED + "The Dean signs the release.\n",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason"], "stale")
        self.assertEqual(ManualRevision.objects.count(), 0)

    def test_an_unreadable_file_fails_the_check_not_the_submission(self):
        response = self.client.post(
            "/api/revisions/pre-assess/{}/".format(self.section.id),
            {"file": SimpleUploadedFile("empty.txt", b"", content_type="text/plain"),
             "change_reason": REASON},
            format="multipart",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("readable", response.data["error"])


class MergePathTests(TestCase):

    def setUp(self):
        self.department = Department.objects.create(name="Finance")
        self.user = CustomUser.objects.create_user(
            username="merger", password="pw", role="staff",
            is_approved=True, department=self.department,
        )
        self.manual = Manual.objects.create(
            title="Financial Administrative Manual", department=self.department,
        )
        self.target = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES",
            content="The Accounting Staff-4 shall verify the request within five days.",
        )
        self.source = ManualSection.objects.create(
            manual=self.manual, subtitle="4.0 PROCEDURES",
            content="The Cashier shall release the cheque once approved.",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def check(self):
        return self.client.post(
            "/api/revisions/pre-assess-merge/",
            {"source_section_id": self.source.id,
             "target_section_id": self.target.id, "change_reason": REASON},
            format="json",
        )

    def merge(self, assessment_id=None):
        body = {"source_section_id": self.source.id,
                "target_section_id": self.target.id, "change_reason": REASON}
        if assessment_id is not None:
            body["assessment_id"] = assessment_id
        return self.client.post(
            "/api/revisions/propose-merge/", body, format="json",
        )

    def test_the_check_returns_the_text_the_server_would_store(self):
        response = self.check()
        self.assertEqual(response.status_code, 200)
        self.assertIn("merged_content", response.data)
        self.assertIn("Accounting Staff-4", response.data["merged_content"])
        self.assertIn("Cashier", response.data["merged_content"])

    def test_merging_without_checking_is_refused(self):
        response = self.merge()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason"], "missing")
        self.assertEqual(ManualRevision.objects.count(), 0)

    def test_a_checked_merge_goes_through(self):
        checked = self.check()
        response = self.merge(assessment_id=checked.data["assessment_id"])
        self.assertEqual(response.status_code, 201)
        revision = ManualRevision.objects.get()
        self.assertEqual(revision.ai_source, "staff_precheck")
        self.assertEqual(revision.merge_type, "merge")

    def test_the_source_moving_is_not_blamed_on_the_submitter(self):
        """A merge rests on both sections. If the source is edited by someone
        else, the submitter changed nothing and must not be told they did."""
        checked = self.check()
        self.source.content = "The Cashier shall release the cheque within a day."
        self.source.save()
        response = self.merge(assessment_id=checked.data["assessment_id"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("updated by someone else", response.data["error"])

    def test_the_target_moving_says_the_same_thing(self):
        checked = self.check()
        self.target.content = "Something else entirely."
        self.target.save()
        response = self.merge(assessment_id=checked.data["assessment_id"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("updated by someone else", response.data["error"])

    def test_the_reviewer_is_told_when_a_source_changes_afterwards(self):
        checked = self.check()
        self.merge(assessment_id=checked.data["assessment_id"])
        self.source.content = "Changed after the merge was submitted."
        self.source.save()
        admin = CustomUser.objects.create_user(
            username="merge-reviewer", password="pw", role="admin",
            is_approved=True,
        )
        reviewer = APIClient()
        reviewer.force_authenticate(user=admin)
        row = reviewer.get("/api/admin/revisions/").data[0]
        self.assertTrue(row["ai_section_changed"])
