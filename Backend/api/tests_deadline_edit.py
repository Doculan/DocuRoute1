"""Editing a deadline (admin): fields, targets and priority manuals.

Removing never deletes: an office no longer targeted has its open
obligation cancelled, its notices cleared, and is told. A cancelled
obligation drops out of every count, list and tag, and is reopened if the
office is targeted again. The audit entry keeps old and new values.
"""

import datetime

from api import deadline_tags, deadlines
from api.models import DeadlineObligation, DeadlineTarget, Notification, SystemEvent

from .tests_notices import DeadlineFixture

OFFICE = DeadlineTarget.OFFICE


class EditingTargets(DeadlineFixture):

    def setUp(self):
        super().setUp()
        self.made = self.deadline(DeadlineTarget(kind=OFFICE, office=self.acc),
                                  DeadlineTarget(kind=OFFICE, office=self.bud))
        self.client = self.as_(self.admin)

    def patch(self, **data):
        return self.client.patch(f'/api/admin/deadlines/{self.made.pk}/', data, format='json')

    def only_budget(self, **more):
        return self.patch(targets=[{'kind': OFFICE, 'office_id': self.bud.pk}], **more)

    def test_a_removed_office_is_cancelled_not_deleted(self):
        before = self.made.obligations.get(office=self.acc).pk
        self.assertEqual(self.only_budget().status_code, 200)
        row = DeadlineObligation.objects.get(pk=before)
        self.assertEqual(row.state, DeadlineObligation.CANCELLED)
        self.made.refresh_from_db()
        self.assertEqual(self.made.obligations_open, 1)    # Budget's alone

    def test_its_notice_clears_and_it_is_told(self):
        self.only_budget()
        old = Notification.objects.get(recipient=self.acc_head, kind=Notification.DEADLINE_SET,
                                        dedupe_key=f'deadline:{self.made.pk}:set')
        self.assertIsNotNone(old.acted_at)
        told = Notification.objects.get(recipient=self.acc_head,
                                        dedupe_key__startswith=f'deadline:{self.made.pk}:removed')
        self.assertEqual(told.title, 'ISO surveillance audit no longer applies to your office')
        self.assertEqual(told.severity, Notification.INFO)
        # Budget, still targeted, keeps its notice open and is not told.
        self.assertIsNone(Notification.objects.get(recipient=self.bud_head).acted_at)

    def test_adding_it_back_reopens_the_same_obligation_and_tells_it_again(self):
        before = self.made.obligations.get(office=self.acc).pk
        self.only_budget()
        self.patch(targets=[{'kind': OFFICE, 'office_id': self.bud.pk},
                            {'kind': OFFICE, 'office_id': self.acc.pk}])
        row = self.made.obligations.get(office=self.acc)
        self.assertEqual((row.pk, row.state), (before, DeadlineObligation.OPEN))
        fresh = Notification.objects.filter(recipient=self.acc_head, kind=Notification.DEADLINE_SET,
                                            acted_at__isnull=True, dedupe_key__contains=':set')
        self.assertEqual(fresh.count(), 1)
        self.assertTrue(fresh.get().title.startswith('ISO surveillance audit — due'))

    def test_a_met_obligation_stays_met(self):
        deadlines.on_submitted(self.proposal(self.acc, self.m1), self.acc_head)
        self.only_budget()
        self.assertEqual(self.made.obligations.get(office=self.acc).state,
                         DeadlineObligation.SUBMITTED)
        self.assertFalse(Notification.objects.filter(
            recipient=self.acc_head, dedupe_key__contains=':removed').exists())

    def test_the_audit_entry_keeps_old_and_new_values(self):
        due = self.today + datetime.timedelta(days=40)
        self.only_budget(title='ISO audit', due_on=due.isoformat(), reminder_days=[10, 3])
        event = SystemEvent.objects.filter(kind=SystemEvent.DEADLINE_CHANGED).latest('seq')
        detail = event.detail
        self.assertEqual(detail['fields'], ['due_on', 'reminder_days', 'targets', 'title'])
        self.assertEqual(detail['old']['title'], 'ISO surveillance audit')
        self.assertEqual(detail['new']['title'], 'ISO audit')
        self.assertEqual(detail['new']['due_on'], due.isoformat())
        self.assertEqual(detail['new']['reminder_days'], [10, 3])
        self.assertEqual(detail['old']['targets'], ['Accounting Office', 'Budget Office'])
        self.assertEqual(detail['new']['targets'], ['Budget Office'])
        self.assertEqual((detail['offices_added'], detail['offices_removed']), ([], [self.acc.pk]))
        self.assertEqual(event.actor, self.admin)
        # One entry for the edit: the removal notice hangs from it.
        told = Notification.objects.get(recipient=self.acc_head, dedupe_key__contains=':removed')
        self.assertEqual(told.system_event, event)

    def test_unchanged_values_are_left_out(self):
        self.patch(title='ISO surveillance audit', note='Bring the folder')
        detail = SystemEvent.objects.filter(kind=SystemEvent.DEADLINE_CHANGED).latest('seq').detail
        self.assertEqual(detail['fields'], ['note'])
        self.assertEqual(detail['old'], {'note': ''})

    def test_the_preview_names_offices_and_saves_nothing(self):
        response = self.patch(targets=[{'kind': OFFICE, 'office_id': self.bud.pk},
                                       {'kind': OFFICE, 'office_id': self.cash.pk}], preview=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['offices_added'], ['Cash Unit'])
        self.assertEqual(response.data['offices_removed'], ['Accounting Office'])
        self.assertEqual(response.data['offices'], 2)
        self.assertEqual(self.made.obligations.get(office=self.acc).state, DeadlineObligation.OPEN)
        self.assertFalse(self.made.obligations.filter(office=self.cash).exists())
        self.assertFalse(SystemEvent.objects.filter(kind=SystemEvent.DEADLINE_CHANGED).exists())

    def test_targets_are_refused_after_the_due_date(self):
        type(self.made).objects.filter(pk=self.made.pk).update(
            due_on=self.today - datetime.timedelta(days=1))
        response = self.only_budget()
        self.assertEqual((response.status_code, response.data['reason']), (400, 'past_due'))


class CancelledDropsOut(DeadlineFixture):
    """A cancelled obligation counts nowhere."""

    def setUp(self):
        super().setUp()
        self.made = self.deadline(DeadlineTarget(kind='manual', manual=self.m1),
                                  DeadlineTarget(kind='manual', manual=self.m9))
        self.made.targets.filter(manual=self.m1).delete()
        deadlines.materialise(self.made, self.admin)
        self.made.refresh_from_db()

    def test_from_the_admin_detail_and_offices_list(self):
        client = self.as_(self.admin)
        detail = client.get(f'/api/admin/deadlines/{self.made.pk}/').data
        self.assertEqual(sum(b['open'] + b['met'] for b in detail['by_branch']), 1)
        rows = client.get(f'/api/admin/deadlines/{self.made.pk}/obligations/',
                          {'branch': self.vp.pk}).data
        self.assertEqual([r['office'] for r in rows['obligations']], ['Budget Office'])

    def test_from_the_office_page_and_the_tags(self):
        mine = self.as_(self.acc_head).get('/api/my-deadlines/').data
        self.assertEqual(mine['count'], 0)
        self.assertEqual(deadline_tags.deadline_tags_for(self.acc_head, [self.m1.pk]), {})

    def test_from_monitoring(self):
        counts = self.as_(self.admin).get('/api/monitoring/offices/', {'show': 'all'}).data
        acc = next((r for r in counts['offices'] if r['id'] == self.acc.pk), None)
        self.assertTrue(acc is None or acc['own']['unmet'] == 0)


class EditingPriority(DeadlineFixture):

    def setUp(self):
        super().setUp()
        self.made = self.deadline(DeadlineTarget(kind='manual', manual=self.m1))
        self.client = self.as_(self.admin)

    def priority(self, manuals, **more):
        return self.client.post(f'/api/admin/deadlines/{self.made.pk}/priority/',
                                {'office_id': self.acc.pk, 'manual_ids': [m.pk for m in manuals],
                                 **more}, format='json')

    def test_unsetting_keeps_a_targeted_obligation_open(self):
        self.priority([self.m1])
        self.assertEqual(self.priority([self.m1], priority=False).data, {'unset': 1})
        row = self.made.obligations.get(office=self.acc, manual=self.m1)
        self.assertEqual((row.priority, row.state), (False, DeadlineObligation.OPEN))

    def test_unsetting_cancels_one_only_the_priority_made(self):
        self.priority([self.m2])
        self.priority([self.m2], priority=False)
        row = self.made.obligations.get(office=self.acc, manual=self.m2)
        self.assertEqual((row.priority, row.state), (False, DeadlineObligation.CANCELLED))

    def test_making_a_cancelled_pair_priority_reopens_it(self):
        self.priority([self.m2])
        self.priority([self.m2], priority=False)
        response = self.priority([self.m2])
        self.assertEqual(response.data, {'priority': 1, 'open': 1})
        row = self.made.obligations.get(office=self.acc, manual=self.m2)
        self.assertEqual((row.priority, row.state), (True, DeadlineObligation.OPEN))


class EditingPastDue(DeadlineFixture):

    def test_a_past_deadline_keeps_its_date_but_takes_no_new_past_date(self):
        made = self.deadline(DeadlineTarget(kind=OFFICE, office=self.acc))
        past = self.today - datetime.timedelta(days=2)
        type(made).objects.filter(pk=made.pk).update(due_on=past)
        client = self.as_(self.admin)
        url = f'/api/admin/deadlines/{made.pk}/'
        kept = client.patch(url, {'title': 'Renamed', 'due_on': past.isoformat()}, format='json')
        self.assertEqual(kept.status_code, 200)
        moved = client.patch(url, {'due_on': (past - datetime.timedelta(days=1)).isoformat()},
                             format='json')
        self.assertEqual((moved.status_code, moved.data['reason']), (400, 'due_in_past'))


class StillOwedThroughAnother(DeadlineFixture):

    def test_the_preview_says_which_target_still_covers_an_office(self):
        made = self.deadline(DeadlineTarget(kind=OFFICE, office=self.cash),
                             DeadlineTarget(kind='series', series=self.fam))
        response = self.as_(self.admin).patch(
            f'/api/admin/deadlines/{made.pk}/',
            {'targets': [{'kind': 'series', 'series_id': self.fam.pk}], 'preview': True},
            format='json')
        self.assertEqual(response.data['offices_removed'], [])
        self.assertEqual(response.data['still_owed'],
                         ['Cash Unit still owes this through the FAM series'])
