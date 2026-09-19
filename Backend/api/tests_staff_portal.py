"""The staff portal's read paths: section search, revision filters, feedback.

These are the endpoints the five tabs are built on. Nothing here touches the
pipeline - the AI fields tested below are the snapshot stored at submission,
and reading them must never trigger an assessment.
"""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    CustomUser, Department, Manual, ManualRevision, ManualSection,
)


class StaffSectionSearchTests(TestCase):
    """Sections across manuals - the thing that justifies the tab."""

    def setUp(self):
        self.finance = Department.objects.create(name="Finance")
        self.registry = Department.objects.create(name="Registry")
        self.user = CustomUser.objects.create_user(
            username="staffer", password="pw", role="staff",
            is_approved=True, department=self.finance,
        )
        self.fam = Manual.objects.create(title="FAM", department=self.finance)
        self.hrm = Manual.objects.create(title="HRM", department=self.finance)
        self.other = Manual.objects.create(title="Registry Manual",
                                           department=self.registry)

        ManualSection.objects.create(
            manual=self.fam, subtitle="3.0 POLICIES", order=1, tag="POLICY",
            content="The Cashier shall release the cheque within five days.",
        )
        ManualSection.objects.create(
            manual=self.hrm, subtitle="4.0 PROCEDURES", order=1, tag="PROCEDURE",
            content="Recruitment follows the Civil Service Commission rules.",
        )
        ManualSection.objects.create(
            manual=self.other, subtitle="1.0 OBJECTIVES", order=1,
            content="Registry keeps the student records.",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def get(self, query=""):
        return self.client.get(f"/api/staff/sections/{query}")

    def test_it_spans_every_manual_in_the_department(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        manuals = {row["manual"] for row in response.data["results"]}
        self.assertEqual(manuals, {"FAM", "HRM"})

    def test_another_department_is_not_visible(self):
        titles = {r["manual"] for r in self.get().data["results"]}
        self.assertNotIn("Registry Manual", titles)

    def test_search_matches_words_inside_a_section(self):
        """Searching only titles would make this the same list one level
        down; matching the wording is the point."""
        response = self.get("?search=cheque")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["manual"], "FAM")

    def test_search_matches_the_title_too(self):
        response = self.get("?search=PROCEDURES")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["manual"], "HRM")

    def test_it_can_be_narrowed_to_one_manual(self):
        response = self.get(f"?manual={self.hrm.id}")
        self.assertEqual(response.data["count"], 1)

    def test_it_can_be_narrowed_by_section_type(self):
        response = self.get("?tag=POLICY")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["tag"], "POLICY")

    def test_a_user_with_no_department_is_told_so(self):
        loner = CustomUser.objects.create_user(
            username="unassigned", password="pw", role="staff", is_approved=True,
        )
        client = APIClient()
        client.force_authenticate(user=loner)
        self.assertEqual(client.get("/api/staff/sections/").status_code, 403)


class StaffRevisionListTests(TestCase):
    """Scope, status, and the stored assessment - read-only throughout."""

    def setUp(self):
        self.department = Department.objects.create(name="Finance")
        self.user = CustomUser.objects.create_user(
            username="staffer", password="pw", role="staff",
            is_approved=True, department=self.department,
        )
        self.colleague = CustomUser.objects.create_user(
            username="colleague", password="pw", role="staff",
            is_approved=True, department=self.department,
        )
        self.manual = Manual.objects.create(title="FAM", department=self.department)
        self.section = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES", order=1,
            content="The Cashier shall release the cheque.",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def a_revision(self, *, who=None, status="pending", notes="", reviewed=False,
                   **extra):
        revision = ManualRevision.objects.create(
            section=self.section, submitted_by=who or self.user,
            status=status, reviewer_notes=notes,
            change_reason="Updated after the August 2026 review.", **extra
        )
        if reviewed:
            revision.reviewed_at = timezone.now()
            revision.reviewed_by = self.colleague
            revision.save(update_fields=["reviewed_at", "reviewed_by"])
        return revision

    def get(self, query=""):
        return self.client.get(f"/api/staff/revisions/{query}")

    # -- scope --------------------------------------------------

    def test_mine_is_the_default_and_excludes_colleagues(self):
        self.a_revision()
        self.a_revision(who=self.colleague)
        self.assertEqual(len(self.get().data), 1)

    def test_my_office_includes_the_whole_department(self):
        self.a_revision()
        self.a_revision(who=self.colleague)
        rows = self.get("?scope=office").data
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["is_mine"] for r in rows}, {True, False})

    # -- status -------------------------------------------------

    def test_status_filters_narrow_the_list(self):
        self.a_revision(status="pending")
        self.a_revision(status="approved", reviewed=True)
        self.assertEqual(len(self.get("?status=pending").data), 1)
        self.assertEqual(len(self.get("?status=approved").data), 1)
        self.assertEqual(len(self.get("?status=all").data), 2)

    def test_returned_is_a_rejection_that_carries_notes(self):
        """A submitter needs 'act on this' separated from 'refused', and
        that distinction is the notes, not a stored state."""
        self.a_revision(status="rejected", notes="Please cite the clause.",
                        reviewed=True)
        self.a_revision(status="rejected", reviewed=True)
        self.assertEqual(len(self.get("?status=returned").data), 1)
        self.assertEqual(len(self.get("?status=rejected").data), 2)

    # -- the stored assessment ----------------------------------

    def test_the_snapshot_travels_with_the_row(self):
        self.a_revision(
            ai_source="staff_precheck", ai_verdict="needs_revision",
            ai_explanation_staff="This would likely need adjusting.",
            ai_issues=[{"label": "modal_weakened", "clause": "7.5.3"}],
            ai_assessed_at=timezone.now(),
        )
        row = self.get().data[0]
        self.assertEqual(row["ai_source"], "staff_precheck")
        self.assertEqual(row["ai_verdict"], "needs_revision")
        self.assertTrue(row["ai_explanation_staff"])
        self.assertEqual(row["ai_issues"][0]["label"], "modal_weakened")
        self.assertTrue(row["ai_assessed_at"])

    def test_reading_the_list_never_produces_an_assessment(self):
        """The list is a record, not a trigger."""
        revision = self.a_revision()
        self.get()
        revision.refresh_from_db()
        self.assertEqual(revision.ai_source, "none")
        self.assertEqual(revision.ai_verdict, "")

    # -- feedback -----------------------------------------------

    def test_feedback_is_unread_until_it_is_opened(self):
        self.a_revision(status="rejected", notes="Please cite the clause.",
                        reviewed=True)
        self.assertTrue(self.get().data[0]["has_unread_feedback"])

    def test_a_decision_with_no_note_is_not_unread_feedback(self):
        self.a_revision(status="approved", reviewed=True)
        self.assertFalse(self.get().data[0]["has_unread_feedback"])

    def test_marking_it_seen_clears_the_badge(self):
        revision = self.a_revision(status="rejected", notes="Cite the clause.",
                                   reviewed=True)
        seen = self.client.post(f"/api/staff/revisions/{revision.id}/seen/")
        self.assertEqual(seen.status_code, 200)
        self.assertFalse(self.get().data[0]["has_unread_feedback"])

    def test_newer_feedback_becomes_unread_again(self):
        """Reviewed a second time after being read - the submitter has not
        seen the new note."""
        revision = self.a_revision(status="rejected", notes="First note.",
                                   reviewed=True)
        self.client.post(f"/api/staff/revisions/{revision.id}/seen/")
        revision.reviewer_notes = "Second note."
        revision.reviewed_at = timezone.now()
        revision.save(update_fields=["reviewer_notes", "reviewed_at"])
        self.assertTrue(self.get().data[0]["has_unread_feedback"])

    def test_you_cannot_mark_someone_elses_revision_seen(self):
        revision = self.a_revision(who=self.colleague, status="rejected",
                                   notes="Cite the clause.", reviewed=True)
        response = self.client.post(f"/api/staff/revisions/{revision.id}/seen/")
        self.assertEqual(response.status_code, 404)
        revision.refresh_from_db()
        self.assertIsNone(revision.feedback_seen_at)
