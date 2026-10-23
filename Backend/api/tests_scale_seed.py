"""The scale harness (`seed_scale`).

Run at a small fraction: the point here is its safety, not its size.

**It refuses beside real data**, the demo organisation included, and says
why. **`--clear` removes exactly its own rows**, and the demo seeder's
clear leaves them alone - both used to share one unlabelled record table.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from api.models import (
    AuditEvent, CustomUser, DemoRecord, Manual, ManualSeries, Notification,
    Office, Proposal, SectionChange,
)

FRACTION = '0.02'


class ScaleSeedTests(TestCase):

    def run_command(self, name, *args):
        out = StringIO()
        call_command(name, *args, stdout=out, stderr=out)
        return out.getvalue()

    def seed(self, *args):
        return self.run_command('seed_scale', '--fraction', FRACTION, *args)

    def test_it_refuses_beside_a_real_office(self):
        Office.objects.create(name='Accounting Office')

        output = self.seed()

        self.assertIn(
            'Refusing to seed: 1 offices exist that this command did not create',
            output,
        )
        self.assertEqual(Office.objects.count(), 1)
        self.assertFalse(Manual.objects.exists())
        self.assertFalse(DemoRecord.objects.exists())

    def test_it_refuses_beside_a_real_manual(self):
        Manual.objects.create(title='FAM 6.02')

        output = self.seed()

        self.assertIn(
            'Refusing to seed: 1 manuals exist that this command did not create',
            output,
        )
        self.assertFalse(Office.objects.exists())

    def test_it_refuses_beside_the_demo_organisation(self):
        self.run_command('seed_demo_org')
        offices = Office.objects.count()

        output = self.seed()

        self.assertIn('offices exist that this command did not create', output)
        self.assertEqual(Office.objects.count(), offices)

    def test_it_refuses_to_seed_twice(self):
        self.seed()
        proposals = Proposal.objects.count()

        output = self.seed()

        self.assertIn('Scale data is already seeded', output)
        self.assertEqual(Proposal.objects.count(), proposals)

    def test_it_seeds_every_status_with_a_trail(self):
        self.seed()

        statuses = set(Proposal.objects.values_list('status', flat=True))
        self.assertEqual(statuses, {value for value, _ in Proposal.STATUS_CHOICES})
        self.assertTrue(Notification.objects.filter(read_at__isnull=True).exists())
        self.assertTrue(AuditEvent.objects.filter(event=AuditEvent.RETURNED).exists())
        # Frozen requests still hold their sections, as the real ones do.
        self.assertTrue(SectionChange.objects.filter(
            is_open=True, version__proposal__status=Proposal.WITH_CUSTODIAN,
        ).exists())
        # Proposals and their trail age: not everything happened today.
        month_ago = timezone.now() - timedelta(days=30)
        self.assertTrue(Proposal.objects.filter(created_at__lt=month_ago).exists())
        self.assertTrue(AuditEvent.objects.filter(at__lt=month_ago).exists())

    def test_clear_removes_exactly_what_it_created(self):
        admin = CustomUser.objects.create_user(
            username='measuring_admin', password='x', role='admin',
        )
        self.seed()
        self.assertTrue(Proposal.objects.exists())

        output = self.seed('--clear')

        self.assertIn('Removed', output)
        for model in (Office, ManualSeries, Manual, Proposal, AuditEvent):
            self.assertFalse(model.objects.exists(), model.__name__)
        self.assertEqual(list(CustomUser.objects.all()), [admin])
        self.assertFalse(DemoRecord.objects.exists())

    def test_clearing_the_demo_organisation_leaves_scale_data(self):
        self.seed()
        offices = Office.objects.count()

        output = self.run_command('seed_demo_org', '--clear')

        self.assertIn('Nothing to clear', output)
        self.assertEqual(Office.objects.count(), offices)
        self.assertEqual(
            DemoRecord.objects.exclude(source=DemoRecord.SCALE).count(), 0,
        )
