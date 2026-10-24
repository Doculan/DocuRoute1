"""Migrations 0042-0044 on notifications written before Phase 2A.

Builds the old shape at 0041 - a notification that is only a user and an
audit event - then migrates forward and checks what each row became, and
that the system log starts with one honest `log_started` row rather than
back-filled history.
"""

from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from api.testing import KeepsMigrationData, migrate_to_latest

BEFORE = [('api', '0041_proposal_status_updated_at_indexes')]
AFTER = [('api', '0044_notification_constraints')]


class BackfillTests(KeepsMigrationData, TransactionTestCase):

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def setUp(self):
        old = self.migrate(BEFORE)
        Office = old.get_model('api', 'Office')
        User = old.get_model('api', 'CustomUser')
        Position = old.get_model('api', 'Position')
        Assignment = old.get_model('api', 'PositionAssignment')
        Series = old.get_model('api', 'ManualSeries')
        Manual = old.get_model('api', 'Manual')
        Proposal = old.get_model('api', 'Proposal')
        Version = old.get_model('api', 'ProposalVersion')
        Participant = old.get_model('api', 'ProposalParticipant')
        Concurrence = old.get_model('api', 'Concurrence')
        AuditEvent = old.get_model('api', 'AuditEvent')
        Notification = old.get_model('api', 'Notification')

        vp = Office.objects.create(name='VP', is_approving_level=True)
        acc = Office.objects.create(name='Accounting Office', parent=vp)
        bud = Office.objects.create(name='Budget Office', parent=vp)

        def person(name, office, kind):
            user = User.objects.create(username=name)
            position = Position.objects.create(office=office, kind=kind)
            Assignment.objects.create(user=user, position=position, starts_on=date(2026, 1, 1),
                                      sole_holder=kind == 'head')
            return user

        acc_head = person('acc_head', acc, 'head')
        bud_head = person('bud_head', bud, 'head')
        bud_enc = person('bud_enc', bud, 'encoder')
        manual = Manual.objects.create(title='FAM 6.02', file='x.pdf', series=Series.objects.create(
            code='FAM', title='Finance', owning_office=vp))
        proposal = Proposal.objects.create(manual=manual, initiating_office=acc,
                                           status='concurrence', created_by=acc_head)
        version = Version.objects.create(proposal=proposal, number=1)
        Participant.objects.create(proposal=proposal, office=bud, office_name_at_time=bud.name,
                                   role='concurring')
        submitted = AuditEvent.objects.create(
            proposal=proposal, version=version, event='submitted', actor=acc_head,
            office=acc, office_name_at_time=acc.name)
        Concurrence.objects.create(version=version, office=bud, decision='concur',
                                   recorded_by=bud_head)
        concurred = AuditEvent.objects.create(
            proposal=proposal, version=version, event='concurred', actor=bud_head,
            office=bud, office_name_at_time=bud.name)
        Notification.objects.create(user=bud_head, event=submitted)
        Notification.objects.create(user=bud_enc, event=submitted)
        Notification.objects.create(user=acc_head, event=concurred)
        self.ids = {'bud_head': bud_head.pk, 'bud_enc': bud_enc.pk, 'acc_head': acc_head.pk,
                    'submitted': submitted.pk, 'manual': manual.pk}

    def tearDown(self):
        migrate_to_latest()

    def test_each_old_notification_becomes_a_complete_one(self):
        new = self.migrate(AFTER)
        Notification = new.get_model('api', 'Notification')
        SystemEvent = new.get_model('api', 'SystemEvent')

        head = Notification.objects.get(recipient_id=self.ids['bud_head'])
        self.assertEqual((head.kind, head.severity), ('concurrence_requested', 'action'))
        self.assertEqual(head.title, 'Accounting Office asks your office to concur on FAM 6.02')
        self.assertEqual(head.addressed_position_title, 'Budget Office — Head')
        self.assertEqual(head.dedupe_key, f"audit:{self.ids['submitted']}")
        self.assertEqual(head.manual_id, self.ids['manual'])
        # Budget concurred, so the Head's request is done - by whom is not
        # recorded for rows written before the log.
        self.assertIsNotNone(head.acted_at)
        self.assertIsNone(head.acted_by_id)

        encoder = Notification.objects.get(recipient_id=self.ids['bud_enc'])
        self.assertEqual(encoder.severity, 'info')
        self.assertIsNone(encoder.acted_at)
        concurred = Notification.objects.get(recipient_id=self.ids['acc_head'])
        self.assertEqual((concurred.kind, concurred.title),
                         ('concurred', 'Budget Office concurred on FAM 6.02'))

        log = list(SystemEvent.objects.order_by('seq'))
        self.assertEqual([(e.seq, e.kind, e.actor_label) for e in log],
                         [(1, 'log_started', 'system')])
        self.assertEqual(log[0].detail['notifications_carried_over'], 3)
