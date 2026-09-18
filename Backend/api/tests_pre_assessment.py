"""The check runs before submission, and the reviewer reads what staff read.

These exercise the real pipeline rather than a stub. The guarantee under test
is that a submitted revision carries the assessment of exactly the content
submitted, and a stub would let a hashing mistake through untouched.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import (
    CustomUser, Department, Manual, ManualRevision, ManualSection,
    RevisionPreAssessment,
)


class PreSubmissionAssessmentTests(TestCase):

    PROPOSED = "The Accounting Staff-4 shall verify the request within ten days."
    REASON = "Extended after the August 2026 management review."

    def setUp(self):
        self.department = Department.objects.create(name="Finance")
        self.user = CustomUser.objects.create_user(
            username="staffer", password="pw", role="staff",
            is_approved=True, department=self.department,
        )
        self.manual = Manual.objects.create(
            title="Financial Administrative Manual", department=self.department,
        )
        self.section = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES ON DISBURSEMENT",
            content="The Accounting Staff-4 shall verify the request within five days.",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def check(self, proposed=None, reason=None):
        return self.client.post(
            "/api/revisions/pre-assess/{}/".format(self.section.id),
            {"proposed_content": proposed or self.PROPOSED,
             "change_reason": reason or self.REASON},
            format="json",
        )

    def submit(self, assessment_id=None, proposed=None, reason=None, **extra):
        body = {"proposed_content": proposed or self.PROPOSED,
                "change_reason": reason or self.REASON}
        if assessment_id is not None:
            body["assessment_id"] = assessment_id
        body.update(extra)
        return self.client.post(
            "/api/revisions/propose-text/{}/".format(self.section.id),
            body, format="json",
        )

    def as_reviewer(self, username):
        admin = CustomUser.objects.create_user(
            username=username, password="pw", role="admin", is_approved=True,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        return client

    # -- the check itself ---------------------------------------

    def test_the_check_returns_a_verdict_and_an_id(self):
        response = self.check()
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.data["verdict"],
                      ("approve", "needs_revision", "reject"))
        self.assertTrue(response.data["assessment_id"])
        self.assertTrue(response.data["explanation"])
        self.assertTrue(response.data["model_fingerprint"])

    def test_the_check_applies_the_clause_6_3_rule_too(self):
        """Told about a throwaway reason now, not after reading a verdict."""
        response = self.check(reason="update")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["field"], "change_reason")

    def test_the_submitter_is_addressed_not_the_reviewer(self):
        self.check()
        snapshot = RevisionPreAssessment.objects.get()
        self.assertTrue(snapshot.explanation_staff)
        self.assertTrue(snapshot.explanation_reviewer)
        self.assertNotEqual(snapshot.explanation_staff,
                            snapshot.explanation_reviewer)

    def test_checking_the_same_content_twice_reads_the_same(self):
        """Seeded by content, so a re-check is not a reword."""
        first, second = self.check(), self.check()
        self.assertEqual(first.data["explanation"], second.data["explanation"])

    # -- the check is required ----------------------------------

    def test_submitting_without_checking_is_refused(self):
        response = self.submit()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason"], "missing")
        self.assertEqual(ManualRevision.objects.count(), 0)

    def test_an_unknown_assessment_id_is_refused(self):
        response = self.submit(assessment_id="not-a-real-id")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason"], "unknown")

    def test_a_valid_check_lets_the_submission_through(self):
        checked = self.check()
        response = self.submit(assessment_id=checked.data["assessment_id"])
        self.assertEqual(response.status_code, 201)
        revision = ManualRevision.objects.get()
        self.assertEqual(revision.ai_source, "staff_precheck")
        self.assertEqual(revision.ai_verdict, checked.data["verdict"])
        self.assertTrue(revision.ai_assessed_at)
        self.assertTrue(revision.ai_model_fingerprint)

    def test_the_verdict_never_blocks_the_submission(self):
        """Required to check, free to disagree."""
        weakened = "The Accounting Staff-4 may verify the request."
        checked = self.check(proposed=weakened)
        self.assertIn(checked.data["verdict"], ("needs_revision", "reject"))
        response = self.submit(
            assessment_id=checked.data["assessment_id"], proposed=weakened,
        )
        self.assertEqual(response.status_code, 201)

    # -- staleness ----------------------------------------------

    def test_editing_after_the_check_requires_another_check(self):
        checked = self.check()
        response = self.submit(
            assessment_id=checked.data["assessment_id"],
            proposed=self.PROPOSED + " The Cashier countersigns.",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason"], "stale")
        self.assertIn("changed the text", response.data["error"])
        self.assertEqual(ManualRevision.objects.count(), 0)

    def test_changing_the_reason_after_the_check_also_counts(self):
        checked = self.check()
        response = self.submit(
            assessment_id=checked.data["assessment_id"],
            reason="A different reason entirely, written afterwards.",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason"], "stale")

    def test_the_section_moving_underneath_says_so_differently(self):
        """Not the submitter's doing, so not the submitter's message."""
        checked = self.check()
        self.section.content = "The Cashier shall verify the request within five days."
        self.section.save()
        response = self.submit(assessment_id=checked.data["assessment_id"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("updated by someone else", response.data["error"])

    def test_whitespace_alone_does_not_invalidate_a_check(self):
        """Being sent back over a trailing space teaches people to distrust
        the check, so the hash ignores what a reader would."""
        checked = self.check()
        response = self.submit(
            assessment_id=checked.data["assessment_id"],
            proposed=self.PROPOSED + "   \n",
        )
        self.assertEqual(response.status_code, 201)

    def test_a_snapshot_cannot_be_used_twice(self):
        checked = self.check()
        self.submit(assessment_id=checked.data["assessment_id"])
        again = self.submit(assessment_id=checked.data["assessment_id"])
        self.assertEqual(again.status_code, 400)
        self.assertEqual(ManualRevision.objects.count(), 1)

    def test_another_user_cannot_borrow_a_check(self):
        checked = self.check()
        other = CustomUser.objects.create_user(
            username="other-staffer", password="pw", role="staff",
            is_approved=True, department=self.department,
        )
        client = APIClient()
        client.force_authenticate(user=other)
        response = client.post(
            "/api/revisions/propose-text/{}/".format(self.section.id),
            {"proposed_content": self.PROPOSED, "change_reason": self.REASON,
             "assessment_id": checked.data["assessment_id"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    # -- the result is the server's, not the client's -----------

    def test_a_client_supplied_verdict_is_ignored(self):
        checked = self.check()
        self.submit(
            assessment_id=checked.data["assessment_id"],
            ai_verdict="approve", ai_explanation="Looks fine to me.",
            verdict="approve",
        )
        revision = ManualRevision.objects.get()
        self.assertEqual(revision.ai_verdict, checked.data["verdict"])
        self.assertNotEqual(revision.ai_explanation, "Looks fine to me.")

    # -- what the reviewer sees ---------------------------------

    def test_the_listing_carries_the_snapshot_and_its_provenance(self):
        checked = self.check()
        self.submit(assessment_id=checked.data["assessment_id"])
        row = self.as_reviewer("reviewer1").get("/api/admin/revisions/").data[0]
        self.assertEqual(row["ai_source"], "staff_precheck")
        self.assertTrue(row["ai_explanation_staff"])
        self.assertTrue(row["ai_assessed_at"])
        self.assertFalse(row["ai_section_changed"])

    def test_the_reviewer_is_told_when_the_section_moved_afterwards(self):
        checked = self.check()
        self.submit(assessment_id=checked.data["assessment_id"])
        self.section.content = "Something else entirely now."
        self.section.save()
        row = self.as_reviewer("reviewer2").get("/api/admin/revisions/").data[0]
        self.assertTrue(row["ai_section_changed"])

    # -- the reviewer-side fallback -----------------------------

    def test_a_reviewer_cannot_re_assess_what_the_submitter_read(self):
        checked = self.check()
        self.submit(assessment_id=checked.data["assessment_id"])
        revision = ManualRevision.objects.get()
        response = self.as_reviewer("reviewer3").get(
            "/api/revisions/{}/ai-assessment/".format(revision.id)
        )
        self.assertEqual(response.status_code, 409)

    def test_a_revision_with_no_assessment_can_still_be_assessed(self):
        """The fallback exists for rows predating the pre-submission check."""
        revision = ManualRevision.objects.create(
            section=self.section, submitted_by=self.user,
            proposed_content=self.PROPOSED, change_reason=self.REASON,
            status="pending", ai_source="none",
        )
        response = self.as_reviewer("reviewer4").get(
            "/api/revisions/{}/ai-assessment/".format(revision.id)
        )
        self.assertEqual(response.status_code, 200)
