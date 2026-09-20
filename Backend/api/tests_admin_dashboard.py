"""The admin landing page, in one request.

Two things here are worth guarding beyond "the numbers add up".

The first is the chart threshold. Whether a line is drawn or a table is
printed is a claim about whether the data has a shape, and it is decided in
the endpoint precisely so it can be tested rather than argued about in a
component.

The second is that nothing on this screen re-runs an assessment. A dashboard
that quietly reassessed every revision on load would show figures the
reviewer never saw, so the test makes the pipeline explode and expects the
dashboard not to notice.
"""

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Announcement, CustomUser, Department, Manual, ManualRevision,
    ManualSection,
)
from api.views import ACTIVITY_CHART_MINIMUM_DAYS, ACTIVITY_WINDOW_DAYS


class AdminDashboardTests(TestCase):

    def setUp(self):
        self.finance = Department.objects.create(name="FAM")
        self.hr = Department.objects.create(name="HRM")

        self.admin = CustomUser.objects.create_user(
            username="dash-admin", password="pw", role="admin", is_approved=True,
        )
        self.staff = CustomUser.objects.create_user(
            username="dash-staff", password="pw", role="staff",
            is_approved=True, department=self.finance,
        )

        self.manual = Manual.objects.create(
            title="FAM 6.02", department=self.finance, uploaded_by=self.admin,
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

    def a_revision(self, status="pending", submitted_days_ago=0,
                   reviewed_days_ago=None, section=None, **extra):
        revision = ManualRevision.objects.create(
            section=section or self.section, submitted_by=self.staff,
            proposed_content="The Cashier shall release the cheque in a day.",
            status=status, change_reason="Management review.", **extra
        )
        # auto_now_add has to be written around rather than passed.
        ManualRevision.objects.filter(pk=revision.pk).update(
            submitted_at=timezone.now() - timedelta(days=submitted_days_ago),
            reviewed_at=(None if reviewed_days_ago is None
                         else timezone.now() - timedelta(days=reviewed_days_ago)),
        )
        revision.refresh_from_db()
        return revision

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
        self.assertEqual(attention["pending_revisions"], 0)
        self.assertEqual(attention["pending_users"], 0)
        self.assertIsNone(attention["oldest_pending_days"])

    def test_pending_work_is_counted_and_dated(self):
        self.a_revision(submitted_days_ago=4)
        self.a_revision(submitted_days_ago=1)
        CustomUser.objects.create_user(
            username="waiting", password="pw", role="staff", is_approved=False,
        )
        attention = self.get()["attention"]
        self.assertEqual(attention["pending_revisions"], 2)
        self.assertEqual(attention["pending_users"], 1)
        self.assertEqual(attention["oldest_pending_days"], 4)

    def test_an_unapproved_admin_is_not_an_account_waiting_for_approval(self):
        """The queue on Users is staff registrations. An admin created from
        the command line has is_approved false until make_admin runs, and
        counting that would send someone to a screen it is not on."""
        CustomUser.objects.create_user(
            username="raw-superuser", password="pw", role="admin",
            is_approved=False,
        )
        self.assertEqual(self.get()["attention"]["pending_users"], 0)

    def test_a_section_edited_after_the_assessment_is_flagged(self):
        stale = self.a_revision()
        stale.ai_section_content_hash = "not-the-current-hash"
        stale.save(update_fields=["ai_section_content_hash"])
        self.assertEqual(self.get()["attention"]["stale_assessments"], 1)

    def test_untagged_sections_are_counted_however_they_are_blank(self):
        ManualSection.objects.create(
            manual=self.manual, subtitle="4.0", content="x", tag="",
        )
        ManualSection.objects.create(
            manual=self.manual, subtitle="5.0", content="x", tag="UNTAGGED",
        )
        self.assertEqual(self.get()["attention"]["untagged_sections"], 2)

    # -- 2. activity -----------------------------------------------

    def test_the_series_covers_the_whole_window_including_empty_days(self):
        """A gap is information: a line drawn only through the days that
        have data would compress a fortnight of silence into one step."""
        activity = self.get()["activity"]
        self.assertEqual(len(activity["days"]), ACTIVITY_WINDOW_DAYS)
        self.assertEqual(activity["active_days"], 0)

    def test_a_decision_counts_on_the_day_it_was_made(self):
        """Not the day the revision arrived. The question is how much
        reviewing is happening, and a decision taken today about a
        month-old submission is today's work."""
        self.a_revision(status="approved", submitted_days_ago=20,
                        reviewed_days_ago=0)
        days = {d["date"]: d for d in self.get()["activity"]["days"]}
        today = timezone.localdate().isoformat()
        then = (timezone.localdate() - timedelta(days=20)).isoformat()
        self.assertEqual(days[today]["approved"], 1)
        self.assertEqual(days[today]["submitted"], 0)
        self.assertEqual(days[then]["submitted"], 1)
        self.assertEqual(days[then]["approved"], 0)

    def test_a_returned_revision_is_not_counted_as_approved(self):
        self.a_revision(status="rejected", reviewed_days_ago=0)
        totals = self.get()["activity"]["totals"]
        self.assertEqual(totals["rejected"], 1)
        self.assertEqual(totals["approved"], 0)

    def test_thin_history_does_not_get_a_chart(self):
        for day in range(ACTIVITY_CHART_MINIMUM_DAYS - 1):
            self.a_revision(submitted_days_ago=day)
        activity = self.get()["activity"]
        self.assertEqual(activity["active_days"], ACTIVITY_CHART_MINIMUM_DAYS - 1)
        self.assertFalse(activity["enough_for_chart"])

    def test_enough_separate_days_earns_the_chart(self):
        for day in range(ACTIVITY_CHART_MINIMUM_DAYS):
            self.a_revision(submitted_days_ago=day)
        self.assertTrue(self.get()["activity"]["enough_for_chart"])

    def test_many_revisions_on_one_day_are_still_one_day(self):
        """Volume is not history. Twenty submissions in an afternoon say
        nothing about a trend, and drawing them as one would be a spike
        with nothing to compare it to."""
        for _ in range(20):
            self.a_revision(submitted_days_ago=0)
        activity = self.get()["activity"]
        self.assertEqual(activity["active_days"], 1)
        self.assertFalse(activity["enough_for_chart"])
        self.assertEqual(activity["totals"]["submitted"], 20)

    def test_work_older_than_the_window_is_left_out(self):
        self.a_revision(submitted_days_ago=ACTIVITY_WINDOW_DAYS + 5)
        self.assertEqual(self.get()["activity"]["totals"]["submitted"], 0)

    # -- 3. by department ------------------------------------------

    def test_a_revision_belongs_to_the_document_s_department(self):
        """Not the submitter's. Someone can move between departments, and
        the thing being changed is the document."""
        hr_manual = Manual.objects.create(
            title="HRM 4.01", department=self.hr, uploaded_by=self.admin,
        )
        hr_section = ManualSection.objects.create(
            manual=hr_manual, subtitle="2.0", content="x", tag="POLICY",
        )
        self.a_revision(section=hr_section)

        rows = {r["department"]: r for r in self.get()["departments"]}
        self.assertEqual(rows["HRM"]["pending"], 1)
        self.assertNotIn("FAM", rows)

    def test_departments_with_pending_work_come_first(self):
        self.a_revision(status="approved", reviewed_days_ago=1)
        self.a_revision(status="approved", reviewed_days_ago=1)
        hr_manual = Manual.objects.create(
            title="HRM 4.01", department=self.hr, uploaded_by=self.admin,
        )
        hr_section = ManualSection.objects.create(
            manual=hr_manual, subtitle="2.0", content="x", tag="POLICY",
        )
        self.a_revision(section=hr_section)

        self.assertEqual(self.get()["departments"][0]["department"], "HRM")

    # -- 4. recent decisions ---------------------------------------

    def test_only_decided_revisions_are_listed_newest_first(self):
        self.a_revision()
        older = self.a_revision(status="approved", reviewed_days_ago=3)
        newer = self.a_revision(status="rejected", reviewed_days_ago=1)

        ids = [d["revision_id"] for d in self.get()["decisions"]]
        self.assertEqual(ids, [newer.id, older.id])

    def test_a_decision_against_the_assessment_is_marked(self):
        self.a_revision(status="approved", reviewed_days_ago=1,
                        ai_verdict="reject")
        self.assertIs(self.get()["decisions"][0]["agreed"], False)

    def test_a_decision_with_the_assessment_is_marked_agreed(self):
        self.a_revision(status="rejected", reviewed_days_ago=1,
                        ai_verdict="needs_revision")
        self.assertIs(self.get()["decisions"][0]["agreed"], True)

    def test_a_revision_with_no_stored_verdict_claims_no_agreement(self):
        """The legacy rows predate the pre-check. Calling that agreement
        would invent a verdict nobody gave."""
        self.a_revision(status="approved", reviewed_days_ago=1)
        row = self.get()["decisions"][0]
        self.assertIsNone(row["ai_verdict"])
        self.assertIsNone(row["agreed"])

    # -- 5. upcoming -----------------------------------------------

    def test_the_admin_sees_every_department_s_notices(self):
        """This is the desk they are posted from. Filtering by the admin's
        own department would hide what they themselves scheduled."""
        today = timezone.localdate()
        Announcement.objects.create(
            title="HR briefing", date=today + timedelta(days=3),
            department=self.hr, created_by=self.admin,
        )
        titles = [row["title"] for row in self.get()["upcoming"]]
        self.assertIn("HR briefing", titles)

    def test_banners_and_past_and_inactive_notices_are_not_upcoming(self):
        today = timezone.localdate()
        Announcement.objects.create(title="Banner", created_by=self.admin)
        Announcement.objects.create(
            title="Last week", date=today - timedelta(days=7),
            created_by=self.admin,
        )
        Announcement.objects.create(
            title="Withdrawn", date=today + timedelta(days=2),
            active=False, created_by=self.admin,
        )
        data = self.get()
        self.assertEqual(data["upcoming"], [])
        self.assertEqual(data["upcoming_total"], 0)
        self.assertEqual(data["system"]["banners_live"], 1)

    # -- 6. system -------------------------------------------------

    def test_system_counts_describe_what_is_actually_installed(self):
        system = self.get()["system"]
        self.assertEqual(system["manuals"], 1)
        self.assertEqual(system["sections"], 1)
        self.assertEqual(system["departments"], 2)
        self.assertEqual(system["staff"], 1)
        self.assertEqual(system["admins"], 1)
        # HRM has no manuals, which is why a staff member there sees nothing.
        self.assertEqual(system["empty_departments"], 1)

    def test_assessment_sources_separate_the_legacy_rows(self):
        self.a_revision(ai_source="staff_precheck")
        self.a_revision(ai_source="admin_legacy")
        self.a_revision(ai_source="none")
        self.assertEqual(
            self.get()["system"]["assessment_sources"],
            {"staff_precheck": 1, "admin_legacy": 1, "none": 1},
        )

    # -- the rule that matters most --------------------------------

    def test_the_dashboard_never_runs_the_pipeline(self):
        """Rule: an assessment is made once, at submission, and displayed
        thereafter. If the dashboard could reassess, the figure on screen
        would not be the one the reviewer acted on - so the pipeline is
        made to raise, and the dashboard must not touch it.
        """
        self.a_revision(status="approved", reviewed_days_ago=1,
                        ai_verdict="approve", ai_source="staff_precheck")
        with mock.patch(
            "ml.revision_pipeline.pipeline.assess_revision",
            side_effect=AssertionError("the dashboard re-ran an assessment"),
        ):
            data = self.get()
        self.assertEqual(data["decisions"][0]["ai_verdict"], "approve")
