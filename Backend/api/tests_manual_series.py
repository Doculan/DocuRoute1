"""Series, inheritance, and the offices screen.

The inheritance tests are the ones that matter later. Four separate parts
of the system will ask "who concurs on this document" - the concurrence
list, the notifications, the frozen participant list and the audit trail -
and they all read the same helpers. If those disagree with each other, the
symptom appears three phases from here as a request that went to the wrong
office.
"""

import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    CustomUser, Department, Manual, ManualOffice, ManualSeries,
    ManualSeriesOffice, Office, OfficeLink, Position, PositionAssignment,
)
from api.views import holds_current_qms_position, issue_reauth_token

PASSWORD = "correct-horse-battery"


class SeriesFixture(TestCase):
    """The shape the university actually has: a president over a VP, and
    working offices under that."""

    def setUp(self):
        self.department = Department.objects.create(name="FAM")

        self.president = Office.objects.create(
            name="Office of the President", abbreviation="OP",
            is_approving_level=True,
        )
        self.vp = Office.objects.create(
            name="VP for Administration", abbreviation="VPA",
            parent=self.president, is_approving_level=True,
        )
        self.accounting = Office.objects.create(
            name="Accounting Services Office", abbreviation="ASO", parent=self.vp,
        )
        self.budget = Office.objects.create(
            name="Budget Office", abbreviation="BO", parent=self.vp,
        )
        self.registrar = Office.objects.create(
            name="Registrar", abbreviation="REG", parent=self.vp,
        )

        self.series = ManualSeries.objects.create(
            code="FAM", title="Finance and Administration Manual",
            owning_office=self.vp,
        )
        ManualSeriesOffice.objects.create(
            series=self.series, office=self.accounting,
            relationship=OfficeLink.CONCURRING,
        )
        ManualSeriesOffice.objects.create(
            series=self.series, office=self.registrar,
            relationship=OfficeLink.READER,
        )

        self.document = Manual.objects.create(
            title="FAM 6.02", department=self.department, series=self.series,
        )


class InheritanceTests(SeriesFixture):

    def test_a_document_inherits_its_owner_from_the_series(self):
        self.assertEqual(self.document.effective_owner, self.vp)
        self.assertTrue(self.document.owner_is_inherited)

    def test_an_override_wins_and_is_reported_as_not_inherited(self):
        self.document.owning_office = self.president
        self.document.save()
        self.assertEqual(self.document.effective_owner, self.president)
        self.assertFalse(self.document.owner_is_inherited)

    def test_an_override_owner_must_still_be_an_approving_level_office(self):
        """The override is held to the same rule as the series it
        overrides - otherwise the escape hatch is a way around it."""
        self.document.owning_office = self.accounting
        with self.assertRaises(ValidationError):
            self.document.full_clean()

    def test_a_series_owner_must_be_an_approving_level_office(self):
        self.series.owning_office = self.accounting
        with self.assertRaises(ValidationError):
            self.series.full_clean()

    def test_a_document_with_no_series_and_no_owner_is_unassigned(self):
        """Where all nineteen existing documents start."""
        loose = Manual.objects.create(title="SDM 3.01", department=self.department)
        self.assertTrue(loose.is_unassigned)
        self.assertIsNone(loose.effective_owner)
        self.assertEqual(loose.effective_office_links(), [])
        self.assertEqual(loose.approval_route(), [])

    def test_office_links_are_inherited_whole(self):
        self.assertEqual(self.document.concurring_offices(), [self.accounting])
        self.assertEqual(self.document.reader_offices(), [self.registrar])

    def test_an_override_replaces_the_series_set_rather_than_adding_to_it(self):
        """The decision this design rests on. The document names Budget
        only, so Accounting and Registrar stop applying to it - they are
        not merged in."""
        self.document.offices_overridden = True
        self.document.save()
        ManualOffice.objects.create(
            manual=self.document, office=self.budget,
            relationship=OfficeLink.CONCURRING,
        )
        self.assertEqual(self.document.concurring_offices(), [self.budget])
        self.assertEqual(self.document.reader_offices(), [])

    def test_the_override_rows_are_ignored_until_the_flag_is_set(self):
        """So that copying the series' links in, as a starting point, does
        not change anything until the admin says so."""
        ManualOffice.objects.create(
            manual=self.document, office=self.budget,
            relationship=OfficeLink.CONCURRING,
        )
        self.assertEqual(self.document.concurring_offices(), [self.accounting])

    def test_an_overriding_document_does_not_receive_a_later_series_change(self):
        """The known cost of replace-all, asserted so it stays known. The
        series screen is what makes it visible."""
        self.document.offices_overridden = True
        self.document.save()
        ManualOffice.objects.create(
            manual=self.document, office=self.budget,
            relationship=OfficeLink.CONCURRING,
        )
        ManualSeriesOffice.objects.create(
            series=self.series, office=self.budget,
            relationship=OfficeLink.READER,
        )
        inheriting = Manual.objects.create(
            title="FAM 6.03", department=self.department, series=self.series,
        )
        self.assertIn(self.budget, inheriting.reader_offices())
        self.assertNotIn(self.budget, self.document.reader_offices())

    def test_one_relationship_per_series_and_office(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ManualSeriesOffice.objects.create(
                    series=self.series, office=self.accounting,
                    relationship=OfficeLink.READER,
                )

    def test_a_document_with_no_concurring_office_cannot_be_proposed_against(self):
        ManualSeriesOffice.objects.filter(
            series=self.series, relationship=OfficeLink.CONCURRING,
        ).delete()
        self.assertFalse(self.document.can_be_proposed_against())


class ApprovalRouteTests(SeriesFixture):

    def test_the_route_runs_from_the_owner_up_through_approving_levels(self):
        self.assertEqual(
            self.document.approval_route(), [self.vp, self.president],
        )

    def test_ordinary_offices_above_the_owner_are_not_in_the_route(self):
        """Only approving levels sign. A non-approving office in the chain
        is skipped rather than ending the walk."""
        middle = Office.objects.create(name="Admin Cluster", parent=self.president)
        self.vp.parent = middle
        self.vp.save()
        self.document.refresh_from_db()
        self.assertEqual(
            self.document.approval_route(), [self.vp, self.president],
        )

    def test_stopping_at_the_owner_is_inherited_from_the_series(self):
        self.series.approval_stops_at_owner = True
        self.series.save()
        self.document.refresh_from_db()
        self.assertEqual(self.document.approval_route(), [self.vp])

    def test_a_document_can_override_the_series_in_either_direction(self):
        """Three states, not two. A document that continues upward under a
        series that stops has to be expressible, or the override only
        works one way."""
        self.series.approval_stops_at_owner = True
        self.series.save()
        self.document.approval_stops_at_owner = False
        self.document.save()
        self.assertEqual(
            self.document.approval_route(), [self.vp, self.president],
        )

    def test_null_means_inherit_not_false(self):
        """The migration converts every 1a default to null for exactly
        this reason: False is a decision, null is the absence of one."""
        self.assertIsNone(self.document.approval_stops_at_owner)
        self.series.approval_stops_at_owner = True
        self.series.save()
        self.document.refresh_from_db()
        self.assertTrue(self.document.stops_at_owner)


class OfficeApiTests(TestCase):

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username="sysadmin", password=PASSWORD, role="admin",
            system_role=CustomUser.SYSTEM_ADMIN, is_approved=True,
        )
        self.ordinary = CustomUser.objects.create_user(
            username="ordinary", password=PASSWORD, role="staff",
            system_role=CustomUser.USER, is_approved=True,
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
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def token(self):
        return issue_reauth_token(self.admin)

    def confirmed(self, method, path, body=None):
        return getattr(self.client, method)(
            path, body or {}, format="json",
            HTTP_X_REAUTH_TOKEN=self.token(),
        )

    # -- access ----------------------------------------------------

    def test_only_the_system_admin_reaches_the_organisation(self):
        other = APIClient()
        other.force_authenticate(user=self.ordinary)
        self.assertEqual(other.get("/api/org/offices/").status_code, 403)

    def test_the_v3_admin_role_alone_is_not_enough(self):
        """Read off `system_role`, not `role`. Someone left as a v3 admin
        without being made a system admin configures nothing."""
        legacy = CustomUser.objects.create_user(
            username="legacy-admin", password=PASSWORD, role="admin",
            system_role=CustomUser.USER, is_approved=True,
        )
        client = APIClient()
        client.force_authenticate(user=legacy)
        self.assertEqual(client.get("/api/org/offices/").status_code, 403)

    # -- reading and creating --------------------------------------

    def test_the_tree_comes_back_flat_with_parents(self):
        rows = self.client.get("/api/org/offices/").data["offices"]
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(
            by_name["Accounting Services Office"]["parent_id"], self.vp.id
        )
        self.assertIsNone(by_name["Office of the President"]["parent_id"])

    def test_creating_an_office_needs_no_password(self):
        """Adding is not destructive, and a prompt on routine work is how
        people learn to type the password without reading it."""
        response = self.client.post(
            "/api/org/offices/",
            {"name": "Budget Office", "parent_id": self.vp.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_an_office_cannot_be_created_inside_its_own_hierarchy(self):
        response = self.client.patch(
            f"/api/org/offices/{self.president.id}/",
            {"parent_id": self.accounting.id}, format="json",
            HTTP_X_REAUTH_TOKEN=self.token(),
        )
        self.assertEqual(response.status_code, 400)
        self.president.refresh_from_db()
        self.assertIsNone(self.president.parent_id)

    # -- what needs a password, and what does not ------------------

    def test_renaming_needs_no_password(self):
        response = self.client.patch(
            f"/api/org/offices/{self.accounting.id}/",
            {"name": "Accounting Office"}, format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_moving_needs_one(self):
        """A move changes the approval route of every document the office
        owns, which is not a rename."""
        response = self.client.patch(
            f"/api/org/offices/{self.accounting.id}/",
            {"parent_id": self.president.id}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_required")
        self.accounting.refresh_from_db()
        self.assertEqual(self.accounting.parent_id, self.vp.id)

    def test_deactivating_needs_one(self):
        response = self.client.post(
            f"/api/org/offices/{self.accounting.id}/deactivate/"
        )
        self.assertEqual(response.status_code, 403)

    # -- deactivating ----------------------------------------------

    def test_there_is_no_way_to_delete_an_office(self):
        self.assertEqual(
            self.client.delete(f"/api/org/offices/{self.accounting.id}/").status_code,
            405,
        )

    def test_deactivating_keeps_the_office(self):
        response = self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/deactivate/"
        )
        self.assertEqual(response.status_code, 200)
        self.accounting.refresh_from_db()
        self.assertFalse(self.accounting.is_active)
        self.assertTrue(Office.objects.filter(pk=self.accounting.pk).exists())

    def test_an_office_with_active_children_cannot_be_deactivated(self):
        """Retiring it would leave the units under it orphaned in the tree
        with no sign of why."""
        response = self.confirmed(
            "post", f"/api/org/offices/{self.vp.id}/deactivate/"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["reason"], "has_children")
        self.vp.refresh_from_db()
        self.assertTrue(self.vp.is_active)

    def test_inactive_offices_are_hidden_unless_asked_for(self):
        self.confirmed("post", f"/api/org/offices/{self.accounting.id}/deactivate/")
        visible = self.client.get("/api/org/offices/").data
        self.assertNotIn(
            self.accounting.id, [o["id"] for o in visible["offices"]]
        )
        self.assertEqual(visible["inactive_total"], 1)

        everything = self.client.get(
            "/api/org/offices/?include_inactive=true"
        ).data["offices"]
        self.assertIn(self.accounting.id, [o["id"] for o in everything])

    # -- merging ---------------------------------------------------

    def test_the_preview_says_what_would_move(self):
        series = ManualSeries.objects.create(code="FAM", title="Finance")
        ManualSeriesOffice.objects.create(
            series=series, office=self.accounting,
            relationship=OfficeLink.CONCURRING,
        )
        budget = Office.objects.create(name="Budget Office", parent=self.vp)

        preview = self.client.get(
            f"/api/org/offices/{self.accounting.id}/merge/?into={budget.id}"
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data["moves"]["series_links"], 1)
        # A preview must not have moved anything.
        self.assertEqual(
            ManualSeriesOffice.objects.get(series=series).office, self.accounting,
        )

    def test_merging_moves_the_work_and_keeps_the_office(self):
        series = ManualSeries.objects.create(
            code="FAM", title="Finance", owning_office=self.vp,
        )
        ManualSeriesOffice.objects.create(
            series=series, office=self.accounting,
            relationship=OfficeLink.CONCURRING,
        )
        budget = Office.objects.create(name="Budget Office", parent=self.vp)

        response = self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        self.assertEqual(response.status_code, 200)

        self.assertEqual(ManualSeriesOffice.objects.get(series=series).office, budget)
        self.accounting.refresh_from_db()
        self.assertTrue(Office.objects.filter(pk=self.accounting.pk).exists())
        self.assertEqual(self.accounting.merged_into, budget)
        self.assertFalse(self.accounting.is_active)

    def test_merging_needs_a_password(self):
        budget = Office.objects.create(name="Budget Office", parent=self.vp)
        response = self.client.post(
            f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id}, format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_a_duplicate_link_is_dropped_rather_than_refused(self):
        """Both offices concur on the same series. The surviving office's
        relationship is the one that keeps applying - re-pointing the
        other would break the unique constraint and fail the whole merge."""
        series = ManualSeries.objects.create(code="FAM", title="Finance")
        ManualSeriesOffice.objects.create(
            series=series, office=self.accounting,
            relationship=OfficeLink.CONCURRING,
        )
        budget = Office.objects.create(name="Budget Office", parent=self.vp)
        ManualSeriesOffice.objects.create(
            series=series, office=budget, relationship=OfficeLink.READER,
        )

        response = self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        self.assertEqual(response.status_code, 200)
        link = ManualSeriesOffice.objects.get(series=series)
        self.assertEqual(link.office, budget)
        self.assertEqual(link.relationship, OfficeLink.READER)

    def test_an_office_cannot_be_merged_into_one_beneath_it(self):
        """That would put the surviving office inside the one being
        retired, and reparenting the children would then make a cycle."""
        response = self.confirmed(
            "post", f"/api/org/offices/{self.vp.id}/merge/",
            {"into": self.accounting.id},
        )
        self.assertEqual(response.status_code, 400)

    def test_merging_moves_the_children_across(self):
        budget = Office.objects.create(name="Budget Office", parent=self.president)
        child = Office.objects.create(name="Cashier", parent=self.accounting)

        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        child.refresh_from_db()
        self.assertEqual(child.parent, budget)

    def test_a_merged_office_is_not_reactivated_by_mistake(self):
        budget = Office.objects.create(name="Budget Office", parent=self.vp)
        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        response = self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/reactivate/"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["reason"], "merged")

    def test_a_conflicting_position_is_deactivated_not_duplicated(self):
        """Both offices have a Head. The retired office's position stays,
        deactivated, so its past assignments still read correctly."""
        budget = Office.objects.create(name="Budget Office", parent=self.vp)
        theirs = Position.objects.create(office=self.accounting, kind=Position.HEAD)
        Position.objects.create(office=budget, kind=Position.HEAD)

        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        theirs.refresh_from_db()
        self.assertEqual(theirs.office, self.accounting)
        self.assertFalse(theirs.is_active)

    # -- two offices, both with someone in post --------------------
    #
    # The case the dated assignment was built for. A position that cannot
    # move across is retired, and anyone holding it has that assignment
    # **ended with a date**. Left open, it is a standing claim that they
    # still hold a post at an office that no longer operates - and every
    # reader asking "who holds this now" would believe it.

    def _two_offices_with_heads(self):
        today = timezone.localdate()
        budget = Office.objects.create(name="Budget Office", parent=self.vp)

        theirs = Position.objects.create(office=self.accounting, kind=Position.HEAD)
        survivor = Position.objects.create(office=budget, kind=Position.HEAD)

        leaving = CustomUser.objects.create_user(username="leaving", password="pw")
        staying = CustomUser.objects.create_user(username="staying", password="pw")

        held = PositionAssignment.objects.create(
            user=leaving, position=theirs,
            starts_on=today - datetime.timedelta(days=200),
        )
        kept = PositionAssignment.objects.create(
            user=staying, position=survivor,
            starts_on=today - datetime.timedelta(days=90),
        )
        return budget, held, kept

    def test_the_preview_names_the_holders_whose_posts_would_end(self):
        """A count is not enough. The admin is about to end someone's
        appointment, and should see whose before agreeing to it."""
        budget, held, _ = self._two_offices_with_heads()

        preview = self.client.get(
            f"/api/org/offices/{self.accounting.id}/merge/?into={budget.id}"
        ).data["moves"]

        self.assertEqual(preview["holders_ending"], 1)
        self.assertEqual(
            [h["user"] for h in preview["holders_ending_detail"]], ["leaving"],
        )
        self.assertEqual(preview["holders_ending_detail"][0]["position"], "Head")

        # A preview ends nothing.
        held.refresh_from_db()
        self.assertIsNone(held.ends_on)

    def test_the_retired_offices_head_assignment_is_ended_with_a_date(self):
        budget, held, kept = self._two_offices_with_heads()

        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )

        held.refresh_from_db()
        self.assertEqual(held.ends_on, timezone.localdate())
        self.assertFalse(held.is_current)
        # Ended, never deleted - the record of who held it stands.
        self.assertTrue(PositionAssignment.objects.filter(pk=held.pk).exists())

        kept.refresh_from_db()
        self.assertIsNone(kept.ends_on)
        self.assertTrue(kept.is_current)

    def test_the_survivors_head_is_untouched(self):
        budget, _, kept = self._two_offices_with_heads()
        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        kept.refresh_from_db()
        self.assertEqual(kept.position.office, budget)
        self.assertTrue(kept.position.is_active)
        self.assertTrue(kept.is_current)

    def test_the_merged_office_has_no_current_holder_afterwards(self):
        """The symptom the dating fixes: without it, the retired office
        still answers "who is the current Head" with a name."""
        budget, _, _ = self._two_offices_with_heads()
        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        self.assertFalse(
            PositionAssignment.objects.filter(
                position__office=self.accounting, ends_on__isnull=True,
            ).exists()
        )

    def test_a_conflicting_qms_position_ends_the_same_way(self):
        """IMR and Custodian are positions like any other here. Carol
        stops being QMS staff because her assignment ended, not because
        one query happens to filter on the position's active flag."""
        today = timezone.localdate()
        budget = Office.objects.create(name="Budget Office", parent=self.vp)
        theirs = Position.objects.create(office=self.accounting, kind=Position.IMR)
        Position.objects.create(office=budget, kind=Position.IMR)

        carol = CustomUser.objects.create_user(username="carol", password="pw")
        held = PositionAssignment.objects.create(
            user=carol, position=theirs, starts_on=today,
        )

        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        held.refresh_from_db()
        self.assertEqual(held.ends_on, today)
        self.assertFalse(holds_current_qms_position(carol))

    def test_a_custodian_conflict_ends_the_same_way(self):
        today = timezone.localdate()
        budget = Office.objects.create(name="Budget Office", parent=self.vp)
        theirs = Position.objects.create(
            office=self.accounting, kind=Position.DOCUMENT_CUSTODIAN,
        )
        Position.objects.create(office=budget, kind=Position.DOCUMENT_CUSTODIAN)

        dave = CustomUser.objects.create_user(username="dave", password="pw")
        held = PositionAssignment.objects.create(
            user=dave, position=theirs, starts_on=today,
        )

        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        held.refresh_from_db()
        self.assertEqual(held.ends_on, today)

    def test_a_non_conflicting_holder_keeps_their_post(self):
        """Only the positions that cannot move are ended. An Encoder the
        surviving office does not have moves across, and the person goes
        on holding it at the office that now exists."""
        today = timezone.localdate()
        budget = Office.objects.create(name="Budget Office", parent=self.vp)
        encoder = Position.objects.create(
            office=self.accounting, kind=Position.ENCODER,
        )
        erin = CustomUser.objects.create_user(username="erin", password="pw")
        held = PositionAssignment.objects.create(
            user=erin, position=encoder, starts_on=today,
        )

        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        held.refresh_from_db()
        self.assertIsNone(held.ends_on)
        self.assertEqual(held.position.office, budget)
        self.assertTrue(held.position.is_active)

    def test_an_already_ended_assignment_is_not_re_dated(self):
        """Someone who left the post last year keeps the date they left,
        not the date of the merge."""
        today = timezone.localdate()
        last_year = today - datetime.timedelta(days=300)
        budget = Office.objects.create(name="Budget Office", parent=self.vp)
        theirs = Position.objects.create(office=self.accounting, kind=Position.HEAD)
        Position.objects.create(office=budget, kind=Position.HEAD)

        frank = CustomUser.objects.create_user(username="frank", password="pw")
        old = PositionAssignment.objects.create(
            user=frank, position=theirs,
            starts_on=last_year - datetime.timedelta(days=100),
            ends_on=last_year,
        )

        self.confirmed(
            "post", f"/api/org/offices/{self.accounting.id}/merge/",
            {"into": budget.id},
        )
        old.refresh_from_db()
        self.assertEqual(old.ends_on, last_year)
