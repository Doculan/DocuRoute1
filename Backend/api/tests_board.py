"""Deadline-first Proposals for staff (spec §8.3).

- **Sections in order**, each paged at 50, empty ones left out: Due for
  submission, Awaiting your office, Returned to you, From my office,
  Other offices' requests.
- **Due for submission** ranks overdue, due soonest, priority, then the
  rest, and shows "Not started" for manuals the office owes but has not
  begun.
- **One action per row**, never one the viewer cannot take.
- **Each request appears once.**

Tests that expect an error assert the reason.
"""

import datetime

from api.models import (
    Concurrence, Deadline, DeadlineObligation, DeadlineType, Manual, Proposal,
)

from .tests_concurrence import ConcurrenceFixture


class BoardFixture(ConcurrenceFixture):

    def setUp(self):
        super().setUp()
        self.dtype, _ = DeadlineType.objects.get_or_create(name='Board audit', defaults={
            'created_by': self.acc_head})
        self.m = {n: Manual.objects.create(title=f'FAM 9.0{n}', series=self.series) for n in range(1, 6)}

    def owe(self, manual, due_in, office=None, priority=False):
        deadline = Deadline.objects.create(
            title=f'Due {due_in}', type=self.dtype, created_by=self.acc_head,
            due_on=self.today + datetime.timedelta(days=due_in))
        return DeadlineObligation.objects.create(deadline=deadline, office=office or self.accounting,
                                                 manual=manual, priority=priority)

    def board(self, user=None, **params):
        return self.as_(user or self.acc_enc).get('/api/proposals/board/', params).data

    def section(self, key, user=None, **params):
        return self.board(user, section=key, **params)['rows']


class DueForSubmission(BoardFixture):

    def test_ranked_overdue_soonest_priority_then_the_rest(self):
        self.owe(self.m[1], 90)                         # the rest
        self.owe(self.m[2], 60, priority=True)          # priority
        self.owe(self.m[3], 10)                         # due soonest
        self.owe(self.m[4], -2)                         # overdue
        self.owe(self.m[5], -9)                         # most overdue
        rows = self.section('due')
        self.assertEqual([r['manual'] for r in rows],
                         ['FAM 9.05', 'FAM 9.04', 'FAM 9.03', 'FAM 9.02', 'FAM 9.01'])
        self.assertEqual(rows[0]['due']['days_late'], 9)
        self.assertTrue(all(r['status'] == 'Not started' for r in rows))
        self.assertEqual(rows[0]['action'], {'kind': 'start', 'label': 'Start'})
        self.assertEqual(self.board()['overdue'], 2)

    def test_a_started_manual_shows_its_request_and_appears_once(self):
        self.owe(self.manual, 5)
        proposal_id = self.a_draft()
        rows = self.section('due')
        self.assertEqual([(r['proposal_id'], r['status'], r['action']['label']) for r in rows],
                         [(proposal_id, 'Drafting', 'Continue')])
        self.assertEqual(self.section('mine'), [])
        self.assertNotIn('mine', [s['key'] for s in self.board()['sections']])

    def test_a_reader_cannot_start(self):
        self.owe(self.m[1], 5, office=self.budget)
        rows = self.section('due', self.bud_enc)
        self.assertEqual(rows[0]['action']['label'], 'Start')
        self.assertEqual(self.section('due', self.acc_enc), [])


class OneActionThatFits(BoardFixture):

    def row(self, key, user, proposal_id):
        return next(r for r in self.section(key, user) if r['proposal_id'] == proposal_id)

    def test_with_the_head(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        self.assertEqual(self.row('mine', self.acc_enc, proposal_id)['action']['label'], 'Recall')
        self.assertEqual(self.row('mine', self.acc_head, proposal_id)['action']['label'],
                         'Submit or return')

    def test_returned_by_the_head_the_encoder_redrafts(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        self.as_(self.acc_head).post(f'/api/proposals/{proposal_id}/return-to-encoder/',
                                     {'note': 'Name the day.'}, format='json')
        mine = self.row('returned', self.acc_enc, proposal_id)
        self.assertEqual((mine['status'], mine['action']['label']), ('Returned by the Head', 'Redraft'))
        self.assertIsNone(self.row('returned', self.acc_head, proposal_id)['action'])
        self.assertEqual(self.section('mine'), [])            # once, under Returned

    def test_awaiting_your_office_only_the_head_decides(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.assertEqual(self.row('awaiting', self.bud_head, proposal_id)['action']['label'],
                         'Concur or return')
        self.assertIsNone(self.row('awaiting', self.bud_enc, proposal_id)['action'])
        self.assertIsNone(self.row('mine', self.acc_enc, proposal_id)['action'])
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)
        self.assertNotIn('awaiting', [s['key'] for s in self.board(self.bud_head)['sections']])
        self.assertEqual(self.row('involving', self.bud_head, proposal_id)['action'], None)


class TheList(BoardFixture):

    def test_empty_sections_are_left_out_and_the_first_opens(self):
        empty = self.board()
        self.assertEqual((empty['sections'], empty['overdue'], empty['open']), ([], 0, None))
        self.owe(self.m[1], 5)
        data = self.board()
        self.assertEqual([s['key'] for s in data['sections']], ['due'])
        self.assertEqual(data['open'], 'due')

    def test_filters(self):
        self.owe(self.m[1], -3)
        self.owe(self.m[2], 20)
        self.a_draft()
        self.assertEqual([r['manual'] for r in self.section('due', overdue='1')], ['FAM 9.01'])
        self.assertEqual(len(self.section('due', status='not_started')), 2)
        self.assertEqual([r['manual'] for r in self.section('mine', status='drafting')], ['FAM 6.02'])
        self.assertEqual(self.section('mine', status='with_qms'), [])
        self.assertEqual([r['manual'] for r in self.section('due', manual='9.02')], ['FAM 9.02'])

    def test_paged_at_fifty(self):
        for n in range(53):
            manual = Manual.objects.create(title=f'FAM 7.{n:02}', series=self.series)
            Proposal.objects.create(manual=manual, initiating_office=self.accounting,
                                    created_by=self.acc_enc, status=Proposal.DRAFT)
        first = self.board(section='mine')
        self.assertEqual((first['count'], first['pages'], len(first['rows'])), (53, 2, 50))
        self.assertEqual(len(self.board(section='mine', page=2)['rows']), 3)

    def test_an_unknown_section_is_refused(self):
        self.assertEqual(self.board(section='everything')['reason'], 'invalid_section')


class OncePerManual(BoardFixture):

    def test_a_manual_owed_twice_is_one_row_under_the_more_urgent_deadline(self):
        self.owe(self.m[1], 40)
        self.owe(self.m[1], -4)
        rows = self.section('due')
        self.assertEqual([(r['manual'], r['due']['days_late']) for r in rows], [('FAM 9.01', 4)])
        self.assertEqual(self.board()['sections'][0]['count'], 1)


class TheDeadlinesTab(BoardFixture):
    """Staff Deadlines: what the office owes, each manual with its status,
    priority manuals first."""

    def test_each_manual_owed_with_its_status_priority_first(self):
        deadline = Deadline.objects.create(title='Audit', type=self.dtype, created_by=self.acc_head,
                                           due_on=self.today + datetime.timedelta(days=9))
        for manual, priority in ((self.m[1], False), (self.manual, False), (self.m[2], True)):
            DeadlineObligation.objects.create(deadline=deadline, office=self.accounting,
                                              manual=manual, priority=priority)
        proposal_id = self.a_draft()
        groups = self.as_(self.acc_enc).get('/api/my-deadlines/').data['deadlines']
        manuals = groups[0]['manuals']
        self.assertEqual([(m['title'], m['status']) for m in manuals], [
            ('FAM 9.02', 'Not started'), ('FAM 6.02', 'Drafting'), ('FAM 9.01', 'Not started'),
        ])
        self.assertTrue(manuals[0]['priority'])
        self.assertEqual(manuals[1]['proposal_id'], proposal_id)
