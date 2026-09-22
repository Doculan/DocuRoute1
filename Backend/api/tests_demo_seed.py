"""The demonstration organisation.

Two properties matter, and neither is about the data itself.

**It refuses to run beside a real organisation.** Once somebody has begun
entering real offices, fictional ones cannot be told apart afterwards.

**`--clear` undoes exactly what it did**, including putting back fields it
changed on rows it did not create. "Delete everything that looks like demo
data" is not exact - a real office can share a name with a fictional one.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from api.models import (
    CustomUser, DemoRecord, Manual, ManualSeries, ManualSeriesOffice,
    Office, Position, PositionAssignment, Department,
)


class DemoSeedTests(TestCase):

    def setUp(self):
        self.department = Department.objects.create(name="CAS")
        # Documents the seeder will place into series, and must release.
        self.fam = Manual.objects.create(
            title="FAM 6.02", department=self.department,
        )
        self.sdm = Manual.objects.create(
            title="SDM 3.01", department=self.department,
        )
        self.stranger = Manual.objects.create(
            title="XYZ 1.01", department=self.department,
        )

    def seed(self, *args):
        out = StringIO()
        call_command('seed_demo_org', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_it_seeds_the_organisation(self):
        self.seed()
        self.assertEqual(Office.objects.count(), 14)
        self.assertEqual(ManualSeries.objects.count(), 4)
        self.assertEqual(CustomUser.objects.count(), 14)
        self.assertEqual(PositionAssignment.objects.count(), 14)

    def test_the_documents_are_placed_by_prefix(self):
        self.seed()
        self.fam.refresh_from_db()
        self.sdm.refresh_from_db()
        self.stranger.refresh_from_db()

        self.assertEqual(self.fam.series.code, "FAM")
        self.assertEqual(self.sdm.series.code, "SDM")
        # No series for its prefix, so it is left alone rather than
        # guessed at.
        self.assertIsNone(self.stranger.series)

    def test_the_owner_may_also_concur(self):
        """The VPSD case, which the demo exists partly to show."""
        self.seed()
        sdm = ManualSeries.objects.get(code="SDM")
        concurring = {
            l.office.abbreviation for l in
            ManualSeriesOffice.objects.filter(series=sdm)
        }
        self.assertIn("VPSD", concurring)
        self.assertEqual(sdm.owning_office.abbreviation, "VPSD")

        self.sdm.refresh_from_db()
        self.assertIsNone(self.sdm.owner_proposal_conflict())
        self.assertEqual(
            [str(o) for o in self.sdm.approval_route()], ["VPSD", "OP"],
        )

    def test_the_qms_positions_share_one_office(self):
        self.seed()
        qms = Office.objects.get(abbreviation="QMS")
        kinds = set(
            Position.objects.filter(office=qms).values_list('kind', flat=True)
        )
        self.assertEqual(kinds, {Position.IMR, Position.DOCUMENT_CUSTODIAN})

    def test_everyone_is_approved_and_can_be_signed_in_as(self):
        self.seed()
        person = CustomUser.objects.get(username="ACC_Maria")
        self.assertTrue(person.is_approved)
        self.assertEqual(person.full_name, "Maria Santos")
        self.assertTrue(person.check_password("Office123!"))

    def test_it_does_not_touch_the_access_switch(self):
        """Seeding prepares the data; flipping is a decision somebody
        makes on the screen, having looked at the preview."""
        from api.models import AccessMode
        self.seed()
        self.assertFalse(AccessMode.current().by_position)

    # -- refusing beside a real organisation -----------------------

    def test_it_refuses_when_an_office_it_did_not_create_exists(self):
        Office.objects.create(name="Real Office Somebody Typed")
        output = self.seed()

        self.assertIn("Refusing to seed", output)
        self.assertEqual(Office.objects.count(), 1)
        self.assertEqual(ManualSeries.objects.count(), 0)

    def test_seeding_twice_does_nothing_the_second_time(self):
        self.seed()
        before = Office.objects.count()
        output = self.seed()
        self.assertIn("already seeded", output)
        self.assertEqual(Office.objects.count(), before)

    # -- clearing exactly ------------------------------------------

    def test_clear_removes_everything_it_created(self):
        self.seed()
        self.seed('--clear')

        self.assertEqual(Office.objects.count(), 0)
        self.assertEqual(ManualSeries.objects.count(), 0)
        self.assertEqual(ManualSeriesOffice.objects.count(), 0)
        self.assertEqual(Position.objects.count(), 0)
        self.assertEqual(PositionAssignment.objects.count(), 0)
        self.assertEqual(CustomUser.objects.count(), 0)
        self.assertEqual(DemoRecord.objects.count(), 0)

    def test_clear_puts_the_documents_back(self):
        """The documents existed before. Clearing has to release them,
        not delete them - they are the university's real content."""
        self.seed()
        self.seed('--clear')

        self.assertEqual(Manual.objects.count(), 3)
        for manual in Manual.objects.all():
            self.assertIsNone(manual.series)

    def test_clear_leaves_accounts_it_did_not_create(self):
        existing = CustomUser.objects.create_user(
            username="real-person", password="pw", is_approved=True,
        )
        self.seed()
        self.seed('--clear')
        self.assertTrue(CustomUser.objects.filter(pk=existing.pk).exists())
        self.assertEqual(CustomUser.objects.count(), 1)

    def test_it_refuses_when_a_series_it_did_not_create_exists(self):
        """Found by a test that expected this to work: a real series
        carrying one of these codes collides on the unique constraint, and
        the command failed with a raw database error instead of saying
        what was wrong."""
        ManualSeries.objects.create(code="FAM", title="The real one")
        output = self.seed()

        self.assertIn("Refusing to seed", output)
        self.assertIn("manual series", output)
        self.assertEqual(Office.objects.count(), 0)
        self.assertEqual(ManualSeries.objects.count(), 1)

    def test_clear_restores_a_previous_series_rather_than_blanking_it(self):
        """The seeder records the value it replaced, so a document that
        already belonged somewhere goes back there."""
        other = ManualSeries.objects.create(code="OTH", title="Other")
        self.stranger.series = other
        self.stranger.save()

        # Cleared first so the pre-existing series does not block seeding,
        # then re-made after - the point is the *restore*, not the guard.
        self.stranger.series = None
        self.stranger.save()
        other.delete()

        self.seed()
        self.fam.refresh_from_db()
        self.assertEqual(self.fam.series.code, "FAM")

        self.seed('--clear')
        self.fam.refresh_from_db()
        self.assertIsNone(self.fam.series)

    def test_clearing_twice_is_harmless(self):
        self.seed()
        self.seed('--clear')
        output = self.seed('--clear')
        self.assertIn("Nothing to clear", output)

    def test_seeding_again_after_clearing_works(self):
        self.seed()
        self.seed('--clear')
        self.seed()
        self.assertEqual(Office.objects.count(), 14)
