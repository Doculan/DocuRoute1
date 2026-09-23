"""The handover from single-section revisions to proposals.

The switch decides which flow is real. What matters is that there is
never a moment when both are, or neither.

**With it off**, every v3 path works exactly as it did - people are using
it while the organisation is entered.

**With it on**, those paths refuse *with an explanation*, rather than
disappearing. A route that vanishes gives an open browser tab a 404 and
the person no idea why.

**The admin dashboard reads both**, so it does not go blank at the moment
access changes - which would look like the system stopped being used.
"""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    AccessMode, Concurrence, CustomUser, Department, Manual, ManualSection,
    ManualSeries, ManualSeriesOffice, Office, OfficeLink, Position,
    PositionAssignment, Proposal, ProposalVersion,
)

PASSWORD = "correct-horse-battery"


class HandoverFixture(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        self.department = Department.objects.create(name="CAS")

        self.president = Office.objects.create(
            name="Office of the President", abbreviation="OP",
            is_approving_level=True,
        )
        self.vpaf = Office.objects.create(
            name="VPAF", abbreviation="VPAF", parent=self.president,
            is_approving_level=True,
        )
        self.accounting = Office.objects.create(
            name="Accounting Office", abbreviation="ACC", parent=self.vpaf,
        )

        self.series = ManualSeries.objects.create(
            code="FAM", title="Finance", owning_office=self.vpaf,
        )
        ManualSeriesOffice.objects.create(
            series=self.series, office=self.accounting,
            relationship=OfficeLink.CONCURRING,
        )
        self.manual = Manual.objects.create(
            title="FAM 6.02", department=self.department, series=self.series,
        )
        self.s1 = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES", order=0,
            content="The Cashier shall release the cheque within five days.",
            tag="POLICY",
        )
        self.s2 = ManualSection.objects.create(
            manual=self.manual, subtitle="4.0 PROCEDURES", order=1,
            content="The Accounting Staff verifies the request.", tag="PROCEDURE",
        )

        self.staff = CustomUser.objects.create_user(
            username="staff", password=PASSWORD, is_approved=True,
            department=self.department,
        )
        position, _ = Position.objects.get_or_create(
            office=self.accounting, kind=Position.ENCODER,
        )
        PositionAssignment.objects.create(
            user=self.staff, position=position, starts_on=self.today,
        )

        self.admin = CustomUser.objects.create_user(
            username="sysadmin", password=PASSWORD, role="admin",
            system_role=CustomUser.SYSTEM_ADMIN, is_approved=True,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.staff)

    def switch(self, on):
        AccessMode.objects.update_or_create(pk=1, defaults={'by_position': on})

    def as_admin(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client


class TheOldFlowKeepsWorkingTests(HandoverFixture):
    """While the organisation is being entered, this is what people use."""

    def setUp(self):
        super().setUp()
        self.switch(False)

    def test_the_single_section_check_works(self):
        response = self.client.post(
            f'/api/revisions/pre-assess/{self.s1.id}/',
            {'proposed_content': 'The Cashier shall release it in a day.',
             'change_reason': 'Consolidated after the 2026 management review.'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_proposing_a_text_revision_works(self):
        checked = self.client.post(
            f'/api/revisions/pre-assess/{self.s1.id}/',
            {'proposed_content': 'The Cashier shall release it in a day.',
             'change_reason': 'Consolidated after the 2026 management review.'},
            format='json',
        )
        response = self.client.post(
            f'/api/revisions/propose-text/{self.s1.id}/',
            {'proposed_content': 'The Cashier shall release it in a day.',
             'change_reason': 'Consolidated after the 2026 management review.',
             'assessment_id': checked.data['assessment_id']},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)

    def test_the_merge_check_works(self):
        response = self.client.post(
            '/api/revisions/pre-assess-merge/',
            {'source_section_id': self.s2.id, 'target_section_id': self.s1.id,
             'change_reason': 'Consolidated after the 2026 management review.'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)

    def test_proposals_are_not_available(self):
        response = self.client.post(
            '/api/proposals/', {'manual_id': self.manual.id}, format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'switch_off')


class TheOldFlowStandsAsideTests(HandoverFixture):
    """Refused with an explanation, not removed."""

    def setUp(self):
        super().setUp()
        self.switch(True)

    def test_the_single_section_check_refuses_and_says_why(self):
        response = self.client.post(
            f'/api/revisions/pre-assess/{self.s1.id}/',
            {'proposed_content': 'Changed.', 'change_reason': 'A real reason here.'},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'superseded_by_proposals')
        self.assertIn('whole document', response.data['error'])

    def test_proposing_a_text_revision_refuses(self):
        response = self.client.post(
            f'/api/revisions/propose-text/{self.s1.id}/',
            {'proposed_content': 'Changed.', 'change_reason': 'A real reason.'},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'superseded_by_proposals')

    def test_uploading_a_revision_refuses(self):
        response = self.client.post(
            f'/api/revisions/upload/{self.s1.id}/', {}, format='multipart',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'superseded_by_proposals')

    def test_merging_says_it_is_out_of_scope_rather_than_superseded(self):
        """Merging deletes a section. It is not replaced by proposals - it
        has no home in one yet, which is a different thing and deserves a
        different sentence."""
        response = self.client.post(
            '/api/revisions/propose-merge/',
            {'source_section_id': self.s2.id, 'target_section_id': self.s1.id,
             'change_reason': 'A real reason here.'},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'merge_out_of_scope')
        self.assertIn('deletes a section', response.data['error'])

    def test_the_merge_check_refuses_too(self):
        response = self.client.post(
            '/api/revisions/pre-assess-merge/',
            {'source_section_id': self.s2.id, 'target_section_id': self.s1.id,
             'change_reason': 'A real reason here.'},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'merge_out_of_scope')

    def test_the_admin_section_merge_refuses_as_well(self):
        """The Sections screen merges too, and it deletes the same row."""
        response = self.as_admin().post(
            f'/api/sections/{self.s2.id}/merge/',
            {'target_id': self.s1.id}, format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'merge_out_of_scope')

    def test_nothing_was_written_by_any_of_them(self):
        from api.models import ManualRevision, RevisionPreAssessment
        self.client.post(
            f'/api/revisions/propose-text/{self.s1.id}/',
            {'proposed_content': 'Changed.', 'change_reason': 'A real reason.'},
            format='json',
        )
        self.assertEqual(ManualRevision.objects.count(), 0)
        self.assertEqual(RevisionPreAssessment.objects.count(), 0)

    def test_reading_a_section_still_works(self):
        """Only the ways of *changing* a document stood aside. Reading is
        the common case and must be untouched."""
        response = self.client.get(f'/api/manuals/{self.manual.id}/sections/')
        self.assertEqual(response.status_code, 200)


class TheStaffShellKnowsWhichFlowTests(HandoverFixture):

    def test_the_dashboard_says_which_flow_is_live(self):
        self.switch(False)
        self.assertFalse(
            self.client.get('/api/staff/dashboard/').data['access_by_position']
        )
        self.switch(True)
        self.assertTrue(
            self.client.get('/api/staff/dashboard/').data['access_by_position']
        )

    def test_it_counts_what_is_waiting_on_my_office(self):
        self.switch(True)
        budget = Office.objects.create(name="Budget", abbreviation="BUD",
                                       parent=self.vpaf)
        ManualSeriesOffice.objects.create(
            series=self.series, office=budget,
            relationship=OfficeLink.CONCURRING,
        )
        head, _ = Position.objects.get_or_create(
            office=budget, kind=Position.HEAD,
        )
        bud_head = CustomUser.objects.create_user(
            username="bud_head", password=PASSWORD, is_approved=True,
        )
        PositionAssignment.objects.create(
            user=bud_head, position=head, starts_on=self.today,
        )

        proposal = Proposal.objects.create(
            manual=self.manual, initiating_office=self.accounting,
            created_by=self.staff, status=Proposal.CONCURRENCE,
        )
        version = ProposalVersion.objects.create(proposal=proposal, number=1)
        from api.models import ProposalParticipant
        ProposalParticipant.objects.create(
            proposal=proposal, office=budget, office_name_at_time="Budget",
            role=ProposalParticipant.CONCURRING,
        )

        client = APIClient()
        client.force_authenticate(user=bud_head)
        self.assertEqual(
            client.get('/api/staff/dashboard/').data['proposals_awaiting'], 1
        )

        Concurrence.objects.create(
            version=version, office=budget, decision=Concurrence.CONCUR,
            recorded_by=bud_head,
        )
        self.assertEqual(
            client.get('/api/staff/dashboard/').data['proposals_awaiting'], 0
        )


class TheAdminDashboardDoesNotGoBlankTests(HandoverFixture):

    def a_locked_proposal(self):
        proposal = Proposal.objects.create(
            manual=self.manual, initiating_office=self.accounting,
            created_by=self.staff, status=Proposal.LOCKED,
            locked_at=timezone.now(),
        )
        ProposalVersion.objects.create(
            proposal=proposal, number=1, submitted_at=timezone.now(),
            submitted_by=self.staff,
        )
        return proposal

    def test_proposal_work_appears_in_the_activity_chart(self):
        """Reading only revisions would make the chart go blank at the
        moment access changed, which looks like the system stopped being
        used."""
        self.switch(True)
        self.a_locked_proposal()

        activity = self.as_admin().get('/api/admin/dashboard/').data['activity']
        self.assertEqual(activity['totals']['submitted'], 1)
        self.assertEqual(activity['totals']['approved'], 1)
        self.assertEqual(activity['mode'], 'proposals')

    def test_the_mode_says_which_flow_is_being_counted(self):
        self.switch(False)
        self.assertEqual(
            self.as_admin().get('/api/admin/dashboard/').data['activity']['mode'],
            'revisions',
        )

    def test_open_proposals_are_counted_for_attention(self):
        self.switch(True)
        Proposal.objects.create(
            manual=self.manual, initiating_office=self.accounting,
            created_by=self.staff, status=Proposal.CONCURRENCE,
        )
        self.a_locked_proposal()

        attention = self.as_admin().get('/api/admin/dashboard/').data['attention']
        self.assertEqual(attention['proposals_in_concurrence'], 1)
        self.assertEqual(attention['proposals_locked'], 1)
        self.assertEqual(attention['proposals_drafting'], 0)

    def test_recent_proposals_are_listed_with_their_progress(self):
        self.switch(True)
        proposal = self.a_locked_proposal()
        rows = self.as_admin().get('/api/admin/dashboard/').data['proposals']
        self.assertEqual([r['id'] for r in rows], [proposal.id])
        self.assertEqual(rows[0]['manual'], 'FAM 6.02')
        self.assertEqual(rows[0]['status'], Proposal.LOCKED)

    def test_the_revision_counts_still_work_with_the_switch_off(self):
        """Both can carry work during the changeover, so neither is
        hidden."""
        self.switch(False)
        data = self.as_admin().get('/api/admin/dashboard/').data
        self.assertIn('pending_revisions', data['attention'])
        self.assertIn('proposals_in_concurrence', data['attention'])
