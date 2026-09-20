"""Announcement management — the half the staff side was waiting on.

The rule under test throughout: one model, two presentations. A dated item
is Upcoming and an undated one is the banner, and what the admin creates
here must land in the place the admin was told it would.
"""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import Announcement, CustomUser, Department
from api.views import issue_reauth_token


class AdminAnnouncementTests(TestCase):

    def setUp(self):
        self.cas = Department.objects.create(name="CAS")
        self.sdm = Department.objects.create(name="SDM")
        self.admin = CustomUser.objects.create_user(
            username="admin", password="pw", role="admin", is_approved=True,
        )
        # Reach counts should only ever count staff who can actually sign in.
        self.staff_cas = CustomUser.objects.create_user(
            username="cas1", password="pw", role="staff",
            is_approved=True, department=self.cas,
        )
        CustomUser.objects.create_user(
            username="cas2", password="pw", role="staff",
            is_approved=True, department=self.cas,
        )
        CustomUser.objects.create_user(
            username="sdm1", password="pw", role="staff",
            is_approved=True, department=self.sdm,
        )
        CustomUser.objects.create_user(
            username="waiting", password="pw", role="staff",
            is_approved=False, department=self.cas,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.today = timezone.localdate()

    def post(self, **fields):
        body = {"title": "A notice", "body": "", "date": "",
                "department_id": "", "active": True}
        body.update(fields)
        return self.client.post("/api/admin/announcements/", body, format="json")

    # -- access -------------------------------------------------

    def test_staff_cannot_manage_announcements(self):
        staff = APIClient()
        staff.force_authenticate(user=self.staff_cas)
        self.assertEqual(staff.get("/api/admin/announcements/").status_code, 403)
        self.assertEqual(
            staff.post("/api/admin/announcements/", {"title": "Mine"},
                       format="json").status_code,
            403,
        )

    # -- one model, two presentations ---------------------------

    def test_no_date_is_a_banner(self):
        response = self.post(title="Workflow changed")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["shows_as"], "banner")
        self.assertIsNone(response.data["date"])

    def test_a_date_makes_it_upcoming(self):
        response = self.post(title="Audit week", date="2026-10-06")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["shows_as"], "upcoming")
        self.assertEqual(str(response.data["date"]), "2026-10-06")

    def test_clearing_the_date_turns_upcoming_back_into_a_banner(self):
        created = self.post(title="Audit week", date="2026-10-06")
        response = self.client.patch(
            f"/api/admin/announcements/{created.data['id']}/",
            {"date": ""}, format="json",
        )
        self.assertEqual(response.data["shows_as"], "banner")

    def test_a_bad_date_is_refused_with_the_field_named(self):
        response = self.post(title="Audit", date="next Tuesday")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["field"], "date")

    def test_a_title_is_required(self):
        response = self.post(title="   ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["field"], "title")

    # -- reach --------------------------------------------------

    def test_reach_counts_approved_staff_in_the_target_department(self):
        response = self.post(title="For CAS", department_id=self.cas.id)
        # two approved in CAS; the unapproved one cannot sign in to read it
        self.assertEqual(response.data["reach"], 2)
        self.assertEqual(response.data["department"], "CAS")

    def test_reach_for_everyone_counts_every_approved_staff_member(self):
        response = self.post(title="For all")
        self.assertEqual(response.data["reach"], 3)
        self.assertIsNone(response.data["department"])

    # -- the list -----------------------------------------------

    def test_inactive_items_sort_below_active_ones(self):
        self.post(title="Old news", active=False)
        self.post(title="Current")
        titles = [r["title"] for r in
                  self.client.get("/api/admin/announcements/").data]
        self.assertEqual(titles[0], "Current")

    def test_deactivating_hides_it_from_staff_without_deleting(self):
        created = self.post(title="Workflow changed")
        self.client.patch(
            f"/api/admin/announcements/{created.data['id']}/",
            {"active": False}, format="json",
        )
        self.assertEqual(Announcement.objects.count(), 1)

        staff = APIClient()
        staff.force_authenticate(user=self.staff_cas)
        self.assertIsNone(staff.get("/api/staff/dashboard/").data["announcement"])

    def test_deleting_removes_it(self):
        created = self.post(title="Mistyped")
        response = self.client.delete(
            f"/api/admin/announcements/{created.data['id']}/",
            HTTP_X_REAUTH_TOKEN=issue_reauth_token(self.admin),
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Announcement.objects.count(), 0)

    def test_deleting_without_confirming_a_password_is_refused(self):
        """Deleting destroys the record of what was posted. Deactivating,
        which keeps it, is the one-click move and stays that way."""
        created = self.post(title="Mistyped")
        response = self.client.delete(
            f"/api/admin/announcements/{created.data['id']}/"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Announcement.objects.count(), 1)

    # -- it actually reaches the staff dashboard ----------------

    def test_a_banner_posted_here_appears_there(self):
        self.post(title="Workflow changed", body="Read this.")
        staff = APIClient()
        staff.force_authenticate(user=self.staff_cas)
        banner = staff.get("/api/staff/dashboard/").data["announcement"]
        self.assertEqual(banner["title"], "Workflow changed")

    def test_a_dated_item_posted_here_appears_under_upcoming(self):
        when = self.today + datetime.timedelta(days=3)
        self.post(title="Audit week", date=when.isoformat())
        staff = APIClient()
        staff.force_authenticate(user=self.staff_cas)
        data = staff.get("/api/staff/dashboard/").data
        self.assertIsNone(data["announcement"])
        self.assertEqual(data["upcoming"][0]["title"], "Audit week")

    def test_targeting_a_department_keeps_it_from_the_others(self):
        self.post(title="CAS only", department_id=self.cas.id)
        sdm_staff = CustomUser.objects.get(username="sdm1")
        other = APIClient()
        other.force_authenticate(user=sdm_staff)
        self.assertIsNone(other.get("/api/staff/dashboard/").data["announcement"])

        mine = APIClient()
        mine.force_authenticate(user=self.staff_cas)
        self.assertEqual(
            mine.get("/api/staff/dashboard/").data["announcement"]["title"],
            "CAS only",
        )

    def test_the_admin_can_see_how_many_people_dismissed_a_banner(self):
        created = self.post(title="Workflow changed")
        staff = APIClient()
        staff.force_authenticate(user=self.staff_cas)
        staff.post(f"/api/staff/announcements/{created.data['id']}/dismiss/")

        row = self.client.get(
            f"/api/admin/announcements/{created.data['id']}/"
        ).data
        self.assertEqual(row["dismissals"], 1)
