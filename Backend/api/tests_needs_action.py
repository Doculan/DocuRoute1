"""Needs your action, and the staff home's awaiting count.

Derived from the data, so a notice someone missed or marked read cannot
hide work. The awaiting count is one aggregate query: it used to loop over
every proposal in concurrence.
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from api.models import (
    Concurrence, CustomUser, JobRun, Manual, Office, Position, Proposal,
    ProposalVersion,
)

from .tests_monitoring import MonitoringFixture


class NeedsAction(MonitoringFixture):

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def sections(self, user):
        return {s['key']: s for s in self.as_(user).get('/api/needs-action/').data['sections']}

    def test_the_head_must_concur_and_the_encoder_waits_on_them(self):
        proposal = self.in_concurrence(days_ago=1)

        head = self.sections(self.bud_head)['concurrence']
        self.assertEqual(head['total'], 1)
        self.assertEqual(head['items'][0]['label'], 'Concur or return')
        self.assertEqual(head['items'][0]['severity'], 'action')
        self.assertEqual(head['items'][0]['proposal_id'], proposal.pk)
        encoder = self.sections(self.bud_enc)['concurrence']['items'][0]
        self.assertEqual((encoder['label'], encoder['severity']), ('Waiting on your Head', 'info'))

    def test_an_office_that_has_concurred_is_not_asked_again(self):
        proposal = self.in_concurrence(days_ago=1)
        Concurrence.objects.create(version=proposal.current_version(), office=self.bud,
                                   decision=Concurrence.CONCUR, recorded_by=self.bud_head)
        self.assertNotIn('concurrence', self.sections(self.bud_head))
        self.assertIn('concurrence', self.sections(self.cash_head))

    def test_a_returned_draft_and_copies_to_sign_are_the_offices_to_do(self):
        from api.models import AuditEvent
        returned = self.in_concurrence(days_ago=1)
        Proposal.objects.filter(pk=returned.pk).update(status=Proposal.DRAFT)
        version = ProposalVersion.objects.create(proposal=returned, number=2)
        for kind, office in ((AuditEvent.RETURNED, self.bud), (AuditEvent.REDRAFTED, self.acc)):
            AuditEvent.objects.create(proposal=returned, version=version, event=kind,
                                      actor=self.bud_head, office=office,
                                      office_name_at_time=office.name)
        signing = Proposal.objects.create(
            manual=Manual.objects.create(title='FAM 7.01', series=self.manual.series),
            initiating_office=self.acc, status=Proposal.AWAITING_SIGNATURE,
            created_by=self.acc_enc)

        mine = self.sections(self.acc_enc)
        self.assertEqual(mine['returned']['items'][0]['proposal_id'], returned.pk)
        self.assertEqual(mine['returned']['items'][0]['label'], 'Redraft — returned by Budget Office')
        self.assertEqual(mine['signing']['items'][0]['proposal_id'], signing.pk)

    def test_the_qms_sees_its_stages(self):
        qms = Office.objects.create(name='Quality Management Office')
        imr = self.person('imr', qms, Position.IMR)
        custodian = self.person('custodian', qms, Position.DOCUMENT_CUSTODIAN)
        proposal = self.in_concurrence(days_ago=1)
        Proposal.objects.filter(pk=proposal.pk).update(status=Proposal.READY_FOR_IMR)

        self.assertEqual(self.sections(imr)['imr']['items'][0]['label'], 'Accept or deny')
        self.assertEqual(self.sections(custodian), {})
        Proposal.objects.filter(pk=proposal.pk).update(status=Proposal.WITH_CUSTODIAN)
        self.assertEqual(self.sections(custodian)['custodian']['total'], 1)

    def test_the_admin_sees_sign_ups_and_vacant_posts(self):
        from datetime import timedelta
        CustomUser.objects.create_user(username='applicant', password='x')
        self.bud_head.position_assignments.update(
            starts_on=self.today - timedelta(days=5), ends_on=self.today - timedelta(days=1))

        admin = self.sections(self.admin)
        self.assertEqual(admin['pending']['total'], 1)
        self.assertEqual(admin['vacant']['total'], 1)

    def test_nothing_waiting_sends_no_sections(self):
        data = self.as_(self.vp_head).get('/api/needs-action/').data
        self.assertEqual(data, {'total': 0, 'sections': []})


class TheStaffHomeCount(MonitoringFixture):

    def setUp(self):
        super().setUp()
        # The scheduler ran just now, so the dashboard does not run the
        # monitoring steps itself and the count is all that is measured.
        from django.utils import timezone
        JobRun.objects.create(started_at=timezone.now(), finished_at=timezone.now())

    def dashboard(self):
        client = APIClient()
        client.force_authenticate(user=self.bud_head)
        with CaptureQueriesContext(connection) as queries:
            data = client.get('/api/staff/dashboard/').data
        return data['proposals_awaiting'], len(queries)

    def test_the_count_is_right_and_costs_the_same_for_one_or_many(self):
        self.in_concurrence(days_ago=1)
        one, one_queries = self.dashboard()
        for n in range(6):
            self.manual = Manual.objects.create(title=f'FAM 9.{n}', series=self.manual.series)
            self.in_concurrence(days_ago=1)
        seven, seven_queries = self.dashboard()

        self.assertEqual((one, seven), (1, 7))
        self.assertEqual(one_queries, seven_queries)
