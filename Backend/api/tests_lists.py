"""The long lists, rebuilt (Phase 3B-2).

The rules with teeth:

- **The same values as before**: the bulk rows for My Manuals, admin
  Manuals and the organisation's documents equal what the per-row code
  gave, for every viewer and every kind of document.
- **Paged at 50, filtered on the server**, refusals naming the reason.
- **A summary first**: series with counts, the group with open deadlines
  marked, Recently opened on top.
- **Queries do not grow with the page**, on every rebuilt endpoint.
- **Reach and the queues keep their rules**: no other branch's manual, no
  duplicates, an IMR's own office kept out of their approval queue, and a
  returned package waiting on the IMR only when the latest return named
  the approving authority's DCR.
"""

import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from api import deadlines, series_views, views
from api.models import (
    Attachment, CustomUser, Deadline, DeadlineTarget, Manual, ManualOffice, ManualSection,
    ManualSeries, ManualSeriesOffice, Office, OfficeLink, Position, PositionAssignment,
    Proposal, ProposalParticipant, ProposalVersion, QmsDecision, RecentlyOpened,
)

from .tests_notices import DeadlineFixture


class ListFixture(DeadlineFixture):

    def setUp(self):
        super().setUp()
        self.vp_head = self.person('vp_head', self.vp, Position.HEAD)
        self.reg_head = self.person('reg_head', self.reg, Position.HEAD)
        for manual in (self.m1, self.m2, self.m9):
            for n in range(manual.pk):
                manual.sections.create(subtitle=f'{n}.0', order=n, content='Text.')
        # Another branch, with its own series nobody here reads.
        self.vp2 = Office.objects.create(name='VP Academic', is_approving_level=True)
        self.dept = Office.objects.create(name='Department of English', parent=self.vp2)
        self.dept_head = self.person('dept_head', self.dept, Position.HEAD)
        self.aca = ManualSeries.objects.create(code='ACA', title='Academic', owning_office=self.vp2)
        ManualSeriesOffice.objects.create(series=self.aca, office=self.dept,
                                          relationship=OfficeLink.CONCURRING)
        self.a1 = Manual.objects.create(title='ACA 1', series=self.aca)
        # Unassigned, and one whose owner concurs and approval stops there.
        self.loose = Manual.objects.create(title='Loose document')
        self.self_approved = Manual.objects.create(
            title='FAM 8', series=self.fam, owning_office=self.acc, offices_overridden=True,
            approval_stops_at_owner=True)
        ManualOffice.objects.create(manual=self.self_approved, office=self.acc,
                                    relationship=OfficeLink.CONCURRING)
        ManualOffice.objects.create(manual=self.self_approved, office=self.reg,
                                    relationship=OfficeLink.READER)
        # Its override leaves only a reader: nobody may propose to it,
        # though its series would let three offices.
        self.read_only = Manual.objects.create(title='FAM 10', series=self.fam,
                                               offices_overridden=True)
        ManualOffice.objects.create(manual=self.read_only, office=self.reg,
                                    relationship=OfficeLink.READER)
        qms = Office.objects.create(name='Quality Management Office')
        self.imr = self.person('imr', qms, Position.IMR)
        self.imr.system_role = CustomUser.QMS_STAFF
        self.imr.save(update_fields=['system_role'])
        self.viewers = [self.acc_head, self.bud_head, self.cash_head, self.reg_head,
                        self.vp_head, self.dept_head, self.imr, self.admin]

    def rows(self, user, url):
        response = self.as_(user).get(url)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def queries(self, user, url):
        client = self.as_(user)
        client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(client.get(url).status_code, 200, url)
        return len(ctx)


class TheSameValuesAsBefore(ListFixture):

    def test_manual_rows_match_the_per_row_code(self):
        for user in self.viewers:
            for row in self.rows(user, '/api/staff/manuals/?page=1')['results']:
                m = Manual.objects.get(pk=row['id'])
                expected = {
                    'title': m.title,
                    'series': m.series.code if m.series_id else None,
                    'owner': str(m.effective_owner) if m.effective_owner else None,
                    'relationship': views._relationship_for(user, m),
                    'section_count': m.sections.count(),
                }
                self.assertEqual({k: row[k] for k in expected}, expected, (user.username, m.title))

    def test_document_rows_match_the_per_row_payload(self):
        documents = self.rows(self.admin, '/api/org/documents/?page=1')['documents']
        self.assertEqual(len(documents), Manual.objects.count())
        for row in documents:
            expected = series_views._document_payload(Manual.objects.get(pk=row['id']))
            self.assertEqual({k: v for k, v in row.items() if k != 'deadline'}, expected)
        conflict = [r for r in documents if r['owner_conflict']]
        self.assertEqual([r['title'] for r in conflict], ['FAM 8'])
        stranded = {r['title'] for r in documents if not r['can_be_proposed_against']}
        self.assertEqual(stranded, {'FAM 10', 'Loose document'})

    def test_a_series_page_matches_too(self):
        data = self.rows(self.admin, f'/api/org/series/{self.fam.pk}/')
        for row in data['documents']:
            expected = series_views._document_payload(Manual.objects.get(pk=row['id']))
            self.assertEqual({k: v for k, v in row.items() if k != 'deadline'}, expected)
        self.assertEqual(data['documents_paging']['count'], 5)


class Paging(ListFixture):

    def more_manuals(self, n, series=None):
        Manual.objects.bulk_create([Manual(title=f'FAM 9.{i:03}', series=series or self.fam)
                                    for i in range(n)])

    def test_fifty_a_page(self):
        self.more_manuals(55)
        first = self.rows(self.acc_head, '/api/staff/manuals/?page=1')
        # Accounting reads FAM 1, 2 and 8 (FAM 9 overrides: Budget alone), and the 55.
        self.assertEqual((first['count'], first['pages'], len(first['results'])), (58, 2, 50))
        second = self.rows(self.acc_head, '/api/staff/manuals/?page=2')
        self.assertEqual(len(second['results']), 8)
        ids = [r['id'] for r in first['results'] + second['results']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_series_and_a_search(self):
        fam = self.rows(self.imr, f'/api/staff/manuals/?series={self.fam.pk}')['results']
        self.assertEqual({r['title'] for r in fam}, {'FAM 1', 'FAM 2', 'FAM 9', 'FAM 8', 'FAM 10'})
        loose = self.rows(self.imr, '/api/staff/manuals/?series=none')['results']
        self.assertEqual([r['title'] for r in loose], ['Loose document'])
        found = self.rows(self.imr, '/api/staff/manuals/?q=aca')['results']
        self.assertEqual([r['title'] for r in found], ['ACA 1'])

    def test_refusals_name_the_reason(self):
        for url, reason in (('/api/staff/manuals/?page=0', 'invalid_page'),
                            ('/api/staff/manuals/?page=x', 'invalid_page'),
                            ('/api/staff/manuals/?series=x', 'invalid_series'),
                            ('/api/manuals/?uploader=x', 'invalid_uploader'),
                            ('/api/proposals/awaiting/?page=0', 'invalid_page'),
                            ('/api/proposals/involving/?page=-1', 'invalid_page'),
                            ('/api/qms/queue/?queue=imr&page=0', 'invalid_page'),
                            ('/api/qms/queue/?queue=nope', 'invalid_queue'),
                            ('/api/org/documents/?page=0', 'invalid_page'),
                            ('/api/org/documents/?series=x', 'invalid_series'),
                            (f'/api/org/series/{self.fam.pk}/?page=0', 'invalid_page')):
            user = self.imr if 'qms' in url else self.admin if ('org/' in url or url.startswith('/api/manuals')) else self.acc_head
            response = self.as_(user).get(url)
            self.assertEqual(response.status_code, 400, url)
            self.assertEqual(response.data['reason'], reason, url)

    def test_the_admins_uploader_filter(self):
        Manual.objects.filter(pk=self.m1.pk).update(uploaded_by=self.acc_head)
        data = self.rows(self.admin, '/api/manuals/')
        self.assertEqual(data['uploaders'], [{'id': self.acc_head.pk, 'username': 'acc_head'}])
        rows = self.rows(self.admin, f'/api/manuals/?page=1&uploader={self.acc_head.pk}')['results']
        self.assertEqual([r['title'] for r in rows], ['FAM 1'])

    def test_the_picker_is_every_title_by_series(self):
        picked = self.rows(self.acc_head, '/api/staff/manuals/?picker=1')['manuals']
        self.assertEqual([m['title'] for m in picked], ['FAM 1', 'FAM 2', 'FAM 8'])
        self.assertEqual(set(picked[0]), {'id', 'title', 'series_code'})


class TheSummary(ListFixture):

    def test_series_with_counts_and_the_unassigned_last(self):
        groups = self.rows(self.imr, '/api/staff/manuals/')['groups']
        self.assertEqual([(g['code'], g['count']) for g in groups],
                         [('ACA', 1), ('FAM', 5), (None, 1)])

    def test_the_group_with_an_open_deadline_is_marked(self):
        deadline = Deadline.objects.create(title='Audit', type=self.dtype, created_by=self.admin,
                                           due_on=self.today + datetime.timedelta(days=9))
        DeadlineTarget.objects.create(deadline=deadline, kind='manual', manual=self.m1)
        deadlines.materialise(deadline, self.admin)
        mine = {g['code']: g['open_deadlines'] for g in self.rows(self.acc_head, '/api/staff/manuals/')['groups']}
        self.assertEqual(mine, {'FAM': 1})
        # The Registry reads FAM but owes nothing.
        theirs = {g['code']: g['open_deadlines'] for g in self.rows(self.reg_head, '/api/staff/manuals/')['groups']}
        self.assertEqual(theirs, {'FAM': 0})
        everyone = {g['code']: g['open_deadlines'] for g in self.rows(self.imr, '/api/staff/manuals/')['groups']}
        self.assertEqual(everyone['FAM'], 1)

    def test_recently_opened_comes_with_it(self):
        RecentlyOpened.objects.create(user=self.acc_head, manual=self.m2)
        data = self.rows(self.acc_head, '/api/staff/manuals/')
        self.assertEqual([r['manual'] for r in data['recently_opened']], ['FAM 2'])
        self.assertIn('deadline', data['recently_opened'][0])

    def test_reach_is_kept(self):
        """Another branch's series is not offered, and a document the
        office both owns and concurs on is one row."""
        groups = self.rows(self.acc_head, '/api/staff/manuals/')['groups']
        self.assertEqual([g['code'] for g in groups], ['FAM'])
        rows = self.rows(self.acc_head, '/api/staff/manuals/?page=1')['results']
        # Not FAM 9: it overrides its series, and only Budget concurs on it.
        self.assertEqual(sorted(r['title'] for r in rows), ['FAM 1', 'FAM 2', 'FAM 8'])
        self.assertEqual([r['relationship'] for r in rows if r['title'] == 'FAM 8'],
                         ['Owner · Concurring'])


class QueriesDoNotGrowWithThePage(ListFixture):

    def grow(self):
        """Ten more of everything each list shows."""
        for i in range(10):
            manual = Manual.objects.create(title=f'FAM 7.{i:02}', series=self.fam)
            manual.sections.create(subtitle='1.0', order=0, content='Text.')
            for office, status in ((self.bud, Proposal.CONCURRENCE), (self.cash, Proposal.EFFECTIVE),
                                   (self.bud, Proposal.READY_FOR_IMR),
                                   (self.cash, Proposal.AWAITING_APPROVAL)):
                proposal = self.proposal(office, manual, status=status)
                ProposalParticipant.objects.create(proposal=proposal, office=self.acc,
                                                   office_name_at_time=self.acc.name,
                                                   role=ProposalParticipant.CONCURRING)

    def test_each_rebuilt_endpoint(self):
        cases = [(self.acc_head, '/api/staff/manuals/?page=1'),
                 (self.acc_head, '/api/staff/manuals/'),
                 (self.imr, '/api/staff/manuals/?page=1'),
                 (self.admin, '/api/manuals/?page=1'),
                 (self.acc_head, '/api/proposals/awaiting/'),
                 (self.acc_head, '/api/proposals/involving/'),
                 (self.imr, '/api/qms/queue/'),
                 (self.admin, '/api/org/documents/'),
                 (self.admin, f'/api/org/series/{self.fam.pk}/')]
        self.grow()
        before = [self.queries(user, url) for user, url in cases]
        self.grow()
        self.grow()
        after = [self.queries(user, url) for user, url in cases]
        self.assertEqual(dict(zip([url for _, url in cases], after)),
                         dict(zip([url for _, url in cases], before)))

    def test_and_the_pages_hold_the_rows(self):
        self.grow()
        self.assertEqual(self.rows(self.acc_head, '/api/proposals/awaiting/')['total'], 10)
        # The other thirty: finished, or past concurrence.
        self.assertEqual(self.rows(self.acc_head, '/api/proposals/involving/')['total'], 30)
        totals = self.rows(self.imr, '/api/qms/queue/')['totals']
        self.assertEqual((totals['imr'], totals['approval']), (10, 10))


class TheQueuesKeepTheirRules(ListFixture):

    def test_an_imrs_own_office_is_kept_out_of_their_approval_queue(self):
        mine = self.proposal(self.acc, self.m1, status=Proposal.AWAITING_APPROVAL)
        theirs = self.proposal(self.bud, self.m2, status=Proposal.AWAITING_APPROVAL)
        position, _ = Position.objects.get_or_create(office=self.acc, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=self.imr, position=position, starts_on=self.today)
        ids = [r['id'] for r in self.rows(self.imr, '/api/qms/queue/')['approval']]
        self.assertEqual(ids, [theirs.pk])
        self.assertNotIn(mine.pk, ids)

    def test_a_returned_package_waits_on_the_imr_only_for_the_approving_dcr(self):
        def returned(kinds_in_order):
            proposal = self.proposal(self.bud, self.m2, status=Proposal.PACKAGE_RETURNED)
            for n, kinds in enumerate(kinds_in_order):
                decision = QmsDecision.objects.create(
                    proposal=proposal, version=proposal.current_version(),
                    stage=QmsDecision.CUSTODIAN, outcome=QmsDecision.RETURN,
                    returned_kinds=kinds, decided_by=self.admin, decided_as='Custodian')
                QmsDecision.objects.filter(pk=decision.pk).update(
                    decided_at=timezone.now() + datetime.timedelta(minutes=n))
            return proposal
        waiting = returned([[Attachment.SIGNED_DCR], [Attachment.APPROVED_DCR]])
        not_now = returned([[Attachment.APPROVED_DCR], [Attachment.SIGNED_PAGES]])
        ids = [r['id'] for r in self.rows(self.imr, '/api/qms/queue/')['approval']]
        self.assertIn(waiting.pk, ids)
        self.assertNotIn(not_now.pk, ids)

    def test_one_queue_a_page_at_a_time(self):
        for _ in range(3):
            self.proposal(self.bud, self.m2, status=Proposal.READY_FOR_IMR)
        data = self.rows(self.imr, '/api/qms/queue/?queue=imr&page=1')
        self.assertEqual((data['count'], len(data['results'])), (3, 3))
        self.assertEqual(self.rows(self.acc_head, '/api/qms/queue/?queue=imr')['results'], [])
