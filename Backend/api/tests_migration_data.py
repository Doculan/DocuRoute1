"""A test that commits leaves the database exactly as migrated.

Found in the full suite: the race test in `tests_proposals` flushed the
database after itself, the preset deadline types went with it, and
`seed_scale` failed in a later module. `serialized_rollback` was tried
and was not enough: it reloads too early and drops microseconds, and the
system log's first event then fails its hash. See `api.testing`.
"""

from django.db import connection
from django.test import TestCase

from api import system_log, testing, tests_migration_0043, tests_notices, tests_proposals
from api.models import DeadlineType, LogHead, MonitoringSetting, SystemEvent

# The modules, not the classes: a class imported here would run twice.
COMMITTING = [
    (tests_proposals.SimultaneousStartTests,
     'test_two_simultaneous_requests_make_exactly_one_draft'),
    (tests_migration_0043.BackfillTests,
     'test_each_old_notification_becomes_a_complete_one'),
    (tests_notices.Migration0046,
     'test_dated_items_expire_undated_stay_the_banner_targets_are_kept'),
]


class AfterATestThatCommits(TestCase):

    def flush_after(self, cls, name):
        cls(name)._fixture_teardown()

    def test_the_migrations_rows_are_back(self):
        self.assertEqual(DeadlineType.objects.filter(is_preset=True).count(), 11)
        self.assertTrue(MonitoringSetting.objects.exists())
        self.assertTrue(LogHead.objects.exists())
        for cls, name in COMMITTING:
            with self.subTest(cls.__name__):
                self.flush_after(cls, name)
                self.assertEqual(DeadlineType.objects.filter(is_preset=True).count(), 11)
                self.assertTrue(MonitoringSetting.objects.exists())
                self.assertTrue(LogHead.objects.exists())

    def test_row_for_row(self):
        before = testing.snapshot(connection)
        for cls, name in COMMITTING:
            with self.subTest(cls.__name__):
                self.flush_after(cls, name)
                self.assertEqual(testing.snapshot(connection), before)

    def test_the_system_log_still_verifies(self):
        """A copy that loses microseconds breaks the first event's hash."""
        events = SystemEvent.objects.count()
        self.assertGreater(events, 0)
        for cls, name in COMMITTING:
            with self.subTest(cls.__name__):
                self.flush_after(cls, name)
                self.assertEqual(system_log.verify(), (events, None))
