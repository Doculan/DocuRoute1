"""The staff dashboard: one request for the landing page.

Announcements and deadlines left it in Phase 3A: the banner rows and the
Deadlines panel read their own endpoints (tests_notices.py).
"""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    CustomUser, Manual, ManualSection,
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

    # -- one request --------------------------------------------

    def test_every_widget_is_answered_by_the_one_call(self):
        data = self.dashboard()
        for key in ("proposals_awaiting", "proposals_mine", "recently_opened", "stats"):
            self.assertIn(key, data)

    def test_a_brand_new_account_gets_empty_everything_not_an_error(self):
        data = self.dashboard()
        self.assertEqual(data["proposals_awaiting"], 0)
        self.assertEqual(data["proposals_mine"], 0)
        self.assertEqual(data["recently_opened"], [])

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

    # -- at a glance --------------------------------------------

    def test_the_stats_describe_this_user(self):
        Manual.objects.create(title="Registry Manual")
        stats = self.dashboard()["stats"]
        self.assertEqual(stats["manuals_total"], 2)
        self.assertEqual(stats["manuals_mine"], 1)
