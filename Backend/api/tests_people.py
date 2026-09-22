"""People and the posts they hold.

Three things this phase was asked to confirm, and they lead:

* the QMS positions have **one home** by data, not by code - and splitting
  them again is possible without a change here;
* an assignment can be **acting / OIC**, because somebody signs the form
  while a post is vacant;
* one person can hold **two offices' Head posts at once**, which the
  one-current-Head constraint must permit rather than block.

Every test that expects an error asserts the reason, not only the status.
A 400 is not a claim about anything.
"""

import datetime

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import CustomUser, Office, Position, PositionAssignment
from api.views import holds_current_qms_position, issue_reauth_token

PASSWORD = "correct-horse-battery"


class PeopleFixture(TestCase):

    def setUp(self):
        self.today = datetime.date.today()

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
        self.qms = Office.objects.create(
            name="Quality Management Office", parent=self.president,
        )

        self.alice = CustomUser.objects.create_user(
            username="alice", password="pw", full_name="Alice Cruz",
            is_approved=True,
        )
        self.bob = CustomUser.objects.create_user(
            username="bob", password="pw", full_name="Bob Reyes",
            is_approved=True,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def confirmed(self, path, body=None):
        return self.client.post(
            path, body or {}, format="json",
            HTTP_X_REAUTH_TOKEN=issue_reauth_token(self.admin),
        )

    def assign(self, person, office, kind, **extra):
        body = {"office_id": office.id, "kind": kind}
        body.update(extra)
        return self.confirmed(f"/api/org/people/{person.id}/assign/", body)


class ConcurrentHeadsTests(PeopleFixture):
    """One person heading two offices. The constraint is per position, and
    each office has its own - so this must work, and the *same* office
    having two current Heads must not."""

    def test_one_person_can_head_two_offices_at_once(self):
        first = self.assign(self.alice, self.accounting, Position.HEAD)
        second = self.assign(self.alice, self.budget, Position.HEAD)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(
            PositionAssignment.objects.filter(
                user=self.alice, ends_on__isnull=True,
            ).count(),
            2,
        )

    def test_the_same_office_still_cannot_have_two_current_heads(self):
        self.assign(self.alice, self.accounting, Position.HEAD)
        response = self.assign(self.bob, self.accounting, Position.HEAD)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["reason"], "already_held")
        self.assertIn("alice", response.data["error"])

    def test_the_refusal_says_who_holds_it(self):
        """A constraint reported as a database error is something nobody
        can act on. This one has to name the person and the next step."""
        self.assign(self.alice, self.accounting, Position.HEAD)
        response = self.assign(self.bob, self.accounting, Position.HEAD)
        self.assertIn("End that appointment first", response.data["error"])

    def test_succession_works_after_ending_the_first(self):
        first = self.assign(self.alice, self.accounting, Position.HEAD)
        self.confirmed(f"/api/org/assignments/{first.data['id']}/end/")
        second = self.assign(self.bob, self.accounting, Position.HEAD)
        self.assertEqual(second.status_code, 201)


class ActingAssignmentTests(PeopleFixture):

    def test_an_assignment_can_be_recorded_as_acting(self):
        response = self.assign(
            self.alice, self.accounting, Position.HEAD, is_acting=True,
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["is_acting"])

    def test_acting_is_not_the_default(self):
        response = self.assign(self.alice, self.accounting, Position.HEAD)
        self.assertFalse(response.data["is_acting"])

    def test_an_officer_in_charge_still_counts_as_the_current_head(self):
        """The record says the appointment was temporary. It does not say
        the person could do less - an OIC concurs for the office exactly
        as a substantive head does."""
        self.assign(self.alice, self.accounting, Position.HEAD, is_acting=True)
        response = self.client.get("/api/org/positions/").data
        office = next(
            o for o in response["offices"] if o["office_id"] == self.accounting.id
        )
        self.assertTrue(office["has_current_head"])
        head = next(p for p in office["positions"] if p["kind"] == Position.HEAD)
        self.assertTrue(head["held_by"][0]["is_acting"])

    def test_an_acting_head_still_blocks_a_second_current_head(self):
        """Otherwise an OIC would be a way around the rule."""
        self.assign(self.alice, self.accounting, Position.HEAD, is_acting=True)
        response = self.assign(self.bob, self.accounting, Position.HEAD)
        self.assertEqual(response.data["reason"], "already_held")

    def test_acting_shows_in_the_history_after_it_ends(self):
        created = self.assign(
            self.alice, self.accounting, Position.HEAD, is_acting=True,
        )
        self.confirmed(f"/api/org/assignments/{created.data['id']}/end/")
        office = next(
            o for o in self.client.get("/api/org/positions/").data["offices"]
            if o["office_id"] == self.accounting.id
        )
        head = next(p for p in office["positions"] if p["kind"] == Position.HEAD)
        self.assertTrue(head["previously"][0]["is_acting"])


class QmsPositionHomeTests(PeopleFixture):
    """One office holds both QMS positions, because that is what was
    entered - not because anything here requires it."""

    def test_both_qms_positions_can_live_in_one_office(self):
        self.assign(self.alice, self.qms, Position.IMR)
        self.assign(self.bob, self.qms, Position.DOCUMENT_CUSTODIAN)

        qms = self.client.get("/api/org/positions/").data["qms"]
        self.assertEqual(
            {(row["kind"], row["user"]) for row in qms},
            {(Position.IMR, "alice"), (Position.DOCUMENT_CUSTODIAN, "bob")},
        )
        self.assertEqual({row["office"] for row in qms}, {"Quality Management Office"})

    def test_one_person_can_hold_both(self):
        """Reported as one person in practice. Two positions, one holder -
        not one merged position, so splitting them later changes nothing
        but the assignments."""
        self.assign(self.alice, self.qms, Position.IMR)
        self.assign(self.alice, self.qms, Position.DOCUMENT_CUSTODIAN)
        self.assertTrue(holds_current_qms_position(self.alice))
        self.assertEqual(
            len(self.client.get("/api/org/positions/").data["qms"]), 2
        )

    def test_the_two_positions_can_be_split_across_offices_again(self):
        """Nothing assumes one home. If the university separates them
        again it is data entry, not a code change."""
        records = Office.objects.create(name="Records Office", parent=self.president)
        self.assign(self.alice, self.qms, Position.IMR)
        self.assign(self.bob, records, Position.DOCUMENT_CUSTODIAN)

        qms = self.client.get("/api/org/positions/").data["qms"]
        self.assertEqual(
            {row["office"] for row in qms},
            {"Quality Management Office", "Records Office"},
        )

    def test_two_people_may_hold_the_imr_post_for_now(self):
        """SOLE_HOLDER_KINDS is (HEAD,) until the QMS office answers
        whether a university may have two. The permissive choice: a wrong
        restriction blocks real work, a missing one can be added."""
        response = self.assign(self.bob, self.qms, Position.IMR)
        self.assertEqual(response.status_code, 201)
        second = Office.objects.create(name="QMS Annex", parent=self.president)
        self.assertEqual(
            self.assign(self.alice, second, Position.IMR).status_code, 201
        )


class AssignmentRulesTests(PeopleFixture):

    def test_assigning_a_head_needs_a_password(self):
        response = self.client.post(
            f"/api/org/people/{self.alice.id}/assign/",
            {"office_id": self.accounting.id, "kind": Position.HEAD},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_required")

    def test_assigning_an_encoder_does_not(self):
        """Drafting is ordinary work, and a prompt on it teaches people to
        type the password without reading."""
        response = self.client.post(
            f"/api/org/people/{self.alice.id}/assign/",
            {"office_id": self.accounting.id, "kind": Position.ENCODER},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_several_encoders_are_allowed_in_one_office(self):
        self.assign(self.alice, self.accounting, Position.ENCODER)
        response = self.assign(self.bob, self.accounting, Position.ENCODER)
        self.assertEqual(response.status_code, 201)

    def test_an_unapproved_person_cannot_hold_a_post(self):
        waiting = CustomUser.objects.create_user(
            username="waiting", password="pw", is_approved=False,
        )
        response = self.assign(waiting, self.accounting, Position.ENCODER)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["reason"], "not_approved")

    def test_an_inactive_office_cannot_be_assigned_to(self):
        self.accounting.is_active = False
        self.accounting.save()
        response = self.assign(self.alice, self.accounting, Position.ENCODER)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["reason"], "office_inactive")

    def test_an_unknown_position_kind_is_refused(self):
        response = self.assign(self.alice, self.accounting, "chancellor")
        self.assertEqual(response.status_code, 400)
        self.assertIn("chancellor", response.data["error"])

    def test_an_assignment_cannot_end_before_it_started(self):
        created = self.assign(self.alice, self.accounting, Position.ENCODER)
        response = self.client.post(
            f"/api/org/assignments/{created.data['id']}/end/",
            {"ends_on": str(self.today - datetime.timedelta(days=5))},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["reason"], "ends_before_start")

    def test_ending_an_assignment_twice_is_refused(self):
        created = self.assign(self.alice, self.accounting, Position.ENCODER)
        self.client.post(f"/api/org/assignments/{created.data['id']}/end/")
        again = self.client.post(f"/api/org/assignments/{created.data['id']}/end/")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.data["reason"], "already_ended")

    def test_an_ended_assignment_is_kept_not_removed(self):
        created = self.assign(self.alice, self.accounting, Position.ENCODER)
        self.client.post(f"/api/org/assignments/{created.data['id']}/end/")
        self.assertTrue(
            PositionAssignment.objects.filter(pk=created.data["id"]).exists()
        )


class PeopleListTests(PeopleFixture):

    def test_only_the_system_admin_sees_the_people_list(self):
        """Names are personal data. The process itself only ever needs a
        position."""
        ordinary = APIClient()
        ordinary.force_authenticate(user=self.alice)
        self.assertEqual(ordinary.get("/api/org/people/").status_code, 403)

    def test_awaiting_position_lists_people_who_can_do_nothing(self):
        self.assign(self.alice, self.accounting, Position.ENCODER)
        data = self.client.get("/api/org/people/?filter=awaiting_position").data
        names = [p["username"] for p in data["people"]]
        self.assertIn("bob", names)
        self.assertNotIn("alice", names)

    def test_a_person_carries_their_current_and_past_posts(self):
        created = self.assign(self.alice, self.accounting, Position.ENCODER)
        self.client.post(f"/api/org/assignments/{created.data['id']}/end/")
        self.assign(self.alice, self.budget, Position.ENCODER)

        row = next(
            p for p in self.client.get("/api/org/people/").data["people"]
            if p["username"] == "alice"
        )
        self.assertEqual(len(row["current_positions"]), 1)
        self.assertEqual(len(row["past_positions"]), 1)


class DeactivationTests(PeopleFixture):

    def test_deactivating_ends_every_current_post(self):
        self.assign(self.alice, self.accounting, Position.HEAD)
        self.assign(self.alice, self.budget, Position.ENCODER)

        response = self.confirmed(f"/api/org/people/{self.alice.id}/deactivate/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_active"])
        self.assertEqual(
            PositionAssignment.objects.filter(
                user=self.alice, ends_on__isnull=True,
            ).count(),
            0,
        )

    def test_deactivating_frees_the_head_post_for_someone_else(self):
        self.assign(self.alice, self.accounting, Position.HEAD)
        self.confirmed(f"/api/org/people/{self.alice.id}/deactivate/")
        self.assertEqual(
            self.assign(self.bob, self.accounting, Position.HEAD).status_code, 201
        )

    def test_the_person_is_kept(self):
        self.confirmed(f"/api/org/people/{self.alice.id}/deactivate/")
        self.assertTrue(CustomUser.objects.filter(pk=self.alice.pk).exists())

    def test_deactivating_needs_a_password(self):
        response = self.client.post(
            f"/api/org/people/{self.alice.id}/deactivate/", {}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["reason"], "reauth_required")

    def test_the_system_admin_cannot_deactivate_themselves(self):
        """Nobody would be left who could configure anything, and the
        recovery is a shell."""
        response = self.confirmed(f"/api/org/people/{self.admin.id}/deactivate/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["reason"], "self")

    def test_a_deactivated_person_cannot_be_assigned_to(self):
        self.confirmed(f"/api/org/people/{self.alice.id}/deactivate/")
        response = self.assign(self.alice, self.accounting, Position.ENCODER)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["reason"], "inactive")

    def test_reactivating_does_not_restore_the_posts_they_held(self):
        """Those ended on a date. Re-opening them would rewrite what the
        record says happened."""
        self.assign(self.alice, self.accounting, Position.HEAD)
        self.confirmed(f"/api/org/people/{self.alice.id}/deactivate/")
        self.confirmed(f"/api/org/people/{self.alice.id}/reactivate/")

        self.assertEqual(
            PositionAssignment.objects.filter(
                user=self.alice, ends_on__isnull=True,
            ).count(),
            0,
        )


class PositionsByOfficeTests(PeopleFixture):

    def test_an_office_with_no_current_head_is_visible_as_such(self):
        """An office that cannot commit to anything is worth seeing."""
        self.assign(self.alice, self.accounting, Position.ENCODER)
        office = next(
            o for o in self.client.get("/api/org/positions/").data["offices"]
            if o["office_id"] == self.accounting.id
        )
        self.assertFalse(office["has_current_head"])

    def test_past_holders_are_listed_with_their_dates(self):
        created = self.assign(self.alice, self.accounting, Position.HEAD)
        self.confirmed(f"/api/org/assignments/{created.data['id']}/end/")
        self.assign(self.bob, self.accounting, Position.HEAD)

        office = next(
            o for o in self.client.get("/api/org/positions/").data["offices"]
            if o["office_id"] == self.accounting.id
        )
        head = next(p for p in office["positions"] if p["kind"] == Position.HEAD)
        self.assertEqual([h["user"] for h in head["held_by"]], ["bob"])
        self.assertEqual([p["user"] for p in head["previously"]], ["alice"])
        self.assertEqual(head["previously"][0]["to"], self.today)
