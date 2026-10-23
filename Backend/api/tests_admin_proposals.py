"""The admin's Proposals list: every proposal, paged and filtered.

It used to read the dashboard's six most recent, so the seventh proposal
in the system was invisible to the admin. These tests hold the stop-gap
until the Phase 5 rebuild: all proposals reachable, 50 to a page, filtered
by status, office and series on the server, in a fixed number of queries.
"""

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Concurrence, CustomUser, Manual, ManualSeries, Office, Proposal,
    ProposalParticipant, ProposalVersion,
)


class AdminProposalListTests(TestCase):

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username='admin', password='x', role='admin', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

        self.vp = Office.objects.create(name='VP', is_approving_level=True)
        self.acc = Office.objects.create(name='Accounting Office', parent=self.vp)
        self.bud = Office.objects.create(name='Budget Office', parent=self.vp)
        self.fam = ManualSeries.objects.create(code='FAM', title='Finance', owning_office=self.vp)
        self.hrm = ManualSeries.objects.create(code='HRM', title='HR', owning_office=self.vp)

    def proposal(self, number, status=Proposal.EFFECTIVE, office=None, series=None,
                 updated_days_ago=0):
        series = series or self.fam
        manual = Manual.objects.create(title=f'{series.code} {number}', series=series)
        proposal = Proposal.objects.create(
            manual=manual, initiating_office=office or self.acc,
            status=status, created_by=self.admin,
        )
        ProposalVersion.objects.create(proposal=proposal, number=1)
        Proposal.objects.filter(pk=proposal.pk).update(
            updated_at=timezone.now() - timedelta(days=updated_days_ago))
        return proposal

    def get(self, **params):
        return self.client.get('/api/admin/proposals/', params)

    def test_more_than_six_proposals_are_visible(self):
        made = [self.proposal(n, status=Proposal.DRAFT, updated_days_ago=n)
                for n in range(9)]

        data = self.get(status='all').data

        self.assertEqual(data['count'], 9)
        # Most recently updated first.
        self.assertEqual([r['id'] for r in data['results']], [p.id for p in made])

    def test_fifty_to_a_page(self):
        for n in range(53):
            self.proposal(n)

        first = self.get(status='all').data
        second = self.get(status='all', page=2).data

        self.assertEqual((first['count'], first['pages'], first['page_size']), (53, 2, 50))
        self.assertEqual(len(first['results']), 50)
        self.assertEqual(len(second['results']), 3)
        ids = {r['id'] for r in first['results']} | {r['id'] for r in second['results']}
        self.assertEqual(len(ids), 53)

    def test_open_is_the_default_and_leaves_out_closed(self):
        draft = self.proposal(1, status=Proposal.DRAFT)
        signing = self.proposal(2, status=Proposal.AWAITING_SIGNATURE)
        self.proposal(3, status=Proposal.EFFECTIVE)
        self.proposal(4, status=Proposal.WITHDRAWN)

        ids = {r['id'] for r in self.get().data['results']}

        self.assertEqual(ids, {draft.id, signing.id})

    def test_filters_by_one_status(self):
        self.proposal(1, status=Proposal.DRAFT)
        denied = self.proposal(2, status=Proposal.DENIED)

        data = self.get(status='denied').data

        self.assertEqual([r['id'] for r in data['results']], [denied.id])

    def test_filters_by_office_and_series(self):
        acc_fam = self.proposal(1, office=self.acc, series=self.fam)
        self.proposal(2, office=self.bud, series=self.fam)
        acc_hrm = self.proposal(3, office=self.acc, series=self.hrm)

        by_office = {r['id'] for r in self.get(status='all', office=self.acc.id).data['results']}
        by_both = [r['id'] for r in self.get(
            status='all', office=self.acc.id, series=self.hrm.id).data['results']]

        self.assertEqual(by_office, {acc_fam.id, acc_hrm.id})
        self.assertEqual(by_both, [acc_hrm.id])

    def test_a_row_says_how_far_concurrence_has_got(self):
        proposal = self.proposal(1, status=Proposal.CONCURRENCE)
        version = proposal.versions.get()
        for office in (self.bud, self.vp):
            ProposalParticipant.objects.create(
                proposal=proposal, office=office, office_name_at_time=office.name,
                role=ProposalParticipant.CONCURRING)
        Concurrence.objects.create(version=version, office=self.bud,
                                   decision=Concurrence.CONCUR, recorded_by=self.admin)

        row = self.get().data['results'][0]

        self.assertEqual((row['concurred'], row['of'], row['version']), (1, 2, 1))
        self.assertEqual(row['manual'], 'FAM 1')
        self.assertEqual(row['series'], 'FAM')
        self.assertEqual(row['office'], 'Accounting Office')

    def test_queries_do_not_grow_with_the_page(self):
        self.proposal(0)
        with CaptureQueriesContext(connection) as one:
            self.get(status='all')
        for n in range(1, 30):
            self.proposal(n)
        with CaptureQueriesContext(connection) as thirty:
            self.get(status='all')

        self.assertEqual(len(one), len(thirty))

    def test_bad_filters_are_refused_with_the_reason(self):
        for params, reason in (
            ({'status': 'pending'}, 'invalid_status'),
            ({'office': 'abc'}, 'invalid_office'),
            ({'series': 'x'}, 'invalid_series'),
            ({'page': '0'}, 'invalid_page'),
            ({'page': 'two'}, 'invalid_page'),
        ):
            with self.subTest(params=params):
                response = self.get(**params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['reason'], reason)

    def test_only_the_admin_may_list_every_proposal(self):
        staff = CustomUser.objects.create_user(username='staff', password='x', is_approved=True)
        self.client.force_authenticate(user=staff)

        self.assertEqual(self.get().status_code, 403)
