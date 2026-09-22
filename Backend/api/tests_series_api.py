"""Entering the organisation: series, documents and their office links.

The tests that matter most are about the override, because that is where
the design chose the blunt option deliberately. Replace-all is only safe
if its cost is visible, so the endpoint that makes a series-level change
has to say which documents did not receive it.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import (
    CustomUser, Department, Manual, ManualOffice, ManualSeries,
    ManualSeriesOffice, Office, OfficeLink,
)
from api.views import issue_reauth_token

PASSWORD = "correct-horse-battery"


class SeriesApiTests(TestCase):

    def setUp(self):
        self.department = Department.objects.create(name="FAM")
        self.admin = CustomUser.objects.create_user(
            username="sysadmin", password=PASSWORD, role="admin",
            system_role=CustomUser.SYSTEM_ADMIN, is_approved=True,
        )

        self.president = Office.objects.create(
            name="Office of the President", is_approving_level=True,
        )
        self.vp = Office.objects.create(
            name="VP for Administration", parent=self.president,
            is_approving_level=True,
        )
        self.accounting = Office.objects.create(
            name="Accounting Services Office", parent=self.vp,
        )
        self.budget = Office.objects.create(name="Budget Office", parent=self.vp)
        self.registrar = Office.objects.create(name="Registrar", parent=self.vp)

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def token(self):
        return issue_reauth_token(self.admin)

    def confirmed(self, method, path, body=None):
        return getattr(self.client, method)(
            path, body or {}, format="json",
            HTTP_X_REAUTH_TOKEN=self.token(),
        )

    def a_series(self, code="FAM", owner=None):
        series = ManualSeries.objects.create(
            code=code, title="Finance and Administration Manual",
            owning_office=owner or self.vp,
        )
        return series

    def a_document(self, title="FAM 6.02", series=None):
        return Manual.objects.create(
            title=title, department=self.department, series=series,
        )

    # -- access ----------------------------------------------------

    def test_only_the_system_admin_reaches_these(self):
        other = CustomUser.objects.create_user(
            username="ordinary", password=PASSWORD, role="staff",
            system_role=CustomUser.USER, is_approved=True,
        )
        client = APIClient()
        client.force_authenticate(user=other)
        for path in ("/api/org/series/", "/api/org/documents/"):
            self.assertEqual(client.get(path).status_code, 403, path)

    # -- creating and naming ---------------------------------------

    def test_creating_a_series_needs_no_password(self):
        response = self.client.post(
            "/api/org/series/",
            {"code": "FAM", "title": "Finance and Administration Manual"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data["owning_office"])

    def test_a_series_code_is_unique_whatever_its_case(self):
        self.a_series(code="FAM")
        response = self.client.post(
            "/api/org/series/", {"code": "fam", "title": "Another"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_renaming_a_series_needs_no_password(self):
        series = self.a_series()
        response = self.client.patch(
            f"/api/org/series/{series.id}/",
            {"title": "Finance Manual"}, format="json",
        )
        self.assertEqual(response.status_code, 200)

    # -- what changes authority ------------------------------------

    def test_changing_the_owner_needs_a_password(self):
        series = self.a_series()
        response = self.client.patch(
            f"/api/org/series/{series.id}/",
            {"owning_office_id": self.president.id}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        series.refresh_from_db()
        self.assertEqual(series.owning_office, self.vp)

    def test_the_owner_must_be_an_approving_level_office(self):
        series = self.a_series()
        response = self.confirmed(
            "patch", f"/api/org/series/{series.id}/",
            {"owning_office_id": self.accounting.id},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("approving-level", response.data["error"])

    def test_setting_office_links_needs_a_password(self):
        series = self.a_series()
        response = self.client.put(
            f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": self.accounting.id,
                          "relationship": "concurring"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    # -- office links, set as a whole ------------------------------

    def test_links_are_replaced_as_a_set(self):
        """A PUT is the whole set. An office left out is removed, because
        the set is the thing being edited."""
        series = self.a_series()
        self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [
                {"office_id": self.accounting.id, "relationship": "concurring"},
                {"office_id": self.registrar.id, "relationship": "reader"},
            ]},
        )
        self.assertEqual(
            ManualSeriesOffice.objects.filter(series=series).count(), 2
        )

        self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [
                {"office_id": self.accounting.id, "relationship": "concurring"},
            ]},
        )
        remaining = ManualSeriesOffice.objects.filter(series=series)
        self.assertEqual([l.office for l in remaining], [self.accounting])

    def test_an_offices_relationship_can_be_changed_in_place(self):
        series = self.a_series()
        self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": self.accounting.id,
                          "relationship": "concurring"}]},
        )
        self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": self.accounting.id,
                          "relationship": "reader"}]},
        )
        link = ManualSeriesOffice.objects.get(series=series)
        self.assertEqual(link.relationship, OfficeLink.READER)

    def test_an_unknown_relationship_is_refused(self):
        series = self.a_series()
        response = self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": self.accounting.id,
                          "relationship": "approves"}]},
        )
        self.assertEqual(response.status_code, 400)

    def test_an_unknown_office_is_refused_before_anything_is_written(self):
        series = self.a_series()
        self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": self.accounting.id,
                          "relationship": "concurring"}]},
        )
        response = self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": 9999, "relationship": "reader"}]},
        )
        self.assertEqual(response.status_code, 400)
        # The earlier set survived: a refused call changes nothing.
        self.assertEqual(
            ManualSeriesOffice.objects.filter(series=series).count(), 1
        )

    # -- the cost of replace-all, reported ------------------------

    def test_a_series_change_says_which_documents_it_did_not_reach(self):
        """The whole reason replace-all is acceptable. The admin makes a
        change here and is told, at that moment, which documents ignored
        it."""
        series = self.a_series()
        inheriting = self.a_document("FAM 6.02", series)
        overriding = self.a_document("FAM 6.03", series)
        overriding.offices_overridden = True
        overriding.save()
        ManualOffice.objects.create(
            manual=overriding, office=self.budget,
            relationship=OfficeLink.CONCURRING,
        )

        response = self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": self.accounting.id,
                          "relationship": "concurring"}]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [d["title"] for d in response.data["did_not_reach"]], ["FAM 6.03"],
        )
        self.assertEqual(inheriting.concurring_offices(), [self.accounting])
        self.assertEqual(overriding.concurring_offices(), [self.budget])

    def test_the_series_list_flags_overriding_documents_too(self):
        series = self.a_series()
        document = self.a_document("FAM 6.02", series)
        document.offices_overridden = True
        document.save()

        row = self.client.get("/api/org/series/").data["series"][0]
        self.assertEqual(
            [d["title"] for d in row["overriding_documents"]], ["FAM 6.02"],
        )

    # -- documents -------------------------------------------------

    def test_the_unassigned_list_holds_the_documents_nobody_owns(self):
        self.a_document("SDM 3.01")
        series = self.a_series()
        self.a_document("FAM 6.02", series)

        data = self.client.get("/api/org/documents/?unassigned=true").data
        self.assertEqual([d["title"] for d in data["documents"]], ["SDM 3.01"])
        self.assertEqual(data["unassigned_total"], 1)

    def test_putting_a_document_in_a_series_needs_a_password(self):
        series = self.a_series()
        document = self.a_document("FAM 6.02")
        response = self.client.patch(
            f"/api/org/documents/{document.id}/",
            {"series_id": series.id}, format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_a_document_in_a_series_inherits_everything(self):
        series = self.a_series()
        self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": self.accounting.id,
                          "relationship": "concurring"}]},
        )
        document = self.a_document("FAM 6.02")
        response = self.confirmed(
            "patch", f"/api/org/documents/{document.id}/",
            {"series_id": series.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["owner_is_inherited"])
        self.assertEqual(
            response.data["effective_owner"]["name"], "VP for Administration"
        )
        self.assertEqual(
            [o["name"] for o in response.data["concurring"]],
            ["Accounting Services Office"],
        )
        self.assertEqual(
            [o["name"] for o in response.data["approval_route"]],
            ["VP for Administration", "Office of the President"],
        )

    def test_a_document_override_must_still_be_an_approving_office(self):
        """Asserts the message, not just the status. The first version
        checked only for 400 and passed on an unrelated validation error,
        which is the way a test quietly stops testing anything."""
        series = self.a_series()
        document = self.a_document("FAM 6.02", series)
        response = self.confirmed(
            "patch", f"/api/org/documents/{document.id}/",
            {"owning_office_id": self.accounting.id},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("approving-level", response.data["error"])
        document.refresh_from_db()
        self.assertIsNone(document.owning_office_id)

    def test_overriding_a_documents_offices_sets_the_flag(self):
        series = self.a_series()
        document = self.a_document("FAM 6.02", series)

        response = self.confirmed(
            "put", f"/api/org/documents/{document.id}/offices/",
            {"offices": [{"office_id": self.budget.id,
                          "relationship": "concurring"}]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["offices_overridden"])
        document.refresh_from_db()
        self.assertEqual(document.concurring_offices(), [self.budget])

    def test_handing_a_document_back_to_its_series_clears_its_rows(self):
        """Leaving them behind would mean the next person to switch the
        override on silently gets a set somebody chose months ago."""
        series = self.a_series()
        self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": self.accounting.id,
                          "relationship": "concurring"}]},
        )
        document = self.a_document("FAM 6.02", series)
        self.confirmed(
            "put", f"/api/org/documents/{document.id}/offices/",
            {"offices": [{"office_id": self.budget.id,
                          "relationship": "concurring"}]},
        )

        response = self.confirmed(
            "put", f"/api/org/documents/{document.id}/offices/",
            {"inherit": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["offices_overridden"])
        self.assertEqual(ManualOffice.objects.filter(manual=document).count(), 0)
        document.refresh_from_db()
        self.assertEqual(document.concurring_offices(), [self.accounting])

    def test_an_orphan_document_cannot_be_left_with_no_offices(self):
        """With no series to fall back on, an empty set means nobody can
        ever change the document - which is a mistake, not a choice."""
        document = self.a_document("SDM 3.01")
        response = self.confirmed(
            "put", f"/api/org/documents/{document.id}/offices/",
            {"offices": []},
        )
        self.assertEqual(response.status_code, 400)

    def test_a_document_with_no_concurring_office_is_flagged(self):
        series = self.a_series()
        self.confirmed(
            "put", f"/api/org/series/{series.id}/offices/",
            {"offices": [{"office_id": self.registrar.id,
                          "relationship": "reader"}]},
        )
        document = self.a_document("FAM 6.02", series)
        row = self.client.get(f"/api/org/documents/{document.id}/").data
        self.assertFalse(row["can_be_proposed_against"])
