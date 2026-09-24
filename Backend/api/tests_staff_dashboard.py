"""The staff dashboard: one request, and the announcement split.

The split is the part worth testing hardest. One model serves two widgets -
dated items are Upcoming, undated ones are the banner - so a bug there shows
up as a message appearing in the wrong place rather than as an error.
"""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Announcement, AnnouncementDismissal, CustomUser, Manual, ManualSection,
    ManualSeries, ManualSeriesOffice, Office, OfficeLink, Position,
    PositionAssignment, RecentlyOpened,
)


class StaffDashboardTests(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        vp = Office.objects.create(name="VP Office", abbreviation="VP", is_approving_level=True)
        self.finance = Office.objects.create(name="Finance Office", abbreviation="FIN", parent=vp)
        self.registry = Office.objects.create(name="Registry", abbreviation="REG", parent=vp)
        self.series = ManualSeries.objects.create(code="FAM", title="Finance", owning_office=vp)
        ManualSeriesOffice.objects.create(
            series=self.series, office=self.finance, relationship=OfficeLink.CONCURRING,
        )
        self.user = CustomUser.objects.create_user(
            username="staffer", password="pw", role="staff",
            is_approved=True,
        )
        position, _ = Position.objects.get_or_create(office=self.finance, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=self.user, position=position, starts_on=self.today)
        self.reviewer = CustomUser.objects.create_user(
            username="reviewer", password="pw", role="admin", is_approved=True,
        )
        self.manual = Manual.objects.create(title="FAM", series=self.series)
        self.section = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES", order=1,
            content="The Cashier shall release the cheque.",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def dashboard(self):
        response = self.client.get("/api/staff/dashboard/")
        self.assertEqual(response.status_code, 200)
        return response.data

    def an_announcement(self, title, *, date=None, active=True, office=None):
        return Announcement.objects.create(
            title=title, body="Body text.", date=date, active=active,
            office=office, created_by=self.reviewer,
        )

    # -- one request --------------------------------------------

    def test_every_widget_is_answered_by_the_one_call(self):
        data = self.dashboard()
        for key in ("proposals_awaiting", "proposals_mine", "recently_opened",
                    "announcement", "upcoming", "stats"):
            self.assertIn(key, data)

    def test_a_brand_new_account_gets_empty_everything_not_an_error(self):
        data = self.dashboard()
        self.assertEqual(data["proposals_awaiting"], 0)
        self.assertEqual(data["proposals_mine"], 0)
        self.assertEqual(data["recently_opened"], [])
        self.assertIsNone(data["announcement"])
        self.assertEqual(data["upcoming"], [])

    # -- recently opened ----------------------------------------

    def test_opening_a_manual_records_it(self):
        self.client.get(f"/api/manuals/{self.manual.id}/sections/")
        recent = self.dashboard()["recently_opened"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["manual"], "FAM")

    def test_re_opening_moves_it_up_rather_than_duplicating(self):
        self.client.get(f"/api/manuals/{self.manual.id}/sections/")
        self.client.get(f"/api/manuals/{self.manual.id}/sections/")
        self.assertEqual(len(self.dashboard()["recently_opened"]), 1)

    def test_the_list_is_capped(self):
        from api.views import RECENTLY_OPENED_LIMIT
        for index in range(RECENTLY_OPENED_LIMIT + 3):
            manual = Manual.objects.create(
                title=f"Manual {index}", series=self.series,
            )
            self.client.get(f"/api/manuals/{manual.id}/sections/")
        self.assertEqual(
            RecentlyOpened.objects.filter(user=self.user).count(),
            RECENTLY_OPENED_LIMIT,
        )
        self.assertEqual(len(self.dashboard()["recently_opened"]),
                         RECENTLY_OPENED_LIMIT)

    # -- announcements and upcoming: one model, two widgets -----

    def test_an_undated_item_is_the_banner(self):
        self.an_announcement("Workflow changed")
        data = self.dashboard()
        self.assertEqual(data["announcement"]["title"], "Workflow changed")
        self.assertEqual(data["upcoming"], [])

    def test_a_dated_item_is_upcoming_and_never_the_banner(self):
        self.an_announcement("Audit week",
                             date=self.today + datetime.timedelta(days=5))
        data = self.dashboard()
        self.assertIsNone(data["announcement"])
        self.assertEqual(len(data["upcoming"]), 1)
        self.assertEqual(data["upcoming"][0]["title"], "Audit week")

    def test_todays_item_is_marked(self):
        self.an_announcement("Refresher session", date=self.today)
        self.assertTrue(self.dashboard()["upcoming"][0]["is_today"])

    def test_past_items_drop_off(self):
        self.an_announcement("Last month's audit",
                             date=self.today - datetime.timedelta(days=30))
        self.assertEqual(self.dashboard()["upcoming"], [])

    def test_another_offices_announcement_is_not_shown(self):
        self.an_announcement("Registry only", office=self.registry)
        self.assertIsNone(self.dashboard()["announcement"])

    def test_my_offices_announcement_is_shown(self):
        self.an_announcement("Finance only", office=self.finance)
        self.assertEqual(self.dashboard()["announcement"]["title"], "Finance only")

    def test_an_announcement_for_everyone_is_shown(self):
        self.an_announcement("Everyone")
        self.assertEqual(self.dashboard()["announcement"]["title"], "Everyone")

    def test_an_inactive_announcement_is_hidden_without_deleting_it(self):
        self.an_announcement("Old news", active=False)
        self.assertIsNone(self.dashboard()["announcement"])
        self.assertEqual(Announcement.objects.count(), 1)

    def test_dismissing_the_banner_hides_it_for_that_user_only(self):
        announcement = self.an_announcement("Workflow changed")
        self.client.post(f"/api/staff/announcements/{announcement.id}/dismiss/")
        self.assertIsNone(self.dashboard()["announcement"])

        colleague = CustomUser.objects.create_user(
            username="colleague2", password="pw", role="staff",
            is_approved=True,
        )
        other = APIClient()
        other.force_authenticate(user=colleague)
        self.assertEqual(
            other.get("/api/staff/dashboard/").data["announcement"]["title"],
            "Workflow changed",
        )

    def test_a_new_announcement_appears_after_dismissing_an_old_one(self):
        """Dismissal is per announcement, not a single 'seen' flag."""
        first = self.an_announcement("First")
        self.client.post(f"/api/staff/announcements/{first.id}/dismiss/")
        first.active = False
        first.save(update_fields=["active"])

        self.an_announcement("Second")
        self.assertEqual(self.dashboard()["announcement"]["title"], "Second")
        self.assertEqual(AnnouncementDismissal.objects.count(), 1)

    # -- at a glance --------------------------------------------

    def test_the_stats_describe_this_user(self):
        Manual.objects.create(title="Registry Manual")
        stats = self.dashboard()["stats"]
        self.assertEqual(stats["manuals_total"], 2)
        self.assertEqual(stats["manuals_mine"], 1)
