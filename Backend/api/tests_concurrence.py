"""Submission through to agreement.

The rules with teeth:

**Participants freeze at submission.** A reorganisation mid-request must
not change who has to agree to it - so the tests reorganise, mid-request,
and check that nothing moved.

**An office concurs with particular text.** A return makes a new version
and every concurrence resets, because agreement to text that no longer
exists is not agreement.

**Only a Head commits an office.** An Encoder drafts and can prepare
feedback; the Head confirms, with re-authentication.

Every test that expects an error asserts the reason, not only the status.
"""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    AccessMode, AuditEvent, Concurrence, CustomUser, Department, Manual,
    ManualSection, ManualSeries, ManualSeriesOffice, Office, OfficeLink,
    Position, PositionAssignment, Proposal, ProposalParticipant,
    ProposalVersion, RevisionPreAssessment, SectionChange,
)
from api.views import issue_reauth_token

PASSWORD = "correct-horse-battery"
REASON = "Consolidated the release window after the 2026 management review."


class ConcurrenceFixture(TestCase):
    """FAM, owned by the VPAF, worked on by Accounting and Budget."""

    def setUp(self):
        # `timezone.localdate()`, not `date.today()`. The application
        # works in the project's timezone and the machine may be a day
        # ahead of it - which made every assignment here start
        # tomorrow, and every test that needed one fail.
        self.today = timezone.localdate()
        self.department = Department.objects.create(name="CAS")

        self.president = Office.objects.create(
            name="Office of the President", abbreviation="OP",
            is_approving_level=True,
        )
        self.vpaf = Office.objects.create(
            name="VP for Administration and Finance", abbreviation="VPAF",
            parent=self.president, is_approving_level=True,
        )
        self.accounting = Office.objects.create(
            name="Accounting Office", abbreviation="ACC", parent=self.vpaf,
        )
        self.budget = Office.objects.create(
            name="Budget Office", abbreviation="BUD", parent=self.vpaf,
        )
        self.cash = Office.objects.create(
            name="Cash Management Office", abbreviation="CMO", parent=self.vpaf,
        )

        self.series = ManualSeries.objects.create(
            code="FAM", title="Finance and Administration Manual",
            owning_office=self.vpaf,
        )
        for office in (self.accounting, self.budget, self.cash):
            ManualSeriesOffice.objects.create(
                series=self.series, office=office,
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

        self.acc_head = self.person("acc_head", self.accounting, Position.HEAD)
        self.acc_enc = self.person("acc_enc", self.accounting, Position.ENCODER)
        self.bud_head = self.person("bud_head", self.budget, Position.HEAD)
        self.bud_enc = self.person("bud_enc", self.budget, Position.ENCODER)
        self.cmo_head = self.person("cmo_head", self.cash, Position.HEAD)

        AccessMode.objects.update_or_create(pk=1, defaults={'by_position': True})

        self.client = APIClient()
        self.client.force_authenticate(user=self.acc_enc)

    def person(self, username, office, kind):
        user = CustomUser.objects.create_user(
            username=username, password=PASSWORD, is_approved=True,
        )
        position, _ = Position.objects.get_or_create(office=office, kind=kind)
        PositionAssignment.objects.create(
            user=user, position=position, starts_on=self.today,
        )
        return user

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def token(self, user):
        return issue_reauth_token(user)

    def a_draft(self, sections=None):
        """A proposal ready to submit: changed, reasoned and checked."""
        proposal_id = self.client.post(
            '/api/proposals/', {'manual_id': self.manual.id}, format='json',
        ).data['id']
        self.client.patch(
            f'/api/proposals/{proposal_id}/',
            {'overall_reason': REASON}, format='json',
        )
        for section, text in (sections or [(self.s1, "The Cashier shall release the cheque within one day.")]):
            self.client.put(
                f'/api/proposals/{proposal_id}/sections/{section.id}/',
                {'new_text': text}, format='json',
            )
            self.client.post(
                f'/api/proposals/{proposal_id}/sections/{section.id}/check/',
                {}, format='json',
            )
        return proposal_id

    def submit(self, proposal_id, user=None):
        user = user or self.acc_head
        return self.as_(user).post(
            f'/api/proposals/{proposal_id}/submit/', {}, format='json',
            HTTP_X_REAUTH_TOKEN=self.token(user),
        )

    def decide(self, proposal_id, user, decision, feedback='', section=None):
        body = {'decision': decision, 'feedback': feedback}
        if section is not None:
            body['section_id'] = section.id
        return self.as_(user).post(
            f'/api/proposals/{proposal_id}/decide/', body, format='json',
            HTTP_X_REAUTH_TOKEN=self.token(user),
        )


class SubmissionTests(ConcurrenceFixture):

    def test_only_a_head_submits(self):
        proposal_id = self.a_draft()
        response = self.submit(proposal_id, user=self.acc_enc)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'not_head')
        self.assertEqual(
            Proposal.objects.get(pk=proposal_id).status, Proposal.DRAFT
        )

    def test_submitting_needs_a_password(self):
        proposal_id = self.a_draft()
        response = self.as_(self.acc_head).post(
            f'/api/proposals/{proposal_id}/submit/', {}, format='json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'reauth_required')

    def test_a_head_submits_and_it_goes_out_for_concurrence(self):
        proposal_id = self.a_draft()
        response = self.submit(proposal_id)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], Proposal.CONCURRENCE)

    def test_an_unchecked_section_stops_submission(self):
        proposal_id = self.a_draft()
        self.client.put(
            f'/api/proposals/{proposal_id}/sections/{self.s2.id}/',
            {'new_text': 'The Accounting Staff may verify the request.'},
            format='json',
        )
        response = self.submit(proposal_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_ready')

    def test_editing_after_checking_stops_submission(self):
        """Per section, using each change's own fingerprint."""
        proposal_id = self.a_draft()
        self.client.put(
            f'/api/proposals/{proposal_id}/sections/{self.s1.id}/',
            {'new_text': 'The Cashier shall release the cheque immediately.'},
            format='json',
        )
        response = self.submit(proposal_id)
        self.assertIn(response.data['reason'], ('not_ready', 'stale_checks'))

    def test_a_throwaway_reason_is_refused(self):
        """Clause 6.3 is only met if the reason says something. The same
        two tiers the single-section flow uses."""
        proposal_id = self.a_draft()
        self.client.patch(
            f'/api/proposals/{proposal_id}/',
            {'overall_reason': '.'}, format='json',
        )
        response = self.submit(proposal_id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'reason_rejected')

    def test_submitting_twice_is_refused(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        response = self.submit(proposal_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_draft')

    def test_with_no_other_office_it_locks_immediately(self):
        """Nobody to ask. A concurrence stage with an empty list would be
        a stage that means nothing."""
        ManualSeriesOffice.objects.filter(series=self.series).exclude(
            office=self.accounting
        ).delete()
        proposal_id = self.a_draft()
        response = self.submit(proposal_id)
        self.assertEqual(response.data['status'], Proposal.AWAITING_SIGNATURE)
        self.assertTrue(
            AuditEvent.objects.filter(
                proposal_id=proposal_id, event=AuditEvent.LOCKED,
            ).exists()
        )


class FrozenParticipantTests(ConcurrenceFixture):

    def setUp(self):
        super().setUp()
        self.proposal_id = self.a_draft()
        self.submit(self.proposal_id)

    def test_the_initiator_is_not_asked_to_concur_with_itself(self):
        offices = set(
            ProposalParticipant.objects.filter(
                proposal_id=self.proposal_id,
                role=ProposalParticipant.CONCURRING,
            ).values_list('office__abbreviation', flat=True)
        )
        self.assertEqual(offices, {'BUD', 'CMO'})

    def test_the_approval_route_is_frozen_in_order(self):
        route = list(
            ProposalParticipant.objects.filter(
                proposal_id=self.proposal_id,
                role=ProposalParticipant.APPROVING,
            ).order_by('route_order').values_list('office__abbreviation', flat=True)
        )
        self.assertEqual(route, ['VPAF', 'OP'])

    def test_adding_a_concurring_office_afterwards_changes_nothing(self):
        """A reorganisation mid-request must never alter who has to agree
        to it."""
        library = Office.objects.create(name="Library", parent=self.vpaf)
        ManualSeriesOffice.objects.create(
            series=self.series, office=library,
            relationship=OfficeLink.CONCURRING,
        )
        offices = set(
            ProposalParticipant.objects.filter(
                proposal_id=self.proposal_id,
                role=ProposalParticipant.CONCURRING,
            ).values_list('office__abbreviation', flat=True)
        )
        self.assertNotIn('Library', offices)
        self.assertEqual(offices, {'BUD', 'CMO'})

    def test_removing_one_afterwards_changes_nothing_either(self):
        ManualSeriesOffice.objects.filter(
            series=self.series, office=self.cash,
        ).delete()
        self.assertTrue(
            ProposalParticipant.objects.filter(
                proposal_id=self.proposal_id, office=self.cash,
            ).exists()
        )

    def test_a_resubmission_does_not_re_freeze_the_list(self):
        """Found in rehearsal, not by a unit test. An office added to the
        document halfway through became a participant on resubmission and
        blocked a proposal every original participant had concurred with.

        The list is frozen for the *request*, not the version: a redraft
        after a return is a new version of the same request."""
        self.decide(
            self.proposal_id, self.bud_head, Concurrence.RETURN,
            feedback="Too short.",
        )

        library = Office.objects.create(name="Library", parent=self.vpaf)
        ManualSeriesOffice.objects.create(
            series=self.series, office=library,
            relationship=OfficeLink.CONCURRING,
        )

        proposal = Proposal.objects.get(pk=self.proposal_id)
        for change in SectionChange.objects.filter(
            version=proposal.current_version()
        ):
            self.client.post(
                f'/api/proposals/{self.proposal_id}/sections/'
                f'{change.section_id}/check/', {}, format='json',
            )
        self.submit(self.proposal_id)

        offices = set(
            ProposalParticipant.objects.filter(
                proposal_id=self.proposal_id,
                role=ProposalParticipant.CONCURRING,
            ).values_list('office__abbreviation', flat=True)
        )
        self.assertEqual(offices, {'BUD', 'CMO'})

    def test_a_redrafted_proposal_still_locks_when_all_concur(self):
        """The symptom the re-freezing caused: every original participant
        agreed and it sat in concurrence for ever."""
        self.decide(
            self.proposal_id, self.bud_head, Concurrence.RETURN,
            feedback="Too short.",
        )
        proposal = Proposal.objects.get(pk=self.proposal_id)
        for change in SectionChange.objects.filter(
            version=proposal.current_version()
        ):
            self.client.post(
                f'/api/proposals/{self.proposal_id}/sections/'
                f'{change.section_id}/check/', {}, format='json',
            )
        self.submit(self.proposal_id)

        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        response = self.decide(
            self.proposal_id, self.cmo_head, Concurrence.CONCUR
        )
        self.assertEqual(response.data['status'], Proposal.AWAITING_SIGNATURE)

    def test_a_renamed_office_still_reads_as_it_was(self):
        """`office_name_at_time`. An office renamed next year must not
        rewrite what this request said."""
        self.budget.name = "Budget and Planning Office"
        self.budget.save()

        participant = ProposalParticipant.objects.get(
            proposal_id=self.proposal_id, office=self.budget,
        )
        self.assertEqual(participant.office_name_at_time, "Budget Office")

        data = self.as_(self.acc_head).get(
            f'/api/proposals/{self.proposal_id}/full/'
        ).data
        names = [p['office'] for p in data['participants']]
        self.assertIn("Budget Office", names)
        self.assertNotIn("Budget and Planning Office", names)

    def test_the_owner_is_in_the_route_even_when_it_initiated(self):
        """The owner-may-propose case: the route has to continue above the
        office that wrote the change."""
        ManualSeriesOffice.objects.create(
            series=self.series, office=self.vpaf,
            relationship=OfficeLink.CONCURRING,
        )
        vp_head = self.person("vp_head", self.vpaf, Position.HEAD)

        client = self.as_(vp_head)
        proposal_id = client.post(
            '/api/proposals/', {'manual_id': self.manual.id}, format='json',
        ).data['id']
        client.patch(f'/api/proposals/{proposal_id}/',
                     {'overall_reason': REASON}, format='json')
        client.put(
            f'/api/proposals/{proposal_id}/sections/{self.s2.id}/',
            {'new_text': 'The Accounting Staff may verify the request.'},
            format='json',
        )
        client.post(
            f'/api/proposals/{proposal_id}/sections/{self.s2.id}/check/',
            {}, format='json',
        )
        self.submit(proposal_id, user=vp_head)

        route = list(
            ProposalParticipant.objects.filter(
                proposal_id=proposal_id, role=ProposalParticipant.APPROVING,
            ).order_by('route_order').values_list('office__abbreviation', flat=True)
        )
        self.assertEqual(route, ['VPAF', 'OP'])
        self.assertIn('OP', route, 'somebody other than the proposer must sign')


class ConcurrenceTests(ConcurrenceFixture):

    def setUp(self):
        super().setUp()
        self.proposal_id = self.a_draft()
        self.submit(self.proposal_id)

    def test_only_a_head_records_a_decision(self):
        response = self.decide(self.proposal_id, self.bud_enc, Concurrence.CONCUR)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'not_head')

    def test_an_office_that_is_not_asked_cannot_decide(self):
        stranger_office = Office.objects.create(name="Library", parent=self.vpaf)
        stranger = self.person("stranger", stranger_office, Position.HEAD)
        response = self.decide(self.proposal_id, stranger, Concurrence.CONCUR)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'not_participating')

    def test_deciding_needs_a_password(self):
        response = self.as_(self.bud_head).post(
            f'/api/proposals/{self.proposal_id}/decide/',
            {'decision': Concurrence.CONCUR}, format='json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'reauth_required')

    def test_one_office_concurring_does_not_lock_it(self):
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        self.assertEqual(
            Proposal.objects.get(pk=self.proposal_id).status,
            Proposal.CONCURRENCE,
        )

    def test_every_office_concurring_locks_it(self):
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        response = self.decide(self.proposal_id, self.cmo_head, Concurrence.CONCUR)
        self.assertEqual(response.data['status'], Proposal.AWAITING_SIGNATURE)
        self.assertIsNotNone(
            Proposal.objects.get(pk=self.proposal_id).locked_at
        )

    def test_a_return_needs_feedback(self):
        """Returning without it leaves the office nothing to act on."""
        response = self.decide(self.proposal_id, self.bud_head, Concurrence.RETURN)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'feedback_required')

    def test_a_return_sends_it_back_to_draft_as_a_new_version(self):
        self.decide(
            self.proposal_id, self.bud_head, Concurrence.RETURN,
            feedback="One day is too short for the bank to clear it.",
        )
        proposal = Proposal.objects.get(pk=self.proposal_id)
        self.assertEqual(proposal.status, Proposal.DRAFT)
        self.assertEqual(proposal.versions.count(), 2)
        self.assertEqual(proposal.current_version().number, 2)

    def test_a_return_resets_every_concurrence(self):
        """An office agreed to particular text. That text no longer
        exists, so the agreement does not carry forward."""
        self.decide(self.proposal_id, self.cmo_head, Concurrence.CONCUR)
        self.decide(
            self.proposal_id, self.bud_head, Concurrence.RETURN,
            feedback="Too short.",
        )
        proposal = Proposal.objects.get(pk=self.proposal_id)
        current = proposal.current_version()

        self.assertEqual(Concurrence.objects.filter(version=current).count(), 0)
        # The old version keeps its record - it is history, not a mistake.
        old = proposal.versions.get(number=1)
        self.assertEqual(Concurrence.objects.filter(version=old).count(), 2)

    def test_the_new_version_carries_the_text_but_not_the_checks(self):
        """The office is amending its own work, so the text comes across -
        but a check that survived would be about text nobody submitted."""
        self.decide(
            self.proposal_id, self.bud_head, Concurrence.RETURN,
            feedback="Too short.",
        )
        proposal = Proposal.objects.get(pk=self.proposal_id)
        change = SectionChange.objects.get(version=proposal.current_version())

        self.assertEqual(
            change.new_text, "The Cashier shall release the cheque within one day."
        )
        self.assertIsNone(change.assessment_id)
        self.assertFalse(change.check_is_current)

    def test_a_returned_proposal_cannot_be_resubmitted_unchecked(self):
        self.decide(
            self.proposal_id, self.bud_head, Concurrence.RETURN,
            feedback="Too short.",
        )
        response = self.submit(self.proposal_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_ready')

    def test_feedback_is_visible_to_every_participating_office(self):
        """Offices often object for the same reason. Seeing each other's
        feedback avoids repeated rounds and contradictory demands."""
        self.decide(
            self.proposal_id, self.bud_head, Concurrence.RETURN,
            feedback="One day is too short.", section=self.s1,
        )
        for viewer in (self.acc_head, self.cmo_head):
            data = self.as_(viewer).get(
                f'/api/proposals/{self.proposal_id}/full/'
            ).data
            texts = [
                d['feedback'] for v in data['versions'] for d in v['decisions']
            ]
            self.assertIn("One day is too short.", texts)

    def test_a_decision_records_the_person_and_the_position(self):
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        decision = Concurrence.objects.get(office=self.budget)
        self.assertEqual(decision.recorded_by, self.bud_head)
        self.assertEqual(decision.recorded_by_position.kind, Position.HEAD)

    def test_deciding_on_a_locked_proposal_is_refused(self):
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        self.decide(self.proposal_id, self.cmo_head, Concurrence.CONCUR)
        response = self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_in_concurrence')


class WithdrawalTests(ConcurrenceFixture):

    def setUp(self):
        super().setUp()
        self.proposal_id = self.a_draft()

    def withdraw(self, user, reason="No longer needed."):
        return self.as_(user).post(
            f'/api/proposals/{self.proposal_id}/withdraw/',
            {'reason': reason}, format='json',
            HTTP_X_REAUTH_TOKEN=self.token(user),
        )

    def test_only_the_initiating_head_withdraws(self):
        response = self.withdraw(self.bud_head)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'not_head')

    def test_a_reason_is_required(self):
        response = self.withdraw(self.acc_head, reason="")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'reason_required')

    def test_withdrawing_keeps_the_record(self):
        self.withdraw(self.acc_head)
        proposal = Proposal.objects.get(pk=self.proposal_id)
        self.assertEqual(proposal.status, Proposal.WITHDRAWN)
        self.assertEqual(proposal.withdrawn_by, self.acc_head)
        self.assertEqual(proposal.withdrawn_reason, "No longer needed.")
        self.assertTrue(
            AuditEvent.objects.filter(
                proposal=proposal, event=AuditEvent.WITHDRAWN,
            ).exists()
        )

    def test_withdrawing_frees_the_sections(self):
        self.withdraw(self.acc_head)
        self.assertFalse(
            SectionChange.objects.filter(is_open=True).exists()
        )

    def test_it_can_be_withdrawn_from_concurrence_too(self):
        self.submit(self.proposal_id)
        response = self.withdraw(self.acc_head)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], Proposal.WITHDRAWN)

    def test_a_locked_proposal_cannot_be_withdrawn(self):
        ManualSeriesOffice.objects.filter(series=self.series).exclude(
            office=self.accounting
        ).delete()
        self.submit(self.proposal_id)
        response = self.withdraw(self.acc_head)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_open')


class AwaitingTests(ConcurrenceFixture):

    def test_it_lists_proposals_my_office_has_not_decided(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)

        data = self.as_(self.bud_head).get('/api/proposals/awaiting/').data
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['proposals'][0]['id'], proposal_id)

    def test_it_drops_off_once_the_office_has_concurred(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)

        data = self.as_(self.bud_head).get('/api/proposals/awaiting/').data
        self.assertEqual(data['total'], 0)

    def test_the_initiating_office_is_not_waiting_on_itself(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        data = self.as_(self.acc_head).get('/api/proposals/awaiting/').data
        self.assertEqual(data['total'], 0)

    def test_an_encoder_sees_it_too(self):
        """The list is per office, not per position - an Encoder prepares
        the response even though the Head confirms it."""
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        data = self.as_(self.bud_enc).get('/api/proposals/awaiting/').data
        self.assertEqual(data['total'], 1)


class AuditAndOversightTests(ConcurrenceFixture):

    def test_every_transition_is_recorded(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.RETURN,
                    feedback="Too short.")

        events = list(
            AuditEvent.objects.filter(proposal_id=proposal_id)
            .order_by('at').values_list('event', flat=True)
        )
        self.assertEqual(
            events,
            [AuditEvent.CREATED, AuditEvent.SUBMITTED,
             AuditEvent.RETURNED, AuditEvent.REDRAFTED],
        )

    def test_an_event_records_the_office_and_the_position(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        event = AuditEvent.objects.get(
            proposal_id=proposal_id, event=AuditEvent.SUBMITTED,
        )
        self.assertEqual(event.office, self.accounting)
        self.assertEqual(event.office_name_at_time, "Accounting Office")
        self.assertEqual(event.position.kind, Position.HEAD)

    def test_qms_staff_may_read_any_proposal(self):
        qms_office = Office.objects.create(name="QMS Office", parent=self.president)
        qms = self.person("qms", qms_office, Position.IMR)
        qms.system_role = CustomUser.QMS_STAFF
        qms.save(update_fields=['system_role'])

        proposal_id = self.a_draft()
        self.submit(proposal_id)
        response = self.as_(qms).get(f'/api/proposals/{proposal_id}/full/')
        self.assertEqual(response.status_code, 200)

    def test_an_unrelated_office_may_not(self):
        library = Office.objects.create(name="Library", parent=self.vpaf)
        outsider = self.person("outsider", library, Position.HEAD)
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.assertEqual(
            self.as_(outsider).get(f'/api/proposals/{proposal_id}/full/').status_code,
            403,
        )


class SwitchOffTests(ConcurrenceFixture):

    def test_everything_refuses_with_the_switch_off(self):
        proposal_id = self.a_draft()
        AccessMode.objects.filter(pk=1).update(by_position=False)

        for path in ('submit', 'decide', 'withdraw', 'full'):
            method = 'get' if path == 'full' else 'post'
            response = getattr(self.as_(self.acc_head), method)(
                f'/api/proposals/{proposal_id}/{path}/', {}, format='json',
            )
            self.assertEqual(response.status_code, 409, path)
            self.assertEqual(response.data['reason'], 'switch_off', path)
