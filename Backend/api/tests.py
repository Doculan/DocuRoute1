"""API-level tests for the clause 6.3 change-reason rule.

The tier logic itself is tested in
``ml/revision_pipeline/tests/test_change_reason.py``, which runs without
Django. What matters here is the other half of the contract: that all three
submission endpoints actually apply it, refuse tier 1 with a message the
submitter can act on, and let tier 2 through so the pipeline can flag it
rather than the API blocking a revision that may be perfectly sound.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import CustomUser, Department, Manual, ManualRevision, ManualSection

BLOCKED = [
    "",                       # missing
    "update",                 # one word, under the length floor
    "typo fix",               # two words
    "...............",        # punctuation only
    "aaaaaaaaaaaaaaaaaaaa",   # one character repeated
]

ACCEPTED_BUT_WEAK = "Updated for compliance purposes"
ACCEPTED_CLEAN = "Bank details changed after the branch moved to LandBank."


class ChangeReasonValidationTests(TestCase):
    """Every submission path enforces the same two tiers."""

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
        self.other = ManualSection.objects.create(
            manual=self.manual, subtitle="4.0 PROCEDURES",
            content="The Cashier releases the cheque.",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    # -- tier 1: refused with a usable message -----------------

    def test_text_revision_rejects_every_tier_one_reason(self):
        for reason in BLOCKED:
            with self.subTest(reason=reason):
                response = self.client.post(
                    "/api/revisions/propose-text/{}/".format(self.section.id),
                    {"proposed_content": "The Accounting Staff-4 shall verify it within ten days.",
                     "change_reason": reason},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.data)
                self.assertEqual(response.data["field"], "change_reason")
                self.assertIn(response.data["reason_tier"], ("missing", "invalid"))
                # the message has to tell the submitter what to do
                self.assertIn("please", response.data["error"].lower())

    def test_merge_rejects_a_tier_one_reason(self):
        response = self.client.post(
            "/api/revisions/propose-merge/",
            {"source_section_id": self.other.id,
             "target_section_id": self.section.id,
             "change_reason": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason_tier"], "missing")

    def test_a_reason_that_only_repeats_the_section_title_is_refused(self):
        response = self.client.post(
            "/api/revisions/propose-text/{}/".format(self.section.id),
            {"proposed_content": "Something else entirely here.",
             "change_reason": self.section.subtitle},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason_tier"], "invalid")

    def test_nothing_is_stored_when_the_reason_is_refused(self):
        self.client.post(
            "/api/revisions/propose-text/{}/".format(self.section.id),
            {"proposed_content": "Something else entirely here.", "change_reason": "update"},
            format="json",
        )
        self.assertEqual(ManualRevision.objects.count(), 0)

    # -- tier 2: accepted, and left for the pipeline to flag ---

    def test_a_weak_reason_is_accepted(self):
        response = self.client.post(
            "/api/revisions/propose-text/{}/".format(self.section.id),
            {"proposed_content": "The Accounting Staff-4 shall verify it within ten days.",
             "change_reason": ACCEPTED_BUT_WEAK},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        revision = ManualRevision.objects.get(id=response.data["revision_id"])
        self.assertEqual(revision.change_reason, ACCEPTED_BUT_WEAK)

    def test_a_specific_reason_is_accepted_and_stored(self):
        response = self.client.post(
            "/api/revisions/propose-text/{}/".format(self.section.id),
            {"proposed_content": "The Accounting Staff-4 shall verify it within ten days.",
             "change_reason": "  " + ACCEPTED_CLEAN + "  "},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        revision = ManualRevision.objects.get(id=response.data["revision_id"])
        self.assertEqual(revision.change_reason, ACCEPTED_CLEAN)

    def test_the_reason_reaches_the_reviewer(self):
        self.client.post(
            "/api/revisions/propose-text/{}/".format(self.section.id),
            {"proposed_content": "The Accounting Staff-4 shall verify it within ten days.",
             "change_reason": ACCEPTED_CLEAN},
            format="json",
        )
        admin = CustomUser.objects.create_user(
            username="reviewer", password="pw", role="admin", is_approved=True,
        )
        reviewer = APIClient()
        reviewer.force_authenticate(user=admin)
        listing = reviewer.get("/api/admin/revisions/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.data[0]["change_reason"], ACCEPTED_CLEAN)
