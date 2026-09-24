"""The dashboards, reading proposals.

The staff dashboard counts what is waiting on the person's offices; the
admin dashboard's attention counts, activity chart and recent list read
proposals. Kept from the v3-to-v4 handover tests when the single-section
flow and the access switch were removed (v4.1.0).
"""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Concurrence, CustomUser, Manual, ManualSection, ManualSeries,
    ManualSeriesOffice, Office, OfficeLink, Position, PositionAssignment,
    Proposal, ProposalVersion,
)

PASSWORD = "correct-horse-battery"


class DashboardFixture(TestCase):

    def setUp(self):
        self.today = timezone.localdate()

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
            title="FAM 6.02", series=self.series,
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

    def as_admin(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client


class StaffDashboardTests(DashboardFixture):

    def test_reading_a_section_works(self):
        response = self.client.get(f'/api/manuals/{self.manual.id}/sections/')
        self.assertEqual(response.status_code, 200)

    def test_it_counts_what_is_waiting_on_my_office(self):
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


class AdminDashboardTests(DashboardFixture):

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
        self.a_locked_proposal()

        activity = self.as_admin().get('/api/admin/dashboard/').data['activity']
        self.assertEqual(activity['totals']['submitted'], 1)
        self.assertEqual(activity['totals']['approved'], 1)

    def test_open_proposals_are_counted_for_attention(self):
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
        proposal = self.a_locked_proposal()
        rows = self.as_admin().get('/api/admin/dashboard/').data['proposals']
        self.assertEqual([r['id'] for r in rows], [proposal.id])
        self.assertEqual(rows[0]['manual'], 'FAM 6.02')
        self.assertEqual(rows[0]['status'], Proposal.LOCKED)
