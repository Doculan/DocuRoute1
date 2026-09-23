"""The documents a request produces, and the number it carries.

Phase 3a: the record and the machinery, before anything writes a file.

What has teeth here:

**A lock that produces nothing to sign must not stand.** Generation runs
inside the locking transaction, so a generator that fails takes the lock
with it and the offices keep a proposal they can still work on.

**The record of a scan is append-only.** Replacement supersedes; the
database itself refuses a second live file for the same slot and a second
replacement for the same file.

**The name on disk is never the name the browser sent.**

Every test that expects an error asserts the reason, not only the status.
"""

import datetime
import shutil
import tempfile
from unittest import mock

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from api import documents
from api.models import Attachment, AuditEvent, Proposal, ProposalVersion
from api.tests_concurrence import ConcurrenceFixture


MEDIA = tempfile.mkdtemp(prefix='docuroute-test-media-')

DOCX = ('application/vnd.openxmlformats-officedocument'
        '.wordprocessingml.document')


def fake_generators(*kinds):
    """Stand-ins for 3b's generators: rows and bytes, no layout."""
    def generate(proposal, version, actor):
        made = []
        for kind in kinds:
            attachment = Attachment(
                proposal=proposal, version=version, kind=kind,
                created_by=actor, original_filename=kind + '.docx',
                content_type=DOCX,
            )
            attachment.file.save(
                kind + '.docx', ContentFile(b'generated'), save=False,
            )
            attachment.size_bytes = attachment.file.size
            attachment.save()
            made.append(attachment)
        return made
    return [generate]


def exploding_generator(message='the template would not open'):
    def generate(proposal, version, actor):
        raise RuntimeError(message)
    return [generate]


# --- The DCR number ------------------------------------------

class DcrNumberTests(TestCase):
    """Counted from the numbers already issued, not a stored counter."""

    def test_the_first_number_of_the_year(self):
        self.assertEqual(
            documents.allocate_dcr_number(
                timezone.make_aware(datetime.datetime(2026, 3, 1, 9, 0))
            ),
            'DCR-2026-001',
        )

    def test_it_counts_on_from_what_has_been_issued(self):
        maker = _ProposalMaker()
        maker.with_number('DCR-2026-001')
        maker.with_number('DCR-2026-007')
        self.assertEqual(
            documents.allocate_dcr_number(
                timezone.make_aware(datetime.datetime(2026, 6, 1, 9, 0))
            ),
            'DCR-2026-008',
        )

    def test_each_year_starts_again(self):
        maker = _ProposalMaker()
        maker.with_number('DCR-2026-004')
        self.assertEqual(
            documents.allocate_dcr_number(
                timezone.make_aware(datetime.datetime(2027, 1, 4, 9, 0))
            ),
            'DCR-2027-001',
        )

    def test_the_same_number_cannot_be_issued_twice(self):
        """The index is the backstop when two locks race.

        Without it the second would quietly take the first's place in the
        sequence and two requests would go out on paper as the same DCR.
        """
        maker = _ProposalMaker()
        maker.with_number('DCR-2026-002')
        with self.assertRaises(IntegrityError) as caught:
            with transaction.atomic():
                maker.with_number('DCR-2026-002')
        self.assertIn('api_proposal.dcr_number', str(caught.exception))

    def test_a_proposal_without_a_number_is_not_a_duplicate(self):
        """Every unlocked proposal holds '' and they must not collide."""
        maker = _ProposalMaker()
        maker.with_number('')
        maker.with_number('')
        self.assertEqual(Proposal.objects.filter(dcr_number='').count(), 2)


class _ProposalMaker:
    """The smallest thing that can hold a DCR number."""

    def __init__(self):
        from api.models import CustomUser, Department, Manual, Office
        self.office = Office.objects.create(name="Some Office", abbreviation="SO")
        self.department = Department.objects.create(name="Dept")
        self.manual = Manual.objects.create(title="Doc", department=self.department)
        self.user = CustomUser.objects.create_user(
            username="maker", password="x", is_approved=True,
        )

    def with_number(self, number):
        return Proposal.objects.create(
            manual=self.manual, initiating_office=self.office,
            created_by=self.user, dcr_number=number,
        )


# --- Generation at the lock ----------------------------------

@override_settings(MEDIA_ROOT=MEDIA)
class GenerationAtLockTests(ConcurrenceFixture):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def a_locked_proposal(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, 'concur')
        self.decide(proposal_id, self.cmo_head, 'concur')
        return Proposal.objects.get(pk=proposal_id)

    def test_locking_numbers_the_request(self):
        proposal = self.a_locked_proposal()
        self.assertEqual(proposal.dcr_number, 'DCR-%d-001' % self.today.year)

    def test_an_unlocked_proposal_has_no_number(self):
        """There is no request to number until the content freezes."""
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.assertEqual(Proposal.objects.get(pk=proposal_id).dcr_number, '')

    def test_without_generators_it_rests_at_locked(self):
        """The honest description of a proposal with nothing to sign.

        3b registers the generators; until then `AWAITING_SIGNATURE` would
        tell the office to go and sign documents that do not exist.
        """
        proposal = self.a_locked_proposal()
        self.assertEqual(proposal.status, Proposal.LOCKED)
        self.assertEqual(proposal.attachments.count(), 0)

    def test_with_generators_it_advances_to_awaiting_signature(self):
        with mock.patch.object(
            documents, 'GENERATORS',
            fake_generators(Attachment.DCR_GENERATED, Attachment.PAGES_GENERATED),
        ):
            proposal = self.a_locked_proposal()
        self.assertEqual(proposal.status, Proposal.AWAITING_SIGNATURE)
        self.assertEqual(proposal.attachments.count(), 2)
        event = proposal.events.filter(event=AuditEvent.DOCUMENTS_GENERATED).first()
        self.assertIsNotNone(event)
        self.assertIn(proposal.dcr_number, event.detail)

    def test_half_a_package_does_not_advance(self):
        """Missing the draft copy the form asks to be attached."""
        with mock.patch.object(
            documents, 'GENERATORS', fake_generators(Attachment.DCR_GENERATED),
        ):
            proposal = self.a_locked_proposal()
        self.assertEqual(proposal.status, Proposal.LOCKED)

    def test_a_failing_generator_rolls_the_lock_back(self):
        """The offices keep a proposal they can still work on.

        A proposal frozen with nothing to sign would be a dead end: no
        screen could act on it and nobody could undo it.
        """
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, 'concur')

        with mock.patch.object(documents, 'GENERATORS', exploding_generator()):
            with self.assertRaises(RuntimeError) as caught:
                self.decide(proposal_id, self.cmo_head, 'concur')
        self.assertIn('template would not open', str(caught.exception))

        proposal = Proposal.objects.get(pk=proposal_id)
        self.assertEqual(proposal.status, Proposal.CONCURRENCE)
        self.assertEqual(proposal.dcr_number, '')
        self.assertIsNone(proposal.locked_at)
        self.assertFalse(proposal.events.filter(event=AuditEvent.LOCKED).exists())
        self.assertEqual(proposal.attachments.count(), 0)

    def test_a_returned_request_does_not_burn_a_number(self):
        """One request, one number, however many drafts it took.

        Numbers are allocated at the lock, not at submission, so a
        proposal that goes out twice must still come back as the first
        DCR of the year rather than the second.
        """
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, 'return', feedback='Too broad.')

        self.client.put(
            '/api/proposals/%d/sections/%d/' % (proposal_id, self.s1.id),
            {'new_text': "The Cashier shall release the cheque within two days."},
            format='json',
        )
        self.client.post(
            '/api/proposals/%d/sections/%d/check/' % (proposal_id, self.s1.id),
            {}, format='json',
        )
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, 'concur')
        self.decide(proposal_id, self.cmo_head, 'concur')

        proposal = Proposal.objects.get(pk=proposal_id)
        self.assertEqual(proposal.status, Proposal.LOCKED)
        self.assertEqual(proposal.dcr_number, 'DCR-%d-001' % self.today.year)


# --- The attachment record -----------------------------------

@override_settings(MEDIA_ROOT=MEDIA)
class AttachmentRecordTests(ConcurrenceFixture):

    def setUp(self):
        super().setUp()
        self.proposal = Proposal.objects.create(
            manual=self.manual, initiating_office=self.accounting,
            created_by=self.acc_enc,
        )
        self.version = ProposalVersion.objects.create(
            proposal=self.proposal, number=1,
        )

    def an_attachment(self, kind=Attachment.SIGNED_DCR, slot='', **kwargs):
        attachment = Attachment(
            proposal=self.proposal, version=self.version, kind=kind, slot=slot,
            created_by=self.acc_head, **kwargs
        )
        attachment.file.save('scan.pdf', ContentFile(b'%PDF-1.4 x'), save=False)
        attachment.size_bytes = attachment.file.size
        attachment.save()
        return attachment

    def test_the_name_on_disk_is_not_the_name_the_browser_sent(self):
        """An uploaded filename is attacker-controlled.

        `Manual.file` once wrote uploads back into the folder being
        scanned; this one keeps the chosen name as data, never as a path.
        """
        attachment = Attachment(
            proposal=self.proposal, version=self.version,
            kind=Attachment.SIGNED_DCR, created_by=self.acc_head,
            original_filename='../../../settings.py',
        )
        attachment.file.save('../../../settings.py', ContentFile(b'x'), save=False)
        attachment.save()

        self.assertNotIn('..', attachment.file.name)
        self.assertNotIn('settings', attachment.file.name)
        self.assertTrue(
            attachment.file.name.startswith('proposals/%d/' % self.proposal.id)
        )
        self.assertEqual(attachment.original_filename, '../../../settings.py')

    def test_two_live_files_for_one_slot_are_refused(self):
        self.an_attachment()
        with self.assertRaises(IntegrityError) as caught:
            with transaction.atomic():
                self.an_attachment()
        message = str(caught.exception)
        for column in ('version_id', 'kind', 'slot'):
            self.assertIn(column, message)

    def test_superseding_makes_room_for_the_replacement(self):
        first = self.an_attachment()
        first.superseded_at = timezone.now()
        first.save(update_fields=['superseded_at'])

        second = self.an_attachment(
            supersedes=first, replacement_reason='The first scan was unreadable.',
        )
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)
        self.assertEqual(first.superseded_by.get(), second)

    def test_one_replacement_per_file(self):
        """Two rows claiming the same predecessor make the chain unreadable."""
        first = self.an_attachment()
        first.superseded_at = timezone.now()
        first.save(update_fields=['superseded_at'])
        self.an_attachment(supersedes=first)

        orphan = Attachment(
            proposal=self.proposal, version=self.version,
            kind=Attachment.SIGNED_PAGES, created_by=self.acc_head,
            supersedes=first,
        )
        orphan.file.save('other.pdf', ContentFile(b'x'), save=False)
        with self.assertRaises(IntegrityError) as caught:
            with transaction.atomic():
                orphan.save()
        self.assertIn('api_attachment.supersedes_id', str(caught.exception))

    def test_the_same_kind_may_cover_several_sections(self):
        """One draft page per changed section, so the slot separates them."""
        self.an_attachment(
            kind=Attachment.SIGNED_PAGES, slot=str(self.s1.id), section=self.s1,
        )
        self.an_attachment(
            kind=Attachment.SIGNED_PAGES, slot=str(self.s2.id), section=self.s2,
        )
        self.assertEqual(
            Attachment.objects.filter(
                version=self.version, kind=Attachment.SIGNED_PAGES,
            ).count(),
            2,
        )

    def test_what_is_still_outstanding(self):
        self.assertEqual(
            documents.scans_outstanding(self.proposal, self.version),
            [Attachment.SIGNED_DCR, Attachment.SIGNED_PAGES],
        )
        self.an_attachment(kind=Attachment.SIGNED_DCR)
        self.assertEqual(
            documents.scans_outstanding(self.proposal, self.version),
            [Attachment.SIGNED_PAGES],
        )

    def test_the_dashboard_counts_every_frozen_status(self):
        """Not just `LOCKED`.

        Once 3b advances a new lock to `AWAITING_SIGNATURE`, a counter
        reading one status would fall to zero while the proposals piled
        up - and nothing would say so.
        """
        from api.models import CustomUser

        # The same account the dashboard's own tests use: `role` is what
        # `IsAdminRole` reads, and `is_staff` is only for Django's /admin/.
        admin = CustomUser.objects.create_user(
            username='counter_admin', password='x', role='admin',
            is_approved=True,
        )
        for status in (Proposal.LOCKED, Proposal.AWAITING_SIGNATURE,
                       Proposal.READY_FOR_IMR):
            Proposal.objects.create(
                manual=self.manual, initiating_office=self.accounting,
                created_by=self.acc_enc, status=status,
            )
        response = self.as_(admin).get('/api/admin/dashboard/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data['attention']['proposals_locked'], 3,
        )

    def test_a_superseded_scan_does_not_count_as_uploaded(self):
        first = self.an_attachment(kind=Attachment.SIGNED_DCR)
        first.superseded_at = timezone.now()
        first.save(update_fields=['superseded_at'])
        self.assertIn(
            Attachment.SIGNED_DCR,
            documents.scans_outstanding(self.proposal, self.version),
        )


class TransactionGuardTests(SimpleTestCase):
    """The guard needs a test that is not itself inside a transaction.

    Django's `TestCase` wraps every test in one, so the check would pass
    there whatever it did. `SimpleTestCase` leaves the connection in its
    ordinary autocommit state, which is the state the guard exists to
    catch.
    """

    def test_generation_refuses_to_run_outside_a_transaction(self):
        """Otherwise a partial failure leaves a frozen, half-documented row."""
        with self.assertRaises(RuntimeError) as caught:
            documents.generate_package(None, None, None)
        self.assertIn('inside the transaction', str(caught.exception))
