"""run_monitoring: stalls, vacancies, the run lock and the system log.

Proposals are built directly in the database and back-dated, so no test
waits on an AI check. The rules with teeth:

- **Idempotent**: a second run tells nobody twice.
- **The lock** stops a second run while one holds it, expires by itself,
  and is extended after every batch.
- **Stalls and vacancies clear** when the thing stops being true.
- **The system log is append-only and tamper-evident.**

Tests that expect an error assert the reason.
"""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from api import monitoring, system_log
from api.models import (
    AuditEvent, Concurrence, CustomUser, JobLock, JobRun, Manual, ManualSeries,
    ManualSeriesOffice, MonitoringSetting, Notification, Office, OfficeLink,
    Position, PositionAssignment, Proposal, ProposalParticipant, ProposalVersion,
    SystemEvent,
)


class MonitoringFixture(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        self.now = timezone.now()
        self.vpaf = Office.objects.create(name='VP Finance', abbreviation='VPAF',
                                          is_approving_level=True)
        self.acc = Office.objects.create(name='Accounting Office', abbreviation='ACC',
                                         parent=self.vpaf)
        self.bud = Office.objects.create(name='Budget Office', abbreviation='BUD',
                                         parent=self.vpaf)
        self.cash = Office.objects.create(name='Cash Office', abbreviation='CMO',
                                          parent=self.vpaf)
        series = ManualSeries.objects.create(code='FAM', title='Finance', owning_office=self.vpaf)
        for office in (self.acc, self.bud, self.cash):
            ManualSeriesOffice.objects.create(series=series, office=office,
                                              relationship=OfficeLink.CONCURRING)
        self.manual = Manual.objects.create(title='FAM 6.02', series=series)

        self.vp_head = self.person('vp_head', self.vpaf, Position.HEAD)
        self.acc_head = self.person('acc_head', self.acc, Position.HEAD)
        self.acc_enc = self.person('acc_enc', self.acc, Position.ENCODER)
        self.bud_head = self.person('bud_head', self.bud, Position.HEAD)
        self.bud_enc = self.person('bud_enc', self.bud, Position.ENCODER)
        self.cash_head = self.person('cash_head', self.cash, Position.HEAD)
        self.admin = CustomUser.objects.create_user(
            username='admin', password='x', role='admin', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN)

    def person(self, username, office, kind, starts=None):
        user = CustomUser.objects.create_user(username=username, password='x', is_approved=True)
        position, _ = Position.objects.get_or_create(office=office, kind=kind)
        PositionAssignment.objects.create(user=user, position=position,
                                          starts_on=starts or self.today)
        return user

    def in_concurrence(self, days_ago):
        """A proposal submitted `days_ago` days ago, both other offices to concur."""
        proposal = Proposal.objects.create(manual=self.manual, initiating_office=self.acc,
                                           status=Proposal.CONCURRENCE, created_by=self.acc_enc)
        version = ProposalVersion.objects.create(proposal=proposal, number=1)
        for office in (self.bud, self.cash):
            ProposalParticipant.objects.create(
                proposal=proposal, office=office, office_name_at_time=office.name,
                role=ProposalParticipant.CONCURRING)
        event = AuditEvent.objects.create(
            proposal=proposal, version=version, event=AuditEvent.SUBMITTED,
            actor=self.acc_head, office=self.acc, office_name_at_time=self.acc.name)
        AuditEvent.objects.filter(pk=event.pk).update(at=self.now - timedelta(days=days_ago))
        return proposal

    def stalled(self, user):
        return Notification.objects.filter(recipient=user, kind=Notification.STALLED)


class Stalls(MonitoringFixture):

    def test_a_proposal_past_its_threshold_notifies_whoever_holds_it(self):
        proposal = self.in_concurrence(days_ago=8)

        counts = monitoring.run()

        self.assertEqual(counts['stalls_flagged'], 1)
        for user, severity in ((self.bud_head, 'action'), (self.bud_enc, 'info'),
                               (self.cash_head, 'action'),
                               (self.acc_head, 'info'), (self.acc_enc, 'info')):
            notice = self.stalled(user).get()
            self.assertEqual(notice.severity, severity, user.username)
            self.assertEqual(notice.proposal, proposal)
        notice = self.stalled(self.bud_head).get()
        self.assertEqual(notice.title, 'FAM 6.02: 8 days in concurrence')
        self.assertEqual(notice.body, 'Waiting on Budget Office, Cash Office. The limit is 7 days.')
        stalled = SystemEvent.objects.get(kind=SystemEvent.STALLED)
        self.assertEqual(stalled.actor_label, 'system')
        self.assertIsNone(stalled.actor)
        self.assertEqual(notice.system_event, stalled)

    def test_nothing_is_flagged_inside_the_threshold(self):
        self.in_concurrence(days_ago=6)
        self.assertEqual(monitoring.run()['stalls_flagged'], 0)
        self.assertFalse(Notification.objects.exists())

    def test_the_threshold_is_the_admins_setting(self):
        self.in_concurrence(days_ago=4)
        MonitoringSetting.objects.update_or_create(stage='concurrence', defaults={'days': 3})
        self.assertEqual(monitoring.run()['stalls_flagged'], 1)

    def test_a_second_run_tells_nobody_twice(self):
        self.in_concurrence(days_ago=8)
        monitoring.run()
        notices, events = Notification.objects.count(), SystemEvent.objects.count()

        self.assertEqual(monitoring.run()['stalls_flagged'], 0)
        self.assertEqual(Notification.objects.count(), notices)
        self.assertEqual(SystemEvent.objects.count(), events)

    def test_an_office_concurring_clears_its_own_stall_notice(self):
        from api import notifications
        proposal = self.in_concurrence(days_ago=8)
        monitoring.run()
        version = proposal.current_version()
        Concurrence.objects.create(version=version, office=self.bud,
                                   decision=Concurrence.CONCUR, recorded_by=self.bud_head)
        notifications.notify(AuditEvent.objects.create(
            proposal=proposal, version=version, event=AuditEvent.CONCURRED,
            actor=self.bud_head, office=self.bud, office_name_at_time=self.bud.name))

        self.assertEqual(self.stalled(self.bud_head).get().acted_by, self.bud_head)
        self.assertIsNone(self.stalled(self.cash_head).get().acted_at)

    def test_leaving_the_stage_clears_the_stall_on_the_next_run(self):
        proposal = self.in_concurrence(days_ago=8)
        monitoring.run()
        Proposal.objects.filter(pk=proposal.pk).update(status=Proposal.WITHDRAWN)

        self.assertEqual(monitoring.run()['stalls_cleared'], 2)
        notice = self.stalled(self.cash_head).get()
        self.assertIsNotNone(notice.acted_at)
        self.assertIsNone(notice.acted_by)
        acted = SystemEvent.objects.filter(kind=SystemEvent.NOTIFICATION_ACTED).last()
        self.assertEqual(acted.actor_label, 'system')
        self.assertEqual(acted.detail['reason'], 'left the stage')


class Vacancies(MonitoringFixture):

    def end(self, user):
        assignment = user.position_assignments.get()
        assignment.starts_on = self.today - timedelta(days=30)
        assignment.ends_on = self.today - timedelta(days=3)
        assignment.save()

    def test_a_head_post_with_nobody_in_it_tells_the_parent_head_and_the_admin(self):
        self.end(self.bud_head)

        self.assertEqual(monitoring.run()['vacancies_flagged'], 1)

        for user in (self.vp_head, self.admin):
            notice = Notification.objects.get(recipient=user, kind=Notification.POSITION_VACANT)
            self.assertEqual(notice.severity, 'action')
            self.assertTrue(notice.office_level)
            self.assertIsNone(notice.manual)
            self.assertEqual(notice.title, 'Budget Office — Head has no holder')
        self.assertEqual(Notification.objects.get(recipient=self.admin).addressed_position_title,
                         'System administrator')
        self.assertEqual(monitoring.run()['vacancies_flagged'], 0)

    def test_filling_the_post_clears_it(self):
        self.end(self.bud_head)
        monitoring.run()
        self.person('new_head', self.bud, Position.HEAD)

        self.assertEqual(monitoring.run()['vacancies_cleared'], 2)
        self.assertFalse(Notification.objects.filter(
            kind=Notification.POSITION_VACANT, acted_at__isnull=True).exists())

    def test_a_vacancy_at_the_top_still_reaches_the_admin(self):
        self.end(self.vp_head)
        monitoring.run()
        notified = set(Notification.objects.filter(
            kind=Notification.POSITION_VACANT).values_list('recipient', flat=True))
        self.assertEqual(notified, {self.admin.pk})


class TheRunLock(MonitoringFixture):

    def test_a_held_lock_stops_a_second_run(self):
        JobLock.objects.update_or_create(name='monitoring', defaults={
            'holder': 'elsewhere', 'expires_at': timezone.now() + timedelta(minutes=5)})
        self.in_concurrence(days_ago=8)

        self.assertIsNone(monitoring.run())
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(JobRun.objects.exists())
        out = StringIO()
        call_command('run_monitoring', stdout=out)
        self.assertIn('Another run holds the lock', out.getvalue())

    def test_an_expired_lock_is_taken_and_released(self):
        JobLock.objects.update_or_create(name='monitoring', defaults={
            'holder': 'crashed', 'expires_at': timezone.now() - timedelta(seconds=1)})

        self.assertIsNotNone(monitoring.run())
        lock = JobLock.objects.get(name='monitoring')
        self.assertNotEqual(lock.holder, 'crashed')
        self.assertLessEqual(lock.expires_at, timezone.now())
        self.assertIsNotNone(JobRun.objects.get().finished_at)

    def test_the_lock_is_extended_after_every_batch(self):
        for _ in range(3):
            self.manual = Manual.objects.create(title=f'FAM {_}', series=self.manual.series)
            self.in_concurrence(days_ago=8)
        extended = []
        real = monitoring.extend
        with patch.object(monitoring, 'BATCH', 1), \
                patch.object(monitoring, 'extend', side_effect=lambda h: (extended.append(h), real(h))):
            monitoring.run(only=['stalls'])
        self.assertEqual(len(extended), 3)

    def test_a_dashboard_runs_the_steps_only_when_the_scheduler_has_not(self):
        self.in_concurrence(days_ago=8)
        JobRun.objects.create(started_at=timezone.now(), finished_at=timezone.now())
        self.assertIsNone(monitoring.maybe_run_for())
        self.assertFalse(Notification.objects.exists())

        JobRun.objects.update(finished_at=timezone.now() - timedelta(minutes=20))
        self.assertEqual(monitoring.maybe_run_for([self.bud])['stalls_flagged'], 1)
        self.assertEqual(JobRun.objects.latest('started_at').trigger, JobRun.DASHBOARD)


class TheSystemLog(MonitoringFixture):

    def test_the_chain_verifies(self):
        before = SystemEvent.objects.count()     # log_started, unless flushed
        for _ in range(3):
            system_log.record(SystemEvent.STALLED, detail={'n': _})
        out = StringIO()
        call_command('verify_log', 'system', stdout=out)
        self.assertIn(f'Chain intact: {before + 3} row(s)', out.getvalue())

    def test_an_edited_row_breaks_the_chain_where_it_was_edited(self):
        events = [system_log.record(SystemEvent.STALLED, detail={'n': n}) for n in range(3)]
        SystemEvent.objects.filter(pk=events[1].pk).update(detail={'n': 99})

        with self.assertRaises(CommandError) as raised:
            call_command('verify_log', 'system', stdout=StringIO())
        self.assertIn(f'seq {events[1].seq} was changed after it was written',
                      str(raised.exception))

    def test_a_deleted_row_breaks_the_chain(self):
        events = [system_log.record(SystemEvent.STALLED) for _ in range(3)]
        SystemEvent.objects.filter(pk=events[1].pk).delete()
        self.assertEqual(system_log.verify()[1], f'seq {events[1].seq} is missing (found {events[2].seq})')

    def test_a_lost_chain_head_is_rebuilt_from_the_last_row(self):
        """Found in the full suite: a test that flushes the database took
        the head row the migration seeded, and every later write failed."""
        from api.models import LogHead
        last = system_log.record(SystemEvent.STALLED)
        LogHead.objects.all().delete()

        following = system_log.record(SystemEvent.STALLED)

        self.assertEqual(following.seq, last.seq + 1)
        self.assertEqual(following.prev_hash, last.hash)
        self.assertEqual(system_log.verify()[1], None)

    def test_rows_cannot_be_saved_twice(self):
        event = system_log.record(SystemEvent.STALLED)
        event.detail = {'changed': True}
        with self.assertRaises(ValueError) as raised:
            event.save()
        self.assertIn('append-only', str(raised.exception))

    def test_the_system_is_a_label_never_a_person(self):
        head = system_log.record(SystemEvent.STALLED)
        bad = SystemEvent(seq=head.seq + 1, kind=SystemEvent.STALLED, actor=None,
                          actor_label='QMS Office — IMR', at=timezone.now(),
                          prev_hash=head.hash, hash='f' * 64)
        with self.assertRaises(IntegrityError) as raised, transaction.atomic():
            bad.save(force_insert=True)
        self.assertIn('system_event_actor_or_system_label', str(raised.exception))
