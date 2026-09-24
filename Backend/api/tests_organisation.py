"""The organisation tables, and the access helper they will feed at 1c.

Two things are being guarded here.

The first is that the new tables cannot be talked into an impossible
state: an office inside its own hierarchy, two current Heads, a manual
related to one office twice. These are the rules later phases will rely
on without re-checking, so they have to hold at the bottom.

The second is that the access refactor changed **nothing** about who can
reach what. Thirteen scattered checks became calls to one helper, and the
helper still returns the v3 answer on purpose - the point of the exercise
is that the switchover at 1c is one edit with one test surface, not
thirteen edits where a mistake is invisible.
"""

import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api import access
from api.models import (
    CustomUser, Manual, ManualOffice, ManualSection, ManualSeries,
    ManualSeriesOffice, Office, OfficeLink, Position, PositionAssignment,
)


class OfficeHierarchyTests(TestCase):

    def setUp(self):
        self.president = Office.objects.create(
            name="Office of the President", abbreviation="OP",
            is_approving_level=True,
        )
        self.vp = Office.objects.create(
            name="Vice President for Administration", abbreviation="VPA",
            parent=self.president, is_approving_level=True,
        )
        self.accounting = Office.objects.create(
            name="Accounting Services Office", abbreviation="ASO",
            parent=self.vp,
        )

    def test_the_tables_ship_empty(self):
        """No import from the old departments. A migration that quietly
        created an office per department would look helpful and would be
        the university's structure written by a script."""
        self.assertEqual(
            Office.objects.exclude(
                pk__in=[self.president.pk, self.vp.pk, self.accounting.pk]
            ).count(),
            0,
        )

    def test_ancestors_walk_upward_nearest_first(self):
        self.assertEqual(
            [o.pk for o in self.accounting.ancestors()],
            [self.vp.pk, self.president.pk],
        )

    def test_an_office_cannot_be_its_own_parent(self):
        self.accounting.parent = self.accounting
        with self.assertRaises(ValidationError):
            self.accounting.full_clean()

    def test_an_office_cannot_be_moved_inside_its_own_hierarchy(self):
        """The cycle that a screen actually produces: each row still has
        exactly one parent and looks locally valid - only the path is
        wrong, which is why this cannot be a database constraint."""
        self.president.parent = self.accounting
        with self.assertRaises(ValidationError):
            self.president.full_clean()

    def test_ancestors_terminates_even_if_the_data_is_cyclic(self):
        """A bad row must not hang a request. Written around the
        validation deliberately, because the guarantee being tested is
        what happens when validation was somehow bypassed."""
        Office.objects.filter(pk=self.president.pk).update(parent=self.accounting)
        self.president.refresh_from_db()
        walk = self.accounting.ancestors()
        self.assertLessEqual(len(walk), 3)

    def test_an_office_cannot_be_merged_into_itself(self):
        self.accounting.merged_into = self.accounting
        with self.assertRaises(ValidationError):
            self.accounting.full_clean()

    def test_a_merged_office_still_exists(self):
        """History has to keep resolving. The office is marked, not
        removed."""
        finance = Office.objects.create(name="Finance Office", parent=self.vp)
        self.accounting.merged_into = finance
        self.accounting.is_active = False
        self.accounting.save()

        self.accounting.refresh_from_db()
        self.assertTrue(Office.objects.filter(pk=self.accounting.pk).exists())
        self.assertEqual(self.accounting.merged_into, finance)
        self.assertFalse(self.accounting.is_active)


class PositionTests(TestCase):

    def setUp(self):
        # `timezone.localdate()`, not `date.today()`. The application
        # works in the project's timezone and the machine may be a day
        # ahead of it - which made every assignment here start
        # tomorrow, and every test that needed one fail.
        self.today = timezone.localdate()
        self.office = Office.objects.create(name="Accounting Services Office")
        self.head = Position.objects.create(office=self.office, kind=Position.HEAD)
        self.encoder = Position.objects.create(
            office=self.office, kind=Position.ENCODER,
        )
        self.alice = CustomUser.objects.create_user(username="alice", password="pw")
        self.bob = CustomUser.objects.create_user(username="bob", password="pw")

    def test_exactly_one_current_head_per_office(self):
        """A real database constraint, not a check in a view: the rule
        should hold against the shell, a management command, and two
        requests arriving at the same moment."""
        PositionAssignment.objects.create(
            user=self.alice, position=self.head, starts_on=self.today,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PositionAssignment.objects.create(
                    user=self.bob, position=self.head, starts_on=self.today,
                )

    def test_a_head_can_be_replaced_by_ending_the_first_assignment(self):
        """The constraint must not make succession impossible - it is one
        *current* head, not one head ever."""
        first = PositionAssignment.objects.create(
            user=self.alice, position=self.head,
            starts_on=self.today - datetime.timedelta(days=365),
        )
        first.ends_on = self.today
        first.save()

        second = PositionAssignment.objects.create(
            user=self.bob, position=self.head, starts_on=self.today,
        )
        self.assertTrue(second.is_current)
        self.assertEqual(
            PositionAssignment.objects.filter(position=self.head).count(), 2,
        )

    def test_several_encoders_are_allowed(self):
        PositionAssignment.objects.create(
            user=self.alice, position=self.encoder, starts_on=self.today,
        )
        PositionAssignment.objects.create(
            user=self.bob, position=self.encoder, starts_on=self.today,
        )
        self.assertEqual(
            PositionAssignment.objects.filter(position=self.encoder).count(), 2,
        )

    def test_an_assignment_cannot_end_before_it_starts(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PositionAssignment.objects.create(
                    user=self.alice, position=self.encoder,
                    starts_on=self.today,
                    ends_on=self.today - datetime.timedelta(days=1),
                )

    # -- the bulk paths, which skip save() -------------------------
    #
    # `sole_holder` is what carries the constraint across the join to
    # `Position.kind`. It defaults to False, and False means the partial
    # index does not apply - so any writer that skips `save()` and leaves
    # it stale does not raise, it silently switches the rule off. These
    # cover every writer there is.

    def test_bulk_create_cannot_smuggle_in_a_second_current_head(self):
        PositionAssignment.objects.create(
            user=self.alice, position=self.head, starts_on=self.today,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PositionAssignment.objects.bulk_create([
                    PositionAssignment(
                        user=self.bob, position=self.head, starts_on=self.today,
                    ),
                ])

    def test_bulk_create_cannot_create_two_current_heads_in_one_call(self):
        """Neither row exists yet, so nothing is there to conflict with -
        the constraint has to catch them against each other."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PositionAssignment.objects.bulk_create([
                    PositionAssignment(
                        user=self.alice, position=self.head, starts_on=self.today,
                    ),
                    PositionAssignment(
                        user=self.bob, position=self.head, starts_on=self.today,
                    ),
                ])

    def test_bulk_create_still_allows_several_encoders(self):
        """The fix must not over-apply: only sole-holder positions are
        restricted, and Encoder is not one."""
        PositionAssignment.objects.bulk_create([
            PositionAssignment(
                user=self.alice, position=self.encoder, starts_on=self.today,
            ),
            PositionAssignment(
                user=self.bob, position=self.encoder, starts_on=self.today,
            ),
        ])
        self.assertEqual(
            PositionAssignment.objects.filter(position=self.encoder).count(), 2,
        )

    def test_a_bulk_update_onto_a_head_position_cannot_create_a_second(self):
        """The one update that can change the answer: moving rows to a
        different position. Without recomputing, these would arrive with
        sole_holder False and the index would ignore them."""
        PositionAssignment.objects.create(
            user=self.alice, position=self.head, starts_on=self.today,
        )
        moving = PositionAssignment.objects.create(
            user=self.bob, position=self.encoder, starts_on=self.today,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PositionAssignment.objects.filter(pk=moving.pk).update(
                    position=self.head,
                )

    def test_a_bulk_update_sets_the_flag_rather_than_leaving_it_stale(self):
        moving = PositionAssignment.objects.create(
            user=self.bob, position=self.encoder, starts_on=self.today,
        )
        self.assertFalse(moving.sole_holder)
        PositionAssignment.objects.filter(pk=moving.pk).update(position=self.head)
        moving.refresh_from_db()
        self.assertTrue(moving.sole_holder)

    def test_reopening_an_ended_head_assignment_in_bulk_is_caught(self):
        """`ends_on` does not change the flag, so this one rests entirely
        on the flag having been right when the row was written."""
        ended = PositionAssignment.objects.create(
            user=self.alice, position=self.head,
            starts_on=self.today - datetime.timedelta(days=30),
            ends_on=self.today - datetime.timedelta(days=1),
        )
        PositionAssignment.objects.create(
            user=self.bob, position=self.head, starts_on=self.today,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PositionAssignment.objects.filter(pk=ended.pk).update(ends_on=None)

    def test_a_positions_kind_cannot_be_changed(self):
        """Re-kinding would re-point every assignment ever made against
        the row, and leave their flags describing a kind that no longer
        applies."""
        self.encoder.kind = Position.HEAD
        with self.assertRaises(ValidationError):
            self.encoder.save()

    def test_saving_a_position_without_changing_its_kind_is_fine(self):
        self.encoder.is_active = False
        self.encoder.save()
        self.encoder.refresh_from_db()
        self.assertFalse(self.encoder.is_active)

    def test_one_position_row_per_office_and_kind(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Position.objects.create(office=self.office, kind=Position.HEAD)

    def test_a_person_can_hold_positions_in_several_offices(self):
        other = Office.objects.create(name="Registrar")
        other_encoder = Position.objects.create(
            office=other, kind=Position.ENCODER,
        )
        PositionAssignment.objects.create(
            user=self.alice, position=self.encoder, starts_on=self.today,
        )
        PositionAssignment.objects.create(
            user=self.alice, position=other_encoder, starts_on=self.today,
        )
        self.assertEqual(self.alice.position_assignments.count(), 2)

    def test_a_person_holding_a_position_cannot_be_deleted(self):
        """People are deactivated, never removed - and the assignment is
        what proves who acted on a past request."""
        PositionAssignment.objects.create(
            user=self.alice, position=self.encoder, starts_on=self.today,
        )
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.alice.delete()


class ManualOfficeTests(TestCase):

    def setUp(self):
        self.vp = Office.objects.create(
            name="Vice President for Administration", is_approving_level=True,
        )
        self.accounting = Office.objects.create(name="Accounting Services Office")
        self.manual = Manual.objects.create(
            title="FAM 6.02",
        )

    def test_an_existing_manual_starts_unassigned(self):
        """Every manual in the database predates the organisation, so
        `owning_office` is null until the system admin links it."""
        self.assertIsNone(self.manual.owning_office)

    def test_one_relationship_per_manual_and_office(self):
        ManualOffice.objects.create(
            manual=self.manual, office=self.accounting,
            relationship=ManualOffice.CONCURRING,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ManualOffice.objects.create(
                    manual=self.manual, office=self.accounting,
                    relationship=ManualOffice.READER,
                )

    def test_an_office_with_manuals_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        self.manual.owning_office = self.vp
        self.manual.save()
        with self.assertRaises(ProtectedError):
            self.vp.delete()

    def test_the_approval_route_override_defaults_to_continuing_upward(self):
        """Provisional, pending the QMS office. The default is the
        behaviour the plan describes; the flag is the escape hatch."""
        self.assertFalse(self.manual.approval_stops_at_owner)


class AccessHelperTests(TestCase):
    """Reading and proposing, by position."""

    def setUp(self):
        today = timezone.localdate()
        vp = Office.objects.create(name="VP Office", abbreviation="VP", is_approving_level=True)
        self.finance = Office.objects.create(name="Finance Office", abbreviation="FIN", parent=vp)
        series = ManualSeries.objects.create(code="FAM", title="Finance", owning_office=vp)
        ManualSeriesOffice.objects.create(
            series=series, office=self.finance, relationship=OfficeLink.CONCURRING,
        )

        self.admin = CustomUser.objects.create_user(
            username="acc-admin", password="pw", role="admin", is_approved=True,
        )
        self.staff = CustomUser.objects.create_user(
            username="acc-staff", password="pw", role="staff",
            is_approved=True,
        )
        position, _ = Position.objects.get_or_create(office=self.finance, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=self.staff, position=position, starts_on=today)
        self.homeless = CustomUser.objects.create_user(
            username="acc-nobody", password="pw", role="staff", is_approved=True,
        )

        self.ours = Manual.objects.create(title="FAM 6.02", series=series)
        self.theirs = Manual.objects.create(title="HRM 4.01")

    def test_offices_for_returns_the_current_offices(self):
        self.assertEqual(access.offices_for(self.staff), [self.finance])
        self.assertEqual(access.offices_for(self.homeless), [])

    def test_reaching_is_scoped_to_my_offices(self):
        self.assertTrue(access.can_reach(self.staff, self.ours))
        self.assertFalse(access.can_reach(self.staff, self.theirs))

    def test_an_admin_reaches_everything(self):
        self.assertTrue(access.can_reach(self.admin, self.ours))
        self.assertTrue(access.can_reach(self.admin, self.theirs))

    def test_an_admin_may_not_propose(self):
        """Reading and proposing are not the same rule. Proposing is an
        office's act, and an admin is not an office."""
        self.assertFalse(access.can_propose(self.admin, self.ours))
        self.assertFalse(access.can_propose(self.admin, self.theirs))

    def test_is_staff_grants_nothing(self):
        """Django's flag is for the /admin/ site. It used to be a
        cross-department escape hatch, which meant any account made with
        createsuperuser silently bypassed scoping."""
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.assertFalse(access.can_reach(self.staff, self.theirs))
        self.assertFalse(access.can_propose(self.staff, self.theirs))

    def test_someone_with_no_office_reaches_nothing(self):
        self.assertFalse(access.can_reach(self.homeless, self.ours))
        self.assertEqual(
            access.manuals_for(self.homeless, Manual.objects.all()).count(), 0,
        )

    def test_a_null_manual_or_section_is_refused_rather_than_raising(self):
        self.assertFalse(access.can_reach(self.staff, None))
        self.assertFalse(access.can_reach_section(self.staff, None))
        self.assertFalse(access.can_propose(self.staff, None))

    def test_queryset_narrowing_matches_the_single_object_answer(self):
        """If the list and the gate ever disagree, a screen shows a manual
        that then refuses to open."""
        visible = set(
            access.manuals_for(self.staff, Manual.objects.all())
            .values_list("pk", flat=True)
        )
        expected = {
            m.pk for m in Manual.objects.all()
            if access.can_reach(self.staff, m)
        }
        self.assertEqual(visible, expected)
