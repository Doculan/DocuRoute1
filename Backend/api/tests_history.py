"""History (spec §8.4): closed requests and "Reviewed, no change".

- **Scope**, as Monitoring: the admin and QMS everything; a Head the
  office and everything beneath it; an Encoder their own office. Never a
  sibling or a parent branch. Mine is what the offices initiated or
  reviewed; Participated is what they concurred on or sign for.
- **Grouped by year, then month**, with counts by outcome; a month's rows
  load on their own, 50 a page.
- **Filters:** closed or submitted date with a range, outcome, office,
  series, DCR number.
- **Export** to CSV and PDF with the audit block's writers.

Tests that expect an error assert the reason.
"""

import datetime

from django.utils import timezone

from api.models import (
    AuditEvent, Manual, ManualReview, Position, PositionAssignment, Proposal, ProposalParticipant,
    ProposalVersion,
)

from .tests_monitoring_scope import TreeFixture


class HistoryFixture(TreeFixture):

    def closed(self, abbr, status=Proposal.EFFECTIVE, when=None, dcr='', submitted=None,
               participants=()):
        when = when or timezone.now()
        manual = Manual.objects.create(title=f'FAM {Manual.objects.count() + 20}.01', series=self.series)
        p = Proposal.objects.create(manual=manual, initiating_office=self.o[abbr],
                                    created_by=self.admin, status=status, dcr_number=dcr)
        Proposal.objects.filter(pk=p.pk).update(created_at=when - datetime.timedelta(days=10))
        ProposalVersion.objects.create(proposal=p, number=1, submitted_by=self.admin,
                                       submitted_at=submitted or when - datetime.timedelta(days=5))
        event = {Proposal.EFFECTIVE: AuditEvent.MADE_EFFECTIVE, Proposal.DENIED: AuditEvent.IMR_DENIED,
                 Proposal.WITHDRAWN: AuditEvent.WITHDRAWN}[status]
        e = AuditEvent.objects.create(proposal=p, event=event, actor=self.admin, office=self.o[abbr])
        AuditEvent.objects.filter(pk=e.pk).update(at=when)
        for other in participants:
            ProposalParticipant.objects.create(proposal=p, office=self.o[other],
                                               office_name_at_time=self.o[other].name,
                                               role=ProposalParticipant.CONCURRING)
        return p

    def reviewed(self, abbr, when=None):
        head = PositionAssignment.objects.filter(position__office=self.o[abbr],
                                                 position__kind=Position.HEAD).first()
        return ManualReview.objects.create(
            manual=self.manual, office=self.o[abbr], office_name_at_time=self.o[abbr].name,
            reviewed_by=head.user if head else self.admin,
            position=head.position if head else Position.objects.get_or_create(
                office=self.o[abbr], kind=Position.HEAD)[0],
            at=when or timezone.now())

    def history(self, user, **params):
        return self.as_(user).get('/api/history/', params)

    def offices_in(self, user, **params):
        """Every office whose rows this viewer gets, across all months."""
        data = self.history(user, **params).data
        seen = set()
        for y in data['years']:
            for m in y['months']:
                rows = self.history(user, year=y['year'], month=m['month'], **params).data['rows']
                seen |= {r['office'] for r in rows}
        return seen


class TheScope(HistoryFixture):

    def setUp(self):
        super().setUp()
        for abbr in ('ACC', 'BUD', 'CAO-F', 'HRMO', 'VPAF', 'GUI'):
            self.closed(abbr)
        # Reviews follow the same scope.
        self.reviewed('HRMO')
        self.reviewed('ACC')

    def test_a_head_sees_the_office_and_beneath_never_a_sibling_or_parent(self):
        self.assertEqual(self.offices_in(self.acc_head), {'ACC Office'})
        self.assertEqual(self.offices_in(self.caof_head), {'CAO-F Office', 'ACC Office', 'BUD Office'})
        self.assertEqual(self.offices_in(self.vpaf_head),
                         {'VPAF Office', 'CAO-F Office', 'ACC Office', 'BUD Office', 'HRMO Office'})

    def test_an_encoder_sees_their_own_office_only(self):
        self.assertEqual(self.offices_in(self.caof_enc), {'CAO-F Office'})
        self.assertEqual(self.offices_in(self.acc_enc), {'ACC Office'})

    def test_admin_and_qms_see_everything(self):
        everyone = {'ACC Office', 'BUD Office', 'CAO-F Office', 'HRMO Office', 'VPAF Office', 'GUI Office'}
        self.assertEqual(self.offices_in(self.admin), everyone)
        self.assertEqual(self.offices_in(self.imr), everyone)

    def test_an_office_outside_scope_is_refused(self):
        for office in ('HRMO', 'VPAF'):
            response = self.history(self.caof_head, office=self.o[office].pk)
            self.assertEqual((response.status_code, response.data.get('reason')), (403, 'out_of_scope'))

    def test_participated_is_what_they_concurred_on_initiated_elsewhere(self):
        shared = self.closed('HRMO', participants=('BUD',))
        # Inside the branch both ways: initiated by Accounting, concurred by
        # Budget - it is the branch's own, so Mine, not Participated.
        self.closed('ACC', participants=('BUD',))
        mine = self.offices_in(self.caof_head)
        self.assertNotIn('HRMO Office', mine)
        theirs = self.offices_in(self.caof_head, view='participated')
        self.assertEqual(theirs, {'HRMO Office'})
        self.assertTrue(shared.pk)


class GroupsAndFilters(HistoryFixture):

    def test_years_then_months_with_counts_by_outcome(self):
        this_month = timezone.now()
        last_year = this_month - datetime.timedelta(days=400)
        self.closed('ACC', Proposal.EFFECTIVE, this_month, dcr='DCR-2026-001')
        self.closed('ACC', Proposal.DENIED, this_month)
        self.closed('ACC', Proposal.WITHDRAWN, last_year)
        self.reviewed('ACC', this_month)
        years = self.history(self.acc_head).data['years']
        self.assertEqual([y['year'] for y in years],
                         [timezone.localtime(this_month).year, timezone.localtime(last_year).year])
        self.assertEqual(years[0]['outcomes'], {'effective': 1, 'denied': 1, 'reviewed': 1})
        self.assertEqual(years[1]['total'], 1)
        local = timezone.localtime(this_month)
        rows = self.history(self.acc_head, year=local.year, month=local.month).data['rows']
        self.assertEqual(sorted(r['outcome'] for r in rows), ['denied', 'effective', 'reviewed'])
        effective = next(r for r in rows if r['outcome'] == 'effective')
        self.assertEqual((effective['dcr_number'], effective['days_open']), ('DCR-2026-001', 10))

    def test_filters(self):
        now = timezone.now()
        self.closed('ACC', Proposal.EFFECTIVE, now, dcr='DCR-2026-007')
        self.closed('ACC', Proposal.WITHDRAWN, now)
        self.closed('ACC', Proposal.EFFECTIVE, now - datetime.timedelta(days=90),
                    submitted=now - datetime.timedelta(days=95))

        def total(**params):
            return sum(y['total'] for y in self.history(self.acc_head, **params).data['years'])
        self.assertEqual(total(outcome='withdrawn'), 1)
        self.assertEqual(total(dcr='2026-007'), 1)
        recent = (now - datetime.timedelta(days=30)).date().isoformat()
        self.assertEqual(total(**{'from': recent}), 2)
        self.assertEqual(total(date_on='submitted', **{'to': (now - datetime.timedelta(days=60)).date().isoformat()}), 1)

    def test_export_csv_and_pdf(self):
        self.closed('ACC', Proposal.EFFECTIVE, dcr='=DCR-2026-009')
        response = self.as_(self.acc_head).post('/api/history/export/', {'format': 'csv'}, format='json')
        text = response.content.decode('utf-8')
        self.assertTrue(text.startswith('﻿'))
        self.assertIn("'=DCR-2026-009", text)
        self.assertIn('ACC Office', text)
        pdf = self.as_(self.acc_head).post('/api/history/export/', {'format': 'pdf'}, format='json')
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        refused = self.as_(self.acc_head).post('/api/history/export/', {'format': 'xls'}, format='json')
        self.assertEqual(refused.data['reason'], 'invalid_format')
