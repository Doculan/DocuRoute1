"""The staff portal's section search: sections across every document the
person's offices reach."""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    CustomUser, Manual, ManualSection, ManualSeries, ManualSeriesOffice,
    Office, OfficeLink, Position, PositionAssignment,
)


class StaffSectionSearchTests(TestCase):
    """Sections across manuals - the thing that justifies the tab."""

    def setUp(self):
        vp = Office.objects.create(name="VP Office", abbreviation="VP", is_approving_level=True)
        finance = Office.objects.create(name="Finance Office", abbreviation="FIN", parent=vp)
        series = ManualSeries.objects.create(code="FIN", title="Finance", owning_office=vp)
        ManualSeriesOffice.objects.create(
            series=series, office=finance, relationship=OfficeLink.CONCURRING,
        )
        self.user = CustomUser.objects.create_user(
            username="staffer", password="pw", role="staff",
            is_approved=True,
        )
        position, _ = Position.objects.get_or_create(office=finance, kind=Position.ENCODER)
        PositionAssignment.objects.create(
            user=self.user, position=position, starts_on=timezone.localdate(),
        )
        self.fam = Manual.objects.create(title="FAM", series=series)
        self.hrm = Manual.objects.create(title="HRM", series=series)
        self.other = Manual.objects.create(title="Registry Manual")

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

    def test_it_spans_every_manual_my_offices_reach(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        manuals = {row["manual"] for row in response.data["results"]}
        self.assertEqual(manuals, {"FAM", "HRM"})

    def test_a_document_my_offices_do_not_reach_is_not_visible(self):
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

    def test_a_user_with_no_office_is_told_so(self):
        loner = CustomUser.objects.create_user(
            username="unassigned", password="pw", role="staff", is_approved=True,
        )
        client = APIClient()
        client.force_authenticate(user=loner)
        self.assertEqual(client.get("/api/staff/sections/").status_code, 403)
