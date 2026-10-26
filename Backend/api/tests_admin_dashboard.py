"""The admin landing page, in one request.

Two things here are worth guarding beyond "the numbers add up".

The first is the chart threshold. Whether a line is drawn or a table is
printed is a claim about whether the data has a shape, and it is decided in
the endpoint precisely so it can be tested rather than argued about in a
component.

The second is that nothing on this screen runs an assessment. A dashboard
that quietly reassessed on load would show figures nobody acted on, so the
test makes the pipeline explode and expects the dashboard not to notice.

Rewritten for proposals when the v3 single-section flow was removed
(v4.1.0): submitted, agreed (locked) and returned are counted from
proposals, on the day each happened.
"""

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Announcement, CustomUser, Manual, ManualSection, Office,
    Proposal, ProposalVersion,
)


class AdminDashboardTests(TestCase):

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username="dash-admin", password="pw", role="admin", is_approved=True,
        )
        self.staff = CustomUser.objects.create_user(
            username="dash-staff", password="pw", role="staff",
            is_approved=True,
        )
        self.office = Office.objects.create(name="Accounting Office", abbreviation="ACC")
        self.other = Office.objects.create(name="Budget Office", abbreviation="BUD")

        self.manual = Manual.objects.create(
            title="FAM 6.02", uploaded_by=self.admin,
        )
        self.section = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES",
            content="The Cashier shall release the cheque.", tag="POLICY",
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    # -- helpers ---------------------------------------------------

    def get(self):
        response = self.client.get("/api/admin/dashboard/")
        self.assertEqual(response.status_code, 200)
        return response.data

    def ago(self, days):
        return timezone.now() - timedelta(days=days)

    def a_submission(self, submitted_days_ago=0, locked_days_ago=None):
        """A proposal submitted on one day and, optionally, agreed on another.

        Each on its own document: an office holds one open proposal per
        document, and a locked one no longer counts as open.
        """
        manual = Manual.objects.create(title="Doc", uploaded_by=self.admin)
        proposal = Proposal.objects.create(
            manual=manual, initiating_office=self.office, created_by=self.staff,
            status=Proposal.CONCURRENCE if locked_days_ago is None else Proposal.LOCKED,
            locked_at=None if locked_days_ago is None else self.ago(locked_days_ago),
        )
        version = ProposalVersion.objects.create(
            proposal=proposal, number=1, submitted_by=self.staff,
            submitted_at=self.ago(submitted_days_ago),
        )
        return proposal, version

    # -- access ----------------------------------------------------

    def test_staff_cannot_read_the_admin_dashboard(self):
        staff_client = APIClient()
        staff_client.force_authenticate(user=self.staff)
        self.assertEqual(
            staff_client.get("/api/admin/dashboard/").status_code, 403
        )

    def test_signed_out_is_refused(self):
        self.assertEqual(
            APIClient().get("/api/admin/dashboard/").status_code, 401
        )

    # -- 1. attention ----------------------------------------------

    def test_an_empty_system_reports_zeroes_rather_than_omitting_them(self):
        """"Nothing is waiting" is a real answer, and the client should not
        have to infer it from a missing key."""
        attention = self.get()["attention"]
        for key in ("pending_users", "proposals_drafting",
                    "proposals_in_concurrence", "proposals_locked"):
            self.assertEqual(attention[key], 0, key)

    def test_accounts_waiting_for_approval_are_counted(self):
        CustomUser.objects.create_user(
            username="waiting", password="pw", role="staff", is_approved=False,
        )
        self.assertEqual(self.get()["attention"]["pending_users"], 1)

    def test_an_unapproved_admin_is_not_an_account_waiting_for_approval(self):
        """The queue on Users is staff registrations. An admin created from
        the command line has is_approved false until make_admin runs, and
        counting that would send someone to a screen it is not on."""
        CustomUser.objects.create_user(
            username="raw-superuser", password="pw", role="admin",
            is_approved=False,
        )
        self.assertEqual(self.get()["attention"]["pending_users"], 0)

    def test_untagged_sections_are_counted_however_they_are_blank(self):
        ManualSection.objects.create(
            manual=self.manual, subtitle="4.0", content="x", tag="",
        )
        ManualSection.objects.create(
            manual=self.manual, subtitle="5.0", content="x", tag="UNTAGGED",
        )
        self.assertEqual(self.get()["attention"]["untagged_sections"], 2)

    # -- 3. upcoming: the next deadlines ----------------------------

    def a_deadline(self, title, days, active=True):
        from api.models import Deadline, DeadlineType
        dtype, _ = DeadlineType.objects.get_or_create(name="Internal quality audit")
        return Deadline.objects.create(
            title=title, type=dtype, due_on=timezone.localdate() + timedelta(days=days),
            active=active, created_by=self.admin,
            obligations_total=12, obligations_open=7, obligations_met=5,
        )

    def test_the_next_deadlines_with_how_many_offices_owe_them(self):
        self.a_deadline("ISO surveillance audit", 3)
        rows = self.get()["upcoming"]
        self.assertEqual([(r["title"], r["type"], r["unmet"]) for r in rows],
                         [("ISO surveillance audit", "Internal quality audit",
                           "7 of 12 not yet met")])

    def test_past_and_inactive_deadlines_are_not_upcoming(self):
        self.a_deadline("Last week", -7)
        self.a_deadline("Withdrawn", 2, active=False)
        data = self.get()
        self.assertEqual(data["upcoming"], [])
        self.assertEqual(data["upcoming_total"], 0)

    def test_live_announcements_are_counted(self):
        today = timezone.localdate()
        Announcement.objects.create(title="Banner", created_by=self.admin)
        Announcement.objects.create(title="Expired", expires_on=today - timedelta(days=1),
                                    created_by=self.admin)
        Announcement.objects.create(title="Off", active=False, created_by=self.admin)
        self.assertEqual(self.get()["system"]["banners_live"], 1)

    # -- 4. system -------------------------------------------------

    def test_system_counts_describe_what_is_actually_installed(self):
        self.a_submission()
        system = self.get()["system"]
        self.assertEqual(system["manuals"], 2)
        self.assertEqual(system["sections"], 1)
        self.assertEqual(system["offices"], 2)
        self.assertEqual(system["staff"], 1)
        self.assertEqual(system["admins"], 1)
        self.assertEqual(system["proposals_total"], 1)

    # -- the rule that matters most --------------------------------

    def test_the_dashboard_never_runs_the_pipeline(self):
        """Rule: an assessment is made once, when the section is checked,
        and displayed thereafter. The pipeline is made to raise, and the
        dashboard must not touch it."""
        self.a_submission(submitted_days_ago=1, locked_days_ago=0)
        with mock.patch(
            "ml.revision_pipeline.pipeline.assess_texts",
            side_effect=AssertionError("the dashboard ran an assessment"),
        ):
            data = self.get()
        self.assertEqual(len(data["proposals"]), 1)
