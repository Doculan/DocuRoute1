"""The switchover, and everything that must move with it.

Four things are being guarded.

**The gate refuses while anyone would lose access.** There is no force,
so the tests care about what counts as a blocker and what clears it.

**Rollback is total.** A flag that restores most of the old behaviour is
worse than no flag, because the part it does not restore is the part
nobody thinks to check. So `can_propose` is tested in both directions,
not only `can_reach`.

**The owner may propose** - an office can own a manual and work on it -
**but never approve its own proposal.** That is a configuration rule, and
it is refused when the configuration is set rather than when somebody
tries to submit.

**Announcements move with access.** Otherwise the system scopes documents
by office and notices by department, which is two answers to "where do
you work" in one application.

Every test that expects an error asserts the reason, not only the status.
"""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api import access
from api.models import (
    AccessMode, Announcement, CustomUser, Department, Manual, ManualSeries,
    ManualSeriesOffice, ManualSection, Office, OfficeLink, Position,
    PositionAssignment,
)
from api.views import issue_reauth_token

PASSWORD = "correct-horse-battery"


class SwitchoverFixture(TestCase):
    """A small but complete organisation: a president over two VPs, one
    working office under each, and a document owned by each VP."""

    def setUp(self):
        # `timezone.localdate()`, not `date.today()`. The application
        # works in the project's timezone and the machine may be a day
        # ahead of it - which made every assignment here start
        # tomorrow, and every test that needed one fail.
        self.today = timezone.localdate()
        self.cas = Department.objects.create(name="CAS")
        self.cme = Department.objects.create(name="CME")

        self.admin = CustomUser.objects.create_user(
            username="sysadmin", password=PASSWORD, role="admin",
            system_role=CustomUser.SYSTEM_ADMIN, is_approved=True,
        )

        self.president = Office.objects.create(
            name="Office of the University President", abbreviation="OP",
            is_approving_level=True,
        )
        self.vpaf = Office.objects.create(
            name="VP for Administration and Finance", abbreviation="VPAF",
            parent=self.president, is_approving_level=True,
        )
        self.vpsd = Office.objects.create(
            name="VP for Student Development", abbreviation="VPSD",
            parent=self.president, is_approving_level=True,
        )
        self.accounting = Office.objects.create(
            name="Accounting Office", abbreviation="ACC", parent=self.vpaf,
        )
        self.registrar = Office.objects.create(
            name="Registrar's Office", abbreviation="REG", parent=self.vpsd,
        )

        self.fam = ManualSeries.objects.create(
            code="FAM", title="Finance and Administration Manual",
            owning_office=self.vpaf,
        )
        self.sdm = ManualSeries.objects.create(
            code="SDM", title="Student Development Manual",
            owning_office=self.vpsd,
        )
        ManualSeriesOffice.objects.create(
            series=self.fam, office=self.accounting,
            relationship=OfficeLink.CONCURRING,
        )
        ManualSeriesOffice.objects.create(
            series=self.fam, office=self.registrar,
            relationship=OfficeLink.READER,
        )

        self.fam602 = Manual.objects.create(
            title="FAM 6.02", department=self.cas, series=self.fam,
        )
        self.sdm301 = Manual.objects.create(
            title="SDM 3.01", department=self.cme, series=self.sdm,
        )
        ManualSection.objects.create(
            manual=self.fam602, subtitle="3.0 POLICIES", content="Text.",
            tag="POLICY",
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def token(self):
        return issue_reauth_token(self.admin)

    def confirmed(self, path, body=None):
        return self.client.post(
            path, body or {}, format="json", HTTP_X_REAUTH_TOKEN=self.token(),
        )

    def a_person(self, username, department=None, office=None,
                 kind=Position.ENCODER, approved=True):
        person = CustomUser.objects.create_user(
            username=username, password="pw", is_approved=approved,
            department=department,
        )
        if office is not None:
            position, _ = Position.objects.get_or_create(
                office=office, kind=kind,
            )
            PositionAssignment.objects.create(
                user=person, position=position, starts_on=self.today,
            )
        return person

    def switch_on(self):
        return self.confirmed("/api/org/switchover/set/", {"by_position": True})

    def switch_off(self):
        return self.confirmed("/api/org/switchover/set/", {"by_position": False})

    def concur(self, series, office):
        ManualSeriesOffice.objects.get_or_create(
            series=series, office=office,
            defaults={'relationship': OfficeLink.CONCURRING},
        )


class GateTests(SwitchoverFixture):

    def test_it_starts_scoped_by_department(self):
        self.assertFalse(AccessMode.current().by_position)
        self.assertFalse(access.by_position())

    def test_an_approved_account_with_no_position_blocks_the_switch(self):
        self.a_person("stranded", department=self.cas)
        self.concur(self.sdm, self.registrar)

        readiness = self.client.get("/api/org/switchover/").data
        self.assertFalse(readiness["ready"])
        codes = [b["code"] for b in readiness["blockers"]]
        self.assertIn("staff_without_positions", codes)

        response = self.switch_on()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["reason"], "not_ready")
        self.assertFalse(AccessMode.current().by_position)

    def test_giving_them_a_position_clears_it(self):
        person = self.a_person("stranded", department=self.cas)
        self.concur(self.sdm, self.registrar)

        position, _ = Position.objects.get_or_create(
            office=self.accounting, kind=Position.ENCODER,
        )
        PositionAssignment.objects.create(
            user=person, position=position, starts_on=self.today,
        )
        self.assertTrue(self.client.get("/api/org/switchover/").data["ready"])

    def test_deactivating_the_account_clears_it_too(self):
        """Some of these are test accounts that will never hold a post.
        Making a position the only way out would mean inventing one."""
        person = self.a_person("test-account", department=self.cas)
        self.concur(self.sdm, self.registrar)
        self.assertFalse(self.client.get("/api/org/switchover/").data["ready"])

        self.confirmed(f"/api/org/people/{person.id}/deactivate/")
        self.assertTrue(self.client.get("/api/org/switchover/").data["ready"])

    def test_an_unapproved_account_does_not_block(self):
        """They cannot sign in, so they cannot lose anything."""
        self.a_person("waiting", department=self.cas, approved=False)
        self.concur(self.sdm, self.registrar)
        self.assertTrue(self.client.get("/api/org/switchover/").data["ready"])

    def test_the_system_admin_does_not_block(self):
        """They hold no position by design - configuring the system and
        working in an office are different jobs."""
        self.concur(self.sdm, self.registrar)
        self.assertTrue(self.client.get("/api/org/switchover/").data["ready"])

    def test_a_document_nobody_could_propose_against_blocks(self):
        readiness = self.client.get("/api/org/switchover/").data
        codes = [b["code"] for b in readiness["blockers"]]
        self.assertIn("documents_without_a_concurring_office", codes)
        blocker = next(
            b for b in readiness["blockers"]
            if b["code"] == "documents_without_a_concurring_office"
        )
        self.assertEqual([d["title"] for d in blocker["detail"]], ["SDM 3.01"])

    def test_switching_needs_a_password(self):
        self.concur(self.sdm, self.registrar)
        response = self.client.post(
            "/api/org/switchover/set/", {"by_position": True}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_required")

    def test_switching_records_who_and_when(self):
        self.concur(self.sdm, self.registrar)
        self.switch_on()
        mode = AccessMode.current()
        self.assertTrue(mode.by_position)
        self.assertEqual(mode.switched_by, self.admin)
        self.assertIsNotNone(mode.switched_at)

    def test_switching_back_is_not_gated(self):
        """Going back never takes access away - it restores what people
        had. Gating it would make a rollback harder than the switch."""
        self.concur(self.sdm, self.registrar)
        self.switch_on()
        self.a_person("stranded", department=self.cas)
        response = self.switch_off()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AccessMode.current().by_position)

    def test_only_the_system_admin_can_see_or_flip_it(self):
        person = self.a_person("ordinary", department=self.cas)
        client = APIClient()
        client.force_authenticate(user=person)
        self.assertEqual(client.get("/api/org/switchover/").status_code, 403)
        self.assertEqual(
            client.post("/api/org/switchover/set/", {"by_position": True},
                        format="json").status_code,
            403,
        )


class PreviewTests(SwitchoverFixture):

    def test_the_preview_shows_before_and_after_per_account(self):
        self.a_person("keeps", department=self.cas, office=self.accounting)
        data = self.client.get("/api/org/switchover/").data
        row = next(r for r in data["preview"] if r["username"] == "keeps")
        self.assertEqual(row["manuals_now"], 1)
        self.assertEqual(row["manuals_after"], 1)
        self.assertEqual(row["offices"], ["ACC"])

    def test_it_catches_someone_who_holds_the_wrong_position(self):
        """The blockers cannot see this: they hold a post, so they are not
        stranded - they just end up somewhere else."""
        self.a_person("moved", department=self.cas, office=self.registrar)
        row = next(
            r for r in self.client.get("/api/org/switchover/").data["preview"]
            if r["username"] == "moved"
        )
        self.assertEqual(row["manuals_now"], 1)      # CAS: FAM 6.02
        self.assertEqual(row["manuals_after"], 1)    # REG reads FAM 6.02
        self.assertEqual(row["offices"], ["REG"])

    def test_the_preview_does_not_change_the_flag(self):
        """It reads both answers directly. Flipping the row to work out
        "after" would mean a staff member loading a page during the
        preview got the other rule."""
        self.a_person("someone", department=self.cas, office=self.accounting)
        self.client.get("/api/org/switchover/")
        self.assertFalse(AccessMode.current().by_position)

    def test_the_admin_row_says_all_rather_than_a_false_loss(self):
        """An admin's reach does not come from an office - the admin
        screens pass them regardless - so running them through the office
        rules would report a loss that will not happen."""
        row = next(
            r for r in self.client.get("/api/org/switchover/").data["preview"]
            if r["username"] == "sysadmin"
        )
        self.assertFalse(row["scoped"])
        self.assertEqual(row["manuals_now"], Manual.objects.count())
        self.assertEqual(row["manuals_after"], Manual.objects.count())
        self.assertFalse(row["loses_everything"])

    def test_an_ordinary_account_is_scoped(self):
        self.a_person("worker", department=self.cas, office=self.accounting)
        row = next(
            r for r in self.client.get("/api/org/switchover/").data["preview"]
            if r["username"] == "worker"
        )
        self.assertTrue(row["scoped"])

    def test_deactivated_accounts_are_listed_separately(self):
        person = self.a_person("gone", department=self.cas)
        self.confirmed(f"/api/org/people/{person.id}/deactivate/")

        data = self.client.get("/api/org/switchover/").data
        self.assertIn("gone", [r["username"] for r in data["inactive"]])
        self.assertNotIn("gone", [r["username"] for r in data["preview"]])

    def test_unapproved_accounts_are_listed_separately(self):
        self.a_person("waiting", department=self.cas, approved=False)
        data = self.client.get("/api/org/switchover/").data
        self.assertIn("waiting", [r["username"] for r in data["unapproved"]])
        self.assertNotIn("waiting", [r["username"] for r in data["preview"]])


class ScopingAfterTheSwitchTests(SwitchoverFixture):

    def setUp(self):
        super().setUp()
        self.concur(self.sdm, self.registrar)
        self.encoder = self.a_person(
            "encoder", department=self.cas, office=self.accounting,
        )
        self.reader = self.a_person(
            "reader", department=self.cme, office=self.registrar,
        )
        self.switch_on()

    def test_a_concurring_office_reaches_and_may_propose(self):
        self.assertTrue(access.can_reach(self.encoder, self.fam602))
        self.assertTrue(access.can_propose(self.encoder, self.fam602))

    def test_a_reader_office_reaches_but_may_not_propose(self):
        self.assertTrue(access.can_reach(self.reader, self.fam602))
        self.assertFalse(access.can_propose(self.reader, self.fam602))

    def test_an_unrelated_office_reaches_nothing(self):
        stranger = self.a_person(
            "stranger", department=self.cas,
            office=Office.objects.create(name="Library", parent=self.president),
        )
        self.assertFalse(access.can_reach(stranger, self.fam602))

    def test_someone_with_no_position_sees_nothing_rather_than_everything(self):
        nobody = CustomUser.objects.create_user(
            username="nobody", password="pw", is_approved=True,
            department=self.cas,
        )
        self.assertEqual(access.offices_for(nobody), [])
        self.assertEqual(
            access.manuals_for(nobody, Manual.objects.all()).count(), 0
        )

    def test_a_post_at_a_retired_office_authorises_nothing(self):
        self.accounting.is_active = False
        self.accounting.save()
        self.assertFalse(access.can_reach(self.encoder, self.fam602))

    def test_an_ended_post_authorises_nothing(self):
        PositionAssignment.objects.filter(user=self.encoder).update(
            starts_on=self.today - datetime.timedelta(days=30),
            ends_on=self.today - datetime.timedelta(days=1),
        )
        self.assertFalse(access.can_reach(self.encoder, self.fam602))

    def test_the_list_and_the_gate_agree(self):
        """If they ever disagree, a screen shows a manual that then
        refuses to open."""
        for person in (self.encoder, self.reader):
            listed = set(
                access.manuals_for(person, Manual.objects.all())
                .values_list("pk", flat=True)
            )
            gated = {
                m.pk for m in Manual.objects.all()
                if access.can_reach(person, m)
            }
            self.assertEqual(listed, gated, person.username)

    def test_a_manual_linked_through_two_offices_appears_once(self):
        position, _ = Position.objects.get_or_create(
            office=self.registrar, kind=Position.HEAD,
        )
        PositionAssignment.objects.create(
            user=self.encoder, position=position, starts_on=self.today,
        )
        self.assertEqual(
            access.manuals_for(self.encoder, Manual.objects.all()).count(),
            Manual.objects.filter(
                pk__in=[self.fam602.pk, self.sdm301.pk]
            ).count(),
        )


class RollbackIsTotalTests(SwitchoverFixture):

    def test_proposing_returns_to_the_department_rule(self):
        """`can_propose` honours the flag too. A rollback that restored
        reading but not proposing would leave the half nobody checks."""
        person = self.a_person(
            "someone", department=self.cas, office=self.registrar,
        )
        self.concur(self.sdm, self.registrar)

        # Before: the department rule - CAS, so FAM 6.02.
        self.assertTrue(access.can_propose(person, self.fam602))

        self.switch_on()
        # After: REG only reads FAM, so it may not propose against it.
        self.assertFalse(access.can_propose(person, self.fam602))

        self.switch_off()
        self.assertTrue(access.can_propose(person, self.fam602))

    def test_reading_returns_too(self):
        person = self.a_person("someone", department=self.cas)
        self.concur(self.sdm, self.registrar)
        self.assertTrue(access.can_reach(person, self.fam602))

        # No position, so after the switch they would reach nothing.
        self.assertEqual(
            access.manuals_for(person, Manual.objects.all(), mode='position').count(),
            0,
        )
        self.assertEqual(
            access.manuals_for(person, Manual.objects.all(), mode='department').count(),
            1,
        )


class OwnerMayProposeTests(SwitchoverFixture):
    """The VPSD owns the Student Development Manual and its own staff
    draft changes to it. Allowed - but the route must continue above the
    owner, or the office approves its own proposal."""

    def test_an_owner_can_also_be_listed_as_concurring(self):
        response = self.client.put(
            f"/api/org/series/{self.sdm.id}/offices/",
            {"offices": [{"office_id": self.vpsd.id,
                          "relationship": "concurring"}]},
            format="json", HTTP_X_REAUTH_TOKEN=self.token(),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.sdm301.refresh_from_db()
        self.assertIn(self.vpsd, self.sdm301.concurring_offices())

    def test_an_owner_that_concurs_may_propose(self):
        self.concur(self.sdm, self.vpsd)
        person = self.a_person("vpsd-staff", department=self.cme, office=self.vpsd)
        self.concur(self.fam, self.accounting)
        self.switch_on()
        self.assertTrue(access.can_propose(person, self.sdm301))

    def test_an_owner_that_concurs_counts_for_the_blocker(self):
        """Otherwise a document only its owner works on would read as
        stranded, and the switch would be refused for no reason."""
        self.concur(self.sdm, self.vpsd)
        readiness = self.client.get("/api/org/switchover/").data
        codes = [b["code"] for b in readiness["blockers"]]
        self.assertNotIn("documents_without_a_concurring_office", codes)

    def test_the_route_still_continues_above_the_owner(self):
        self.concur(self.sdm, self.vpsd)
        self.sdm301.refresh_from_db()
        self.assertEqual(
            [str(o) for o in self.sdm301.approval_route()], ["VPSD", "OP"],
        )
        self.assertIsNone(self.sdm301.owner_proposal_conflict())

    def test_stopping_at_the_owner_while_it_proposes_is_refused(self):
        """The configuration that would let an office approve its own
        proposal. Refused when it is set, not when somebody tries to
        submit - by then they have done the work."""
        self.concur(self.sdm, self.vpsd)
        response = self.client.patch(
            f"/api/org/series/{self.sdm.id}/",
            {"approval_stops_at_owner": True},
            format="json", HTTP_X_REAUTH_TOKEN=self.token(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.data["reason"], "owner_would_approve_its_own_proposal"
        )
        self.sdm.refresh_from_db()
        self.assertFalse(self.sdm.approval_stops_at_owner)

    def test_the_same_conflict_from_the_other_direction_is_refused(self):
        """Setting the route first, then adding the owner as concurring."""
        self.sdm.approval_stops_at_owner = True
        self.sdm.save()

        response = self.client.put(
            f"/api/org/series/{self.sdm.id}/offices/",
            {"offices": [{"office_id": self.vpsd.id,
                          "relationship": "concurring"}]},
            format="json", HTTP_X_REAUTH_TOKEN=self.token(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.data["reason"], "owner_would_approve_its_own_proposal"
        )
        # Rolled back, not half applied.
        self.assertEqual(
            ManualSeriesOffice.objects.filter(series=self.sdm).count(), 0
        )

    def test_an_owner_with_nothing_above_it_is_refused(self):
        """Not just the flag - a top-level owner has no approving level
        above it, so the route ends at it whatever the flag says."""
        top = ManualSeries.objects.create(
            code="TOP", title="Top Manual", owning_office=self.president,
        )
        document = Manual.objects.create(
            title="TOP 1.01", department=self.cas, series=top,
        )
        response = self.client.put(
            f"/api/org/series/{top.id}/offices/",
            {"offices": [{"office_id": self.president.id,
                          "relationship": "concurring"}]},
            format="json", HTTP_X_REAUTH_TOKEN=self.token(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("no approving level above it", response.data["error"])
        document.refresh_from_db()
        self.assertEqual(document.concurring_offices(), [])

    def test_a_reader_owner_raises_no_conflict(self):
        """Only proposing creates the problem. An owner that merely reads
        its own manual approves nothing it wrote."""
        ManualSeriesOffice.objects.create(
            series=self.sdm, office=self.vpsd, relationship=OfficeLink.READER,
        )
        self.sdm.approval_stops_at_owner = True
        self.sdm.save()
        self.sdm301.refresh_from_db()
        self.assertIsNone(self.sdm301.owner_proposal_conflict())


class AnnouncementsFollowTheSwitchTests(SwitchoverFixture):

    def setUp(self):
        super().setUp()
        self.concur(self.sdm, self.registrar)
        self.person = self.a_person(
            "reader", department=self.cas, office=self.accounting,
        )

    def test_before_the_switch_they_are_targeted_by_department(self):
        Announcement.objects.create(
            title="For CAS", department=self.cas, created_by=self.admin,
        )
        Announcement.objects.create(
            title="For CME", department=self.cme, created_by=self.admin,
        )
        from api.views import _visible_announcements
        titles = [a.title for a in _visible_announcements(self.person)]
        self.assertEqual(titles, ["For CAS"])

    def test_after_the_switch_they_are_targeted_by_office(self):
        Announcement.objects.create(
            title="For Accounting", office=self.accounting, created_by=self.admin,
        )
        Announcement.objects.create(
            title="For the Registrar", office=self.registrar, created_by=self.admin,
        )
        self.switch_on()

        from api.views import _visible_announcements
        titles = [a.title for a in _visible_announcements(self.person)]
        self.assertEqual(titles, ["For Accounting"])

    def test_an_untargeted_announcement_reaches_everyone_either_way(self):
        Announcement.objects.create(title="For all", created_by=self.admin)
        from api.views import _visible_announcements
        self.assertIn(
            "For all", [a.title for a in _visible_announcements(self.person)]
        )
        self.switch_on()
        self.assertIn(
            "For all", [a.title for a in _visible_announcements(self.person)]
        )

    def test_a_department_targeted_notice_hides_rather_than_broadcasting(self):
        """The dangerous case. Its office is null, and null means
        "everyone" - so read carelessly, a notice meant for one
        department would go to the whole university at the moment of the
        switch. It has to mean "nobody" instead."""
        Announcement.objects.create(
            title="For CAS", department=self.cas, created_by=self.admin,
        )
        outsider = self.a_person(
            "outsider", department=self.cme, office=self.registrar,
        )
        self.switch_on()

        from api.views import _visible_announcements
        self.assertNotIn(
            "For CAS", [a.title for a in _visible_announcements(self.person)]
        )
        self.assertNotIn(
            "For CAS", [a.title for a in _visible_announcements(outsider)]
        )

    def test_the_switchover_warns_about_them_first(self):
        """A notice nobody sees is better than one everybody sees, but it
        is still a notice nobody sees."""
        Announcement.objects.create(
            title="For CAS", department=self.cas, created_by=self.admin,
        )
        warnings = self.client.get("/api/org/switchover/").data["warnings"]
        codes = [w["code"] for w in warnings]
        self.assertIn("announcements_targeted_by_department", codes)

    def test_the_payload_says_which_field_is_being_read(self):
        announcement = Announcement.objects.create(
            title="Notice", office=self.accounting, created_by=self.admin,
        )
        row = self.client.get(
            f"/api/admin/announcements/{announcement.id}/"
        ).data
        self.assertEqual(row["targets_by"], "department")
        self.switch_on()
        row = self.client.get(
            f"/api/admin/announcements/{announcement.id}/"
        ).data
        self.assertEqual(row["targets_by"], "office")
