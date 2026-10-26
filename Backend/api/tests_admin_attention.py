"""The admin's Needs attention block (spec §8.2).

- **In order:** manuals marked priority or due within 30 days, then
  overdue (most days late first), then stalled requests.
- **Under the list's filters** (status, office, series), 50 a page.
- **Each request appears once**, under any filter and on any page - and
  so does every row of the main list.

Tests that expect an error assert the reason.
"""

import datetime

from django.utils import timezone

from api.models import (
    AuditEvent, CustomUser, Deadline, DeadlineObligation, DeadlineType, Manual, Proposal,
)

from .tests_concurrence import ConcurrenceFixture


class AttentionFixture(ConcurrenceFixture):

    def setUp(self):
        super().setUp()
        self.admin = CustomUser.objects.create_user(
            username='att_admin', password='pw', role='admin', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN)
        self.dtype, _ = DeadlineType.objects.get_or_create(name='Attention audit',
                                                           defaults={'created_by': self.admin})
        self.n = 0

    def new_manual(self):
        self.n += 1
        return Manual.objects.create(title=f'FAM 8.{self.n:02}', series=self.series)

    def owe(self, manual, due_in, office=None, priority=False):
        deadline = Deadline.objects.create(title=f'Due {due_in}', type=self.dtype, created_by=self.admin,
                                           due_on=self.today + datetime.timedelta(days=due_in))
        return DeadlineObligation.objects.create(deadline=deadline, office=office or self.accounting,
                                                 manual=manual, priority=priority)

    def request(self, manual, status=Proposal.WITH_HEAD, entered_days_ago=0, office=None):
        p = Proposal.objects.create(manual=manual, initiating_office=office or self.accounting,
                                    created_by=self.acc_enc, status=status)
        e = AuditEvent.objects.create(proposal=p, event=AuditEvent.SENT_TO_HEAD, actor=self.acc_enc,
                                      office=office or self.accounting)
        AuditEvent.objects.filter(pk=e.pk).update(
            at=timezone.now() - datetime.timedelta(days=entered_days_ago))
        return p

    def attention(self, **params):
        return self.as_(self.admin).get('/api/admin/proposals/attention/', params).data


class TheOrder(AttentionFixture):

    def test_priority_and_near_then_overdue_then_stalled(self):
        far_priority = self.new_manual()
        self.owe(far_priority, 90, priority=True)
        near = self.new_manual()
        self.owe(near, 5)
        late = self.new_manual()
        self.owe(late, -3)
        later = self.new_manual()
        self.owe(later, -10)
        self.request(later)                                   # overdue, with a request
        stuck = self.request(self.new_manual(), entered_days_ago=6)   # stalled (limit 3), no deadline
        self.owe(self.new_manual(), 200)                          # not urgent: not listed
        data = self.attention()
        self.assertEqual([(r['group'], r['manual']) for r in data['rows']], [
            ('priority_or_near', 'FAM 8.02'), ('priority_or_near', 'FAM 8.01'),
            ('overdue', 'FAM 8.04'), ('overdue', 'FAM 8.03'),
            ('stalled', 'FAM 8.05'),
        ])
        self.assertEqual(data['groups'], {'priority_or_near': 2, 'overdue': 2, 'stalled': 1})
        rows = {r['manual']: r for r in data['rows']}
        self.assertEqual(rows['FAM 8.03']['status'], 'Not started')
        self.assertEqual(rows['FAM 8.03']['action']['label'], 'Open deadline')
        self.assertEqual(rows['FAM 8.04']['status'], 'With Head')
        self.assertEqual(rows['FAM 8.04']['due']['days_late'], 10)
        self.assertEqual(rows['FAM 8.05']['proposal_id'], stuck.pk)
        self.assertTrue(rows['FAM 8.05']['stalled'])

    def test_filters_follow_the_list(self):
        self.owe(self.new_manual(), 5)
        self.owe(self.new_manual(), 5, office=self.budget)
        self.assertEqual({r['office'] for r in self.attention(office=self.budget.pk)['rows']},
                         {'Budget Office'})
        self.assertEqual(self.attention(status='closed')['count'], 0)
        self.assertEqual(self.attention(status=Proposal.WITH_HEAD)['count'], 0)  # not started hidden
        self.assertEqual(self.attention(status='nonsense')['reason'], 'invalid_status')

    def test_admin_only(self):
        response = self.as_(self.acc_head).get('/api/admin/proposals/attention/')
        self.assertEqual(response.status_code, 403)


class EachRequestOnce(AttentionFixture):

    def test_no_request_twice_under_any_filter_or_page(self):
        # 60 requests, each owed twice (priority and overdue) and stalled -
        # every way a request could be listed more than once.
        for n in range(60):
            m = self.new_manual()
            office = self.accounting if n % 2 else self.budget
            self.owe(m, -2, office=office)
            self.owe(m, 5, office=office, priority=True)
            self.request(m, entered_days_ago=9, office=office)
        for filters in ({}, {'office': self.accounting.pk}, {'series': self.series.pk},
                        {'status': 'all'}, {'status': Proposal.WITH_HEAD}):
            first = self.attention(**filters)
            seen = []
            for group, n in first['groups'].items():
                if not n:
                    continue
                part = self.attention(group=group, **filters)
                for page in range(1, part['pages'] + 1):
                    seen += [r['proposal_id'] for r in
                             self.attention(group=group, page=page, **filters)['rows']]
            self.assertEqual(len(seen), len(set(seen)), filters)
            self.assertEqual(len(seen), first['count'], filters)
            shown = [r['proposal_id'] for r in first['rows']]
            self.assertEqual(len(shown), len(set(shown)), filters)
        listed = []
        for page in (1, 2):
            listed += [r['id'] for r in self.as_(self.admin).get(
                '/api/admin/proposals/', {'status': 'all', 'page': page}).data['results']]
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(len(listed), 60)


class TenEachThenShowMore(AttentionFixture):

    def test_each_part_shows_ten_and_the_count(self):
        for n in range(14):
            self.owe(self.new_manual(), -1 - n)
        first = self.attention()
        self.assertEqual((first['groups']['overdue'], len(first['rows'])), (14, 10))
        part = self.attention(group='overdue')
        self.assertEqual((part['count'], len(part['rows'])), (14, 14))
        self.assertEqual(self.attention(group='everything')['reason'], 'invalid_group')
