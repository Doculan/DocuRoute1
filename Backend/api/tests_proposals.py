"""Drafting a whole-document proposal.

Three things carry the weight here.

**One open proposal per section**, enforced by a partial index rather than
a view-level check, because two people submitting at the same moment is
exactly when a view-level check fails. `is_open` is a denormalisation, so
every writer that skips `save()` is tested - a stale False does not raise,
it silently lets two offices edit the same section at once.

**The check is per section.** Editing one box clears only that box, which
is the whole reason a twenty-section document is workable at all.

**Both switch states.** With the switch off the v3 single-section flow is
still the real one and these endpoints refuse; with it on they work. A
half-switched application is the failure mode this phase has to avoid.

Every test that expects an error asserts the reason, not only the status.
"""

import datetime
import os
import shutil
import sqlite3
import tempfile
import threading
from unittest import mock

from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api import proposal_views
from api.models import (
    AccessMode, AuditEvent, CustomUser, Department, Manual, ManualSection,
    ManualSeries, ManualSeriesOffice, Office, OfficeLink, Position,
    PositionAssignment, Proposal, ProposalVersion, RevisionPreAssessment,
    SectionChange,
)

PASSWORD = "correct-horse-battery"


class ProposalFixture(TestCase):
    """One document, two offices that concur, one that only reads."""

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
        self.registrar = Office.objects.create(
            name="Registrar", abbreviation="REG", parent=self.vpaf,
        )

        self.series = ManualSeries.objects.create(
            code="FAM", title="Finance and Administration Manual",
            owning_office=self.vpaf,
        )
        for office, relationship in (
            (self.accounting, OfficeLink.CONCURRING),
            (self.budget, OfficeLink.CONCURRING),
            (self.registrar, OfficeLink.READER),
        ):
            ManualSeriesOffice.objects.create(
                series=self.series, office=office, relationship=relationship,
            )

        self.manual = Manual.objects.create(
            title="FAM 6.02", department=self.department, series=self.series,
        )
        self.s1 = ManualSection.objects.create(
            manual=self.manual, subtitle="1.0 OBJECTIVES", order=0,
            content="To set out how receivables are monitored.", tag="POLICY",
        )
        self.s2 = ManualSection.objects.create(
            manual=self.manual, subtitle="3.0 POLICIES", order=1,
            content="The Cashier shall release the cheque within five days.",
            tag="POLICY",
        )
        self.s3 = ManualSection.objects.create(
            manual=self.manual, subtitle="4.0 PROCEDURES", order=2,
            content="The Accounting Staff verifies the request.", tag="PROCEDURE",
        )

        self.drafter = self.a_person("drafter", self.accounting, Position.ENCODER)
        self.head = self.a_person("head", self.accounting, Position.HEAD)
        self.other = self.a_person("other", self.budget, Position.ENCODER)
        self.reader = self.a_person("reader", self.registrar, Position.ENCODER)

        AccessMode.objects.update_or_create(pk=1, defaults={'by_position': True})

        self.client = APIClient()
        self.client.force_authenticate(user=self.drafter)

    def a_person(self, username, office, kind):
        person = CustomUser.objects.create_user(
            username=username, password=PASSWORD, is_approved=True,
        )
        position, _ = Position.objects.get_or_create(office=office, kind=kind)
        PositionAssignment.objects.create(
            user=person, position=position, starts_on=self.today,
        )
        return person

    def switch_off(self):
        AccessMode.objects.filter(pk=1).update(by_position=False)

    def start(self, client=None, office=None):
        body = {'manual_id': self.manual.id}
        if office is not None:
            body['office_id'] = office.id
        return (client or self.client).post('/api/proposals/', body, format='json')

    def edit(self, proposal_id, section, text, client=None):
        return (client or self.client).put(
            f'/api/proposals/{proposal_id}/sections/{section.id}/',
            {'new_text': text}, format='json',
        )


class SwitchStateTests(ProposalFixture):

    def test_proposals_refuse_while_the_switch_is_off(self):
        """The v3 flow is still the real one, and two ways to change a
        document with nothing deciding between them is worse than one."""
        self.switch_off()
        response = self.start()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'switch_off')

    def test_the_single_section_flow_still_works_with_the_switch_off(self):
        """Nothing in phase 2 may break what people are using today."""
        self.switch_off()
        self.drafter.department = self.department
        self.drafter.save(update_fields=['department'])

        response = self.client.post(
            f'/api/revisions/pre-assess/{self.s2.id}/',
            {'proposed_content': 'The Cashier shall release the cheque in a day.',
             'change_reason': 'Consolidated after the 2026 management review.'},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('assessment_id', response.data)

    def test_proposals_work_with_the_switch_on(self):
        self.assertEqual(self.start().status_code, 201)


class StartingTests(ProposalFixture):

    def test_a_concurring_office_may_start_one(self):
        response = self.start()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], Proposal.DRAFT)
        self.assertEqual(response.data['version'], 1)
        self.assertEqual(response.data['initiating_office'], 'ACC')

    def test_a_reader_office_may_not(self):
        client = APIClient()
        client.force_authenticate(user=self.reader)
        response = self.start(client=client)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'not_concurring')

    def test_an_owner_that_concurs_may(self):
        """The VPSD case: an office can own a document and work on it."""
        ManualSeriesOffice.objects.create(
            series=self.series, office=self.vpaf,
            relationship=OfficeLink.CONCURRING,
        )
        vp_person = self.a_person("vp-staff", self.vpaf, Position.ENCODER)
        client = APIClient()
        client.force_authenticate(user=vp_person)
        self.assertEqual(self.start(client=client).status_code, 201)

    def test_an_office_cannot_hold_two_open_proposals_on_one_document(self):
        self.start()
        response = self.start()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'already_open')

    def test_someone_in_two_offices_must_say_which(self):
        """The DCR is signed by an office. Guessing would put the wrong
        one on it."""
        position, _ = Position.objects.get_or_create(
            office=self.budget, kind=Position.ENCODER,
        )
        PositionAssignment.objects.create(
            user=self.drafter, position=position, starts_on=self.today,
        )
        response = self.start()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'office_required')
        self.assertEqual(len(response.data['offices']), 2)

        self.assertEqual(self.start(office=self.accounting).status_code, 201)

    def test_someone_with_no_position_cannot_start_one(self):
        nobody = CustomUser.objects.create_user(
            username="nobody", password=PASSWORD, is_approved=True,
        )
        client = APIClient()
        client.force_authenticate(user=nobody)
        response = self.start(client=client)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'no_position')

    def test_creating_one_is_recorded(self):
        proposal_id = self.start().data['id']
        event = AuditEvent.objects.get(proposal_id=proposal_id)
        self.assertEqual(event.event, AuditEvent.CREATED)
        self.assertEqual(event.office, self.accounting)
        self.assertEqual(event.actor, self.drafter)


class EditingTests(ProposalFixture):

    def setUp(self):
        super().setUp()
        self.proposal_id = self.start().data['id']

    def test_the_editor_shows_the_whole_document(self):
        """Collapsed, but all of it - a drafter has to see what they are
        *not* changing to know whether the change is coherent."""
        data = self.client.get(f'/api/proposals/{self.proposal_id}/').data
        self.assertEqual(len(data['all_sections']), 3)
        self.assertTrue(all(s['change'] is None for s in data['all_sections']))

    def test_editing_a_section_records_the_text_it_replaces(self):
        """The diff a reviewer sees must be the diff the drafter saw, even
        if the section moves underneath both of them."""
        self.edit(self.proposal_id, self.s2, "The Cashier shall release it in a day.")
        change = SectionChange.objects.get(section=self.s2)
        self.assertEqual(change.old_text, self.s2.content)

        self.s2.content = "Something else entirely."
        self.s2.save()
        change.refresh_from_db()
        self.assertNotEqual(change.old_text, self.s2.content)

    def test_an_unchanged_section_does_not_count_as_a_change(self):
        response = self.edit(self.proposal_id, self.s2, self.s2.content)
        self.assertEqual(response.data['changed_sections'], 0)

    def test_putting_a_section_back_removes_the_change(self):
        self.edit(self.proposal_id, self.s2, "Changed.")
        self.assertEqual(SectionChange.objects.count(), 1)
        self.client.delete(
            f'/api/proposals/{self.proposal_id}/sections/{self.s2.id}/'
        )
        self.assertEqual(SectionChange.objects.count(), 0)

    def test_a_section_from_another_document_is_refused(self):
        other_manual = Manual.objects.create(
            title="FAM 6.03", department=self.department, series=self.series,
        )
        stranger = ManualSection.objects.create(
            manual=other_manual, subtitle="1.0", content="x", tag="POLICY",
        )
        response = self.edit(self.proposal_id, stranger, "Changed.")
        self.assertEqual(response.status_code, 404)

    def test_another_office_cannot_edit_it(self):
        client = APIClient()
        client.force_authenticate(user=self.other)
        response = self.edit(self.proposal_id, self.s2, "Changed.", client=client)
        self.assertEqual(response.status_code, 403)

    def test_the_reason_is_required_before_submitting(self):
        self.edit(self.proposal_id, self.s2, "Changed.")
        data = self.client.get(f'/api/proposals/{self.proposal_id}/').data
        self.assertFalse(data['ready_to_submit'])
        self.assertIn(
            'The reason for the change is required.', data['blockers']
        )

    def test_a_proposal_with_no_changes_cannot_be_submitted(self):
        data = self.client.get(f'/api/proposals/{self.proposal_id}/').data
        self.assertIn('Nothing has been changed yet.', data['blockers'])

    def test_a_locked_proposal_cannot_be_edited(self):
        Proposal.objects.filter(pk=self.proposal_id).update(
            status=Proposal.LOCKED
        )
        response = self.edit(self.proposal_id, self.s2, "Changed.")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_open')


class OneOpenProposalPerSectionTests(ProposalFixture):
    """`is_open` carries the constraint across the join to
    `Proposal.status`. A stale value does not raise - it lets two offices
    edit the same section at once and tells neither."""

    def setUp(self):
        super().setUp()
        self.mine = self.start().data['id']
        self.edit(self.mine, self.s2, "Changed by Accounting.")

        self.other_client = APIClient()
        self.other_client.force_authenticate(user=self.other)
        self.theirs = self.start(
            client=self.other_client, office=self.budget
        ).data['id']

    def test_a_second_office_is_told_who_holds_the_section(self):
        response = self.edit(
            self.theirs, self.s2, "Changed by Budget.", client=self.other_client
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_in_another_proposal')
        self.assertEqual(response.data['office'], 'ACC')
        self.assertEqual(response.data['proposal_id'], self.mine)

    def test_a_different_section_proceeds_side_by_side(self):
        response = self.edit(
            self.theirs, self.s3, "Changed by Budget.", client=self.other_client
        )
        self.assertEqual(response.status_code, 200)

    def test_withdrawing_frees_the_section(self):
        Proposal.objects.filter(pk=self.mine).update(status=Proposal.WITHDRAWN)
        Proposal.objects.get(pk=self.mine).refresh_open_changes()

        response = self.edit(
            self.theirs, self.s2, "Changed by Budget.", client=self.other_client
        )
        self.assertEqual(response.status_code, 200)

    def test_locking_keeps_the_section_held(self):
        """Changed in P4. A locked request is on its way to being made
        effective; releasing its sections at the lock let a second office
        start changing the same text, and the two would have met at the
        custodian's desk."""
        Proposal.objects.filter(pk=self.mine).update(status=Proposal.LOCKED)
        Proposal.objects.get(pk=self.mine).refresh_open_changes()
        response = self.edit(self.theirs, self.s2, "x", client=self.other_client)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_in_another_proposal')

    def test_closing_frees_the_section(self):
        """Denied, withdrawn or made effective: the text is free again."""
        for closed in Proposal.CLOSED_STATUSES:
            Proposal.objects.filter(pk=self.mine).update(status=closed)
            Proposal.objects.get(pk=self.mine).refresh_open_changes()
            self.assertFalse(SectionChange.objects.get(section=self.s2, version__proposal_id=self.mine).is_open, closed)
        self.assertEqual(
            self.edit(self.theirs, self.s2, "x", client=self.other_client).status_code,
            200,
        )

    def test_a_superseded_version_stops_holding_the_section(self):
        """Only the current version is open. An office agreed to text that
        no longer exists, and the old rows are history."""
        proposal = Proposal.objects.get(pk=self.mine)
        ProposalVersion.objects.create(proposal=proposal, number=2)
        proposal.refresh_open_changes()

        self.assertFalse(SectionChange.objects.get(section=self.s2).is_open)
        self.assertEqual(
            self.edit(self.theirs, self.s2, "x", client=self.other_client).status_code,
            200,
        )

    # -- the writers that skip save() ------------------------------

    def test_the_database_refuses_two_open_changes_on_one_section(self):
        theirs = ProposalVersion.objects.get(proposal_id=self.theirs)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SectionChange.objects.create(
                    version=theirs, section=self.s2, old_text="x", new_text="y",
                )

    def test_bulk_create_cannot_make_a_second_open_change(self):
        theirs = ProposalVersion.objects.get(proposal_id=self.theirs)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SectionChange.objects.bulk_create([
                    SectionChange(
                        version=theirs, section=self.s2,
                        old_text="x", new_text="y",
                    ),
                ])

    def test_bulk_create_cannot_make_two_in_one_call(self):
        """Neither exists yet, so they have to be caught against each
        other rather than against a row already there."""
        theirs = ProposalVersion.objects.get(proposal_id=self.theirs)
        SectionChange.objects.filter(section=self.s2).delete()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SectionChange.objects.bulk_create([
                    SectionChange(version=theirs, section=self.s3,
                                  old_text="a", new_text="b"),
                    SectionChange(version=theirs, section=self.s3,
                                  old_text="a", new_text="c"),
                ])

    def test_an_update_moving_a_change_to_an_open_version_is_caught(self):
        """The one update that changes the answer. Without recomputing,
        the row would arrive with is_open False and the index would
        ignore it."""
        theirs = ProposalVersion.objects.get(proposal_id=self.theirs)
        spare = SectionChange.objects.create(
            version=theirs, section=self.s3, old_text="a", new_text="b",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SectionChange.objects.filter(pk=spare.pk).update(
                    section=self.s2, version=theirs,
                )

    def test_an_update_sets_the_flag_rather_than_leaving_it_stale(self):
        closed = Proposal.objects.create(
            manual=self.manual, initiating_office=self.registrar,
            created_by=self.reader, status=Proposal.WITHDRAWN,
        )
        closed_version = ProposalVersion.objects.create(
            proposal=closed, number=1,
        )
        change = SectionChange.objects.create(
            version=closed_version, section=self.s3, old_text="a", new_text="b",
        )
        self.assertFalse(change.is_open)

        theirs = ProposalVersion.objects.get(proposal_id=self.theirs)
        SectionChange.objects.filter(pk=change.pk).update(version=theirs)
        change.refresh_from_db()
        self.assertTrue(change.is_open)


class PerSectionCheckTests(ProposalFixture):

    def setUp(self):
        super().setUp()
        self.proposal_id = self.start().data['id']
        self.client.patch(
            f'/api/proposals/{self.proposal_id}/',
            {'overall_reason': 'Consolidated after the 2026 management review.'},
            format='json',
        )

    def check(self, section):
        return self.client.post(
            f'/api/proposals/{self.proposal_id}/sections/{section.id}/check/',
            {}, format='json',
        )

    def test_checking_a_section_stores_a_snapshot(self):
        self.edit(self.proposal_id, self.s2,
                  "The Cashier may release the cheque within five days.")
        response = self.check(self.s2)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNotNone(response.data['assessment'])
        self.assertTrue(response.data['check_is_current'])

        change = SectionChange.objects.get(section=self.s2)
        self.assertIsNotNone(change.assessment_id)
        self.assertEqual(RevisionPreAssessment.objects.count(), 1)

    def test_an_unchanged_section_cannot_be_checked(self):
        self.edit(self.proposal_id, self.s2, self.s2.content)
        response = self.check(self.s2)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'unchanged')

    def test_editing_a_section_clears_only_that_sections_check(self):
        """The whole reason the check is per section: a twenty-section
        document would otherwise be unworkable."""
        self.edit(self.proposal_id, self.s2, "The Cashier may release it.")
        self.edit(self.proposal_id, self.s3, "The Accounting Staff may verify.")
        self.check(self.s2)
        self.check(self.s3)

        self.edit(self.proposal_id, self.s2, "The Cashier might release it.")

        self.assertFalse(SectionChange.objects.get(section=self.s2).check_is_current)
        self.assertTrue(SectionChange.objects.get(section=self.s3).check_is_current)

    def test_an_unchecked_section_blocks_submission_and_is_named(self):
        self.edit(self.proposal_id, self.s2, "The Cashier may release it.")
        data = self.client.get(f'/api/proposals/{self.proposal_id}/').data
        self.assertFalse(data['ready_to_submit'])
        self.assertTrue(
            any('3.0 POLICIES' in b for b in data['blockers']), data['blockers']
        )

    def test_a_fully_checked_proposal_is_ready(self):
        self.edit(self.proposal_id, self.s2, "The Cashier may release it.")
        self.check(self.s2)
        data = self.client.get(f'/api/proposals/{self.proposal_id}/').data
        self.assertTrue(data['ready_to_submit'], data['blockers'])

    def test_the_overall_verdict_is_the_strictest_section(self):
        self.edit(self.proposal_id, self.s2, "The Cashier may release it.")
        self.edit(self.proposal_id, self.s3, "The Accounting Staff may verify.")
        self.check(self.s2)
        self.check(self.s3)

        changes = SectionChange.objects.filter(section__in=[self.s2, self.s3])
        RevisionPreAssessment.objects.filter(
            section_change=changes.get(section=self.s2)
        ).update(verdict='approve')
        RevisionPreAssessment.objects.filter(
            section_change=changes.get(section=self.s3)
        ).update(verdict='reject')

        data = self.client.get(f'/api/proposals/{self.proposal_id}/').data
        self.assertEqual(data['verdict'], 'reject')

    def test_the_retrieval_context_is_stored_with_the_check(self):
        """The advisory reads stored output. The pipeline's trace does not
        keep what retrieval returned, so the view records it."""
        self.edit(self.proposal_id, self.s2, "The Cashier may release it.")
        self.check(self.s2)
        snapshot = RevisionPreAssessment.objects.get()
        self.assertIsInstance(snapshot.retrieved_section_ids, list)

    def test_the_coordinated_advisory_names_the_other_section(self):
        """Stored output only - the ids were recorded when the check ran,
        and nothing is recomputed to produce this."""
        self.edit(self.proposal_id, self.s2, "The Cashier may release it.")
        self.edit(self.proposal_id, self.s3, "The Accounting Staff may verify.")
        self.check(self.s2)
        self.check(self.s3)

        change = SectionChange.objects.get(section=self.s2)
        RevisionPreAssessment.objects.filter(pk=change.assessment_id).update(
            issues=['contradicts_manual'],
            retrieved_section_ids=[self.s3.id],
        )

        data = self.client.get(f'/api/proposals/{self.proposal_id}/').data
        row = next(s for s in data['sections'] if s['section_id'] == self.s2.id)
        self.assertIn('4.0 PROCEDURES', row['assessment']['coordinated_change'])

    def test_no_advisory_when_the_other_section_is_not_being_changed(self):
        self.edit(self.proposal_id, self.s2, "The Cashier may release it.")
        self.check(self.s2)

        change = SectionChange.objects.get(section=self.s2)
        RevisionPreAssessment.objects.filter(pk=change.assessment_id).update(
            issues=['contradicts_manual'],
            retrieved_section_ids=[self.s1.id],
        )

        data = self.client.get(f'/api/proposals/{self.proposal_id}/').data
        row = next(s for s in data['sections'] if s['section_id'] == self.s2.id)
        self.assertNotIn('coordinated_change', row['assessment'])

    def test_no_advisory_without_a_contradiction(self):
        """It explains one concern. Attaching it to anything else would be
        noise on a screen that is meant to be sparse."""
        self.edit(self.proposal_id, self.s2, "The Cashier may release it.")
        self.edit(self.proposal_id, self.s3, "The Accounting Staff may verify.")
        self.check(self.s2)

        change = SectionChange.objects.get(section=self.s2)
        RevisionPreAssessment.objects.filter(pk=change.assessment_id).update(
            issues=['weakened_obligation'],
            retrieved_section_ids=[self.s3.id],
        )

        data = self.client.get(f'/api/proposals/{self.proposal_id}/').data
        row = next(s for s in data['sections'] if s['section_id'] == self.s2.id)
        self.assertNotIn('coordinated_change', row['assessment'])


class OneDraftAtATimeTests(ProposalFixture):
    """One open proposal per office per document - held by the database,
    not only by the view's check, which reads before it inserts."""

    def a_row(self, status=Proposal.DRAFT):
        return Proposal.objects.create(
            manual=self.manual, initiating_office=self.accounting,
            created_by=self.drafter, status=status,
        )

    def test_the_database_refuses_a_second_open_proposal(self):
        self.a_row()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.a_row(Proposal.CONCURRENCE)

    def test_a_closed_one_does_not_count(self):
        self.a_row(Proposal.WITHDRAWN)
        self.a_row(Proposal.EFFECTIVE)
        self.a_row()
        self.assertEqual(Proposal.objects.filter(status=Proposal.DRAFT).count(), 1)

    def test_the_request_that_loses_the_race_is_sent_to_the_draft(self):
        """The check found nothing - the other request had not committed
        yet - and the insert is refused: the answer names the draft."""
        first = self.start().data['id']
        real = proposal_views._open_proposal
        calls = []

        def missed_then_real(manual, office):
            calls.append(1)
            return None if len(calls) == 1 else real(manual, office)

        with mock.patch.object(proposal_views, '_open_proposal', missed_then_real):
            response = self.start()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'already_open')
        self.assertEqual(response.data['proposal_id'], first)
        self.assertEqual(Proposal.objects.filter(manual=self.manual).count(), 1)


class SimultaneousStartTests(ProposalFixture):
    """Two requests at the same moment, on two threads and two connections,
    against a real database file.

    Not the test database itself: it lives in memory as a shared cache,
    where SQLite refuses a second writer outright ("database table is
    locked") instead of waiting - nothing like the file the application
    runs on. So the committed test data is copied to a file, and the two
    threads connect to that with the project's own SQLite options.

    The data has to be committed to be copied, so this class does not run
    inside TestCase's transaction: it reports the database as lacking
    transactions, which makes TestCase flush afterwards instead.
    """

    @classmethod
    def _databases_support_transactions(cls):
        return False

    def test_two_simultaneous_requests_make_exactly_one_draft(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, 'race.sqlite3')
        connection.ensure_connection()
        target = sqlite3.connect(path)
        connection.connection.backup(target)
        # WAL, as the real database already is. Two connections switching a
        # fresh file to it at the same moment is its own collision.
        target.execute('PRAGMA journal_mode=WAL')
        target.close()

        # Both must pass the view's check before either inserts - the
        # race itself, not merely two requests close together.
        both_checked = threading.Barrier(2, timeout=10)
        local = threading.local()
        real = proposal_views._open_proposal

        def check_then_wait(manual, office):
            found = real(manual, office)
            if not getattr(local, 'waited', False):
                local.waited = True
                both_checked.wait()
            return found

        results = []

        def start():
            try:
                client = APIClient()
                client.force_authenticate(user=self.drafter)
                response = client.post('/api/proposals/', {'manual_id': self.manual.id},
                                       format='json')
                results.append((response.status_code, response.data.get('reason')))
            finally:
                connections['default'].close()

        settings_dict = connections.settings['default']
        in_memory = settings_dict['NAME']
        settings_dict['NAME'] = path      # new threads open new connections
        try:
            with mock.patch.object(proposal_views, '_open_proposal', check_then_wait):
                threads = [threading.Thread(target=start) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=30)
        finally:
            settings_dict['NAME'] = in_memory

        check = sqlite3.connect(path)
        drafts = check.execute(
            'select count(*) from api_proposal where manual_id = ?', (self.manual.id,),
        ).fetchone()[0]
        check.close()
        shutil.rmtree(folder, ignore_errors=True)

        self.assertEqual(sorted(results), [(201, None), (409, 'already_open')])
        self.assertEqual(drafts, 1)
