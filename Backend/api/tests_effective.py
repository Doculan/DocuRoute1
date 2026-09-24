"""Phase 4c: section 5, making a change effective, what readers see.

What has teeth here:

**Only the Document Custodian makes a change effective** - with the
password, never on their own office's request, only for a package that
is with them.

**All of it or none of it.** The locked text goes into the document, the
old text into the section's history linked to the request, section 5
becomes the document's status, and the request is closed - or, if a
changed section no longer reads as the offices saw it, nothing at all.

**No text that is not yet in force.** A future effectivity date is
refused, and a revision lower than the current one, where both are plain
numbers.

**A baseline, once**, for documents that carry real revisions on paper.

**Readers see the official status**: the document's number, revision and
effectivity date, and on each section a request has changed, its own
revision - never v3's counters.

Every test that expects an error asserts the reason, not only the status.
"""

import datetime
from unittest import mock

from django.test import SimpleTestCase

from api import qms_views
from api.document_status import revision_goes_backwards, status_goes_backwards
from api.models import (
    Attachment, AuditEvent, CustomUser, DocumentStatus, Manual,
    ManualSection, Position, PositionAssignment, Proposal, QmsDecision,
    SectionHistory,
)
from api.tests_concurrence import REASON
from api.tests_custodian import ApprovalFixture


class EffectiveFixture(ApprovalFixture):
    """A complete package with the custodian."""

    def setUp(self):
        super().setUp()
        response = self.upload_approval()
        assert response.status_code == 201, response.data
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)
        self.old = {s.pk: s.content for s in (self.s1, self.s2)}
        self.new = dict(self.proposal.current_version().changes.values_list(
            'section_id', 'new_text'))
        # Not part of the request.
        self.s3 = ManualSection.objects.create(
            manual=self.manual, subtitle='5.0 FORMS', order=2,
            content='Form FAM-01.', tag='PROCEDURE',
        )

    def entry(self, **overrides):
        body = {
            'document_number': 'FAM 6.02', 'version': '01', 'revision': '3',
            'effective_on': self.today.isoformat(),
            'updated_in_ids_on': self.today.isoformat(),
        }
        body.update(overrides)
        return body

    def make_effective(self, user=None, token=True, **overrides):
        user = user or self.custodian
        extra = {'HTTP_X_REAUTH_TOKEN': self.token(user)} if token else {}
        return self.as_(user).post(self.url + 'custodian/effective/',
                                   self.entry(**overrides), format='json', **extra)

    def baseline(self, user=None, token=True, **body):
        user = user or self.custodian
        extra = {'HTTP_X_REAUTH_TOKEN': self.token(user)} if token else {}
        data = {'document_number': 'FAM 6.02', 'version': '01', 'revision': '2',
                'effective_on': (self.today - datetime.timedelta(days=400)).isoformat()}
        data.update(body)
        return self.as_(user).post('/api/manuals/%d/status/baseline/' % self.manual.id,
                                   data, format='json', **extra)

    def text(self, section):
        return ManualSection.objects.get(pk=section.pk).content

    def assert_nothing_written(self):
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)
        for section in (self.s1, self.s2):
            self.assertEqual(self.text(section), self.old[section.pk])
        self.assertFalse(DocumentStatus.objects.filter(proposal=self.proposal).exists())
        self.assertFalse(SectionHistory.objects.filter(proposal=self.proposal).exists())
        self.assertIsNone(Manual.objects.get(pk=self.manual.pk).current_status)
        self.assertTrue(all(self.held()))


# --- making it effective -------------------------------------

class MakeEffectiveTests(EffectiveFixture):

    def test_the_text_changes_and_the_request_is_effective(self):
        response = self.make_effective()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), Proposal.EFFECTIVE)
        for section in (self.s1, self.s2):
            self.assertEqual(self.text(section), self.new[section.pk])

    def test_section_five_becomes_the_documents_status(self):
        self.make_effective()
        status = DocumentStatus.objects.get(proposal=self.proposal)
        self.assertEqual(
            (status.document_number, status.version, status.revision,
             status.effective_on, status.updated_in_ids_on),
            ('FAM 6.02', '01', '3', self.today, self.today))
        self.assertEqual(status.recorded_as, 'Quality Management Office — Document Custodian')
        self.assertEqual(Manual.objects.get(pk=self.manual.pk).current_status, status)
        for section in (self.s1, self.s2):
            self.assertEqual(ManualSection.objects.get(pk=section.pk).status_changed, status)

    def test_the_old_text_is_kept_in_history_linked_to_the_request(self):
        before = ManualSection.objects.get(pk=self.s1.pk).version
        self.make_effective()
        row = SectionHistory.objects.get(section=self.s1, proposal=self.proposal)
        self.assertEqual(row.source, 'proposal')
        self.assertEqual(row.content, self.old[self.s1.pk])
        self.assertEqual(row.version, before)
        self.assertIn(REASON, row.change_reason)
        self.assertEqual(ManualSection.objects.get(pk=self.s1.pk).version, before + 1)

    def test_the_admins_history_names_the_dcr(self):
        self.make_effective()
        self.proposal.refresh_from_db()
        admin = CustomUser.objects.create_user(
            username='sysadmin', password='x', is_approved=True, role='admin',
            system_role=CustomUser.SYSTEM_ADMIN)
        rows = self.as_(admin).get('/api/sections/%d/history/' % self.s1.pk).data
        linked = [r for r in rows if r['source'] == 'proposal']
        self.assertEqual([r['dcr_number'] for r in linked], [self.proposal.dcr_number])

    def test_sections_outside_the_request_are_untouched(self):
        self.make_effective()
        s3 = ManualSection.objects.get(pk=self.s3.pk)
        self.assertEqual(s3.content, 'Form FAM-01.')
        self.assertIsNone(s3.status_changed)
        self.assertFalse(s3.history.exists())

    def test_changed_sections_are_tagged_again(self):
        with mock.patch.object(qms_views, 'predict_section', return_value='RESPONSIBILITY'):
            self.make_effective()
        self.assertEqual(ManualSection.objects.get(pk=self.s1.pk).tag, 'RESPONSIBILITY')
        self.assertEqual(ManualSection.objects.get(pk=self.s3.pk).tag, 'PROCEDURE')

    def test_it_is_recorded_and_the_sections_are_free(self):
        self.make_effective()
        decision = QmsDecision.objects.get(proposal=self.proposal, outcome='effective')
        self.assertEqual(decision.stage, 'custodian')
        event = self.proposal.events.get(event=AuditEvent.MADE_EFFECTIVE)
        self.assertIn('revision 3', event.detail)
        self.assertFalse(any(self.held()))

    def test_v3s_counter_still_counts(self):
        before = Manual.objects.get(pk=self.manual.pk).revision
        self.make_effective()
        self.assertEqual(Manual.objects.get(pk=self.manual.pk).revision, before + 1)

    def test_every_office_involved_sees_section_five(self):
        self.make_effective()
        for user in (self.acc_enc, self.bud_head):
            data = self.as_(user).get(self.url + 'full/').data
            self.assertEqual(data['status'], Proposal.EFFECTIVE)
            self.assertEqual(data['document_status']['revision'], '3')


class MakeEffectiveRefusalTests(EffectiveFixture):

    def test_it_needs_the_password(self):
        response = self.make_effective(token=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'reauth_required')
        self.assert_nothing_written()

    def test_only_the_custodian(self):
        for user in (self.imr, self.acc_head, self.bud_head):
            response = self.make_effective(user=user)
            self.assertEqual(response.status_code, 403, user.username)
            self.assertEqual(response.data['reason'], 'not_custodian')
        self.assert_nothing_written()

    def test_never_on_their_own_offices_request(self):
        position, _ = Position.objects.get_or_create(office=self.accounting, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=self.custodian, position=position, starts_on=self.today)
        response = self.make_effective()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'conflict_of_interest')
        self.assert_nothing_written()

    def test_only_a_package_with_the_custodian(self):
        self.returns([Attachment.SIGNED_DCR])
        response = self.make_effective()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_with_custodian')

    def test_only_once(self):
        self.make_effective()
        response = self.make_effective(revision='4')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_with_custodian')
        self.assertEqual(DocumentStatus.objects.filter(manual=self.manual).count(), 1)

    def test_a_future_effectivity_date_is_refused(self):
        tomorrow = (self.today + datetime.timedelta(days=1)).isoformat()
        response = self.make_effective(effective_on=tomorrow)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'future_date')
        self.assertEqual(response.data['field'], 'effective_on')
        self.assert_nothing_written()

    def test_so_is_a_future_ids_date(self):
        tomorrow = (self.today + datetime.timedelta(days=1)).isoformat()
        response = self.make_effective(updated_in_ids_on=tomorrow)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'future_date')
        self.assertEqual(response.data['field'], 'updated_in_ids_on')

    def test_every_field_of_section_five_is_required(self):
        for field in ('document_number', 'version', 'revision',
                      'effective_on', 'updated_in_ids_on'):
            response = self.make_effective(**{field: ' '})
            self.assertEqual(response.status_code, 400, field)
            self.assertEqual(response.data['reason'], 'field_required', field)
            self.assertEqual(response.data['field'], field)
        self.assert_nothing_written()

    def test_a_date_must_be_a_date(self):
        response = self.make_effective(effective_on='24/09/2026')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'invalid_date')

    def test_a_lower_revision_is_refused(self):
        self.assertEqual(self.baseline(revision='5').status_code, 201)
        response = self.make_effective(revision='4')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'revision_backwards')
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)

    def test_a_lower_version_is_refused(self):
        self.assertEqual(self.baseline(version='02', revision='5').status_code, 201)
        response = self.make_effective(version='01', revision='6')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'version_backwards')
        self.assertEqual(response.data['field'], 'version')
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)

    def test_a_new_version_may_restart_its_revisions(self):
        self.assertEqual(self.baseline(version='01', revision='5').status_code, 201)
        response = self.make_effective(version='02', revision='0')
        self.assertEqual(response.status_code, 200, response.data)

    def test_a_revision_that_is_not_a_number_is_recorded_as_written(self):
        self.assertEqual(self.baseline(revision='5').status_code, 201)
        response = self.make_effective(revision='Rev. A')
        self.assertEqual(response.status_code, 200, response.data)

    def test_a_section_changed_since_stops_everything(self):
        """s1 comes first and would be written; s2 was touched. Nothing is."""
        ManualSection.objects.filter(pk=self.s2.pk).update(content='Edited around the hold.')
        self.old[self.s2.pk] = 'Edited around the hold.'
        response = self.make_effective()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_changed')
        self.assertIn(self.s2.subtitle, response.data['error'])
        self.assert_nothing_written()


class RevisionOrderTests(SimpleTestCase):
    """Plain numbers are ordered; anything else is recorded as written."""

    def test_the_rule(self):
        self.assertTrue(revision_goes_backwards('3', '2'))
        self.assertFalse(revision_goes_backwards('9', '10'))
        self.assertFalse(revision_goes_backwards('3', '3'))
        self.assertFalse(revision_goes_backwards('Rev. 3', '1'))
        self.assertFalse(revision_goes_backwards('3', 'A'))

    def test_version_first_then_revision_within_it(self):
        now = DocumentStatus(version='02', revision='5')
        self.assertEqual(status_goes_backwards(now, '01', '9'), 'version')
        self.assertEqual(status_goes_backwards(now, '2', '4'), 'revision')   # "02" is "2"
        self.assertIsNone(status_goes_backwards(now, '03', '0'))             # a new version restarts
        self.assertIsNone(status_goes_backwards(now, '02', '6'))
        self.assertIsNone(status_goes_backwards(now, 'B', '0'))              # not ordered


# --- the form's starting values ------------------------------

class SuggestionTests(EffectiveFixture):

    def test_it_starts_from_the_current_entry_one_revision_up(self):
        self.baseline(revision='2')
        data = self.as_(self.custodian).get(self.url + 'custodian/effective/').data
        self.assertEqual(data['current']['revision'], '2')
        self.assertEqual(data['suggested']['document_number'], 'FAM 6.02')
        self.assertEqual(data['suggested']['revision'], '3')
        self.assertEqual(data['suggested']['effective_on'], self.today.isoformat())

    def test_the_custodian_sees_they_can_make_it_effective(self):
        self.assertTrue(self.as_(self.custodian).get(self.url + 'full/').data['can_make_effective'])
        self.assertFalse(self.as_(self.imr).get(self.url + 'full/').data['can_make_effective'])


# --- the baseline --------------------------------------------

class BaselineTests(EffectiveFixture):

    def test_the_custodian_records_where_a_document_stands(self):
        response = self.baseline()
        self.assertEqual(response.status_code, 201, response.data)
        status = Manual.objects.get(pk=self.manual.pk).current_status
        self.assertTrue(status.is_baseline)
        self.assertEqual(status.revision, '2')
        self.assertIsNone(status.updated_in_ids_on)

    def test_it_needs_the_password(self):
        response = self.baseline(token=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'reauth_required')
        self.assertFalse(DocumentStatus.objects.exists())

    def test_only_the_custodian(self):
        for user in (self.imr, self.acc_head):
            response = self.baseline(user=user)
            self.assertEqual(response.status_code, 403, user.username)
            self.assertEqual(response.data['reason'], 'not_custodian')
        self.assertFalse(DocumentStatus.objects.exists())

    def test_only_once(self):
        self.baseline()
        response = self.baseline(revision='7')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'status_exists')

    def test_not_once_a_request_has_set_one(self):
        self.make_effective()
        response = self.baseline()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'status_exists')

    def test_not_in_the_future(self):
        response = self.baseline(effective_on=(self.today + datetime.timedelta(days=3)).isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'future_date')

    def test_the_reader_screen_offers_it_only_to_the_custodian_and_only_once(self):
        path = '/api/manuals/%d/sections/' % self.manual.id
        self.assertTrue(self.as_(self.custodian).get(path).data['can_record_baseline'])
        self.assertFalse(self.as_(self.imr).get(path).data['can_record_baseline'])
        self.baseline()
        self.assertFalse(self.as_(self.custodian).get(path).data['can_record_baseline'])


# --- what readers see ----------------------------------------

class ReaderTests(EffectiveFixture):

    path = '/api/manuals/%d/sections/'

    def sections(self, user):
        return self.as_(user).get(self.path % self.manual.id).data

    def test_a_baseline_shows_on_the_document_and_nothing_on_its_sections(self):
        self.baseline()
        data = self.sections(self.bud_enc)
        self.assertEqual(data['status']['revision'], '2')
        self.assertTrue(data['status']['is_baseline'])
        self.assertTrue(all(s['revision'] is None for s in data['sections']))

    def test_after_a_change_the_document_and_its_changed_sections_show_it(self):
        self.baseline()
        self.make_effective()
        self.proposal.refresh_from_db()
        data = self.sections(self.bud_enc)
        self.assertEqual(data['status']['revision'], '3')
        self.assertEqual(data['status']['dcr_number'], self.proposal.dcr_number)
        by_id = {s['id']: s for s in data['sections']}
        self.assertEqual(by_id[self.s1.pk]['revision'],
                         {'revision': '3', 'effective_on': self.today,
                          'dcr_number': self.proposal.dcr_number})
        self.assertIsNone(by_id[self.s3.pk]['revision'])

    def test_a_changed_section_lists_the_request_that_changed_it(self):
        self.make_effective()
        self.proposal.refresh_from_db()
        s1 = {s['id']: s for s in self.sections(self.bud_enc)['sections']}[self.s1.pk]
        self.assertEqual([c['dcr_number'] for c in s1['changes']], [self.proposal.dcr_number])
        self.assertEqual(s1['changes'][0]['text_before'], self.old[self.s1.pk])
        self.assertEqual(s1['changes'][0]['revision'], '3')

    def test_the_manual_list_carries_the_status(self):
        self.make_effective()
        rows = self.as_(self.bud_enc).get('/api/staff/manuals/').data
        row = [r for r in rows if r['id'] == self.manual.id][0]
        self.assertEqual(row['status']['revision'], '3')
        self.assertEqual(row['status']['effective_on'], self.today)


# --- correcting a baseline -----------------------------------

class BaselineCorrectionTests(EffectiveFixture):

    def setUp(self):
        super().setUp()
        response = self.baseline(revision='2')
        assert response.status_code == 201, response.data
        self.first = Manual.objects.get(pk=self.manual.pk).current_status

    def correct(self, user=None, token=True, reason='The paper copy reads revision 4.', **fields):
        user = user or self.custodian
        extra = {'HTTP_X_REAUTH_TOKEN': self.token(user)} if token else {}
        body = {'document_number': 'FAM 6.02', 'version': '01', 'revision': '4',
                'effective_on': (self.today - datetime.timedelta(days=300)).isoformat(),
                'reason': reason}
        body.update(fields)
        return self.as_(user).post('/api/manuals/%d/status/baseline/correct/' % self.manual.id,
                                   body, format='json', **extra)

    def current(self):
        return Manual.objects.get(pk=self.manual.pk).current_status

    def test_the_custodian_corrects_it_and_the_old_row_is_kept(self):
        response = self.correct()
        self.assertEqual(response.status_code, 201, response.data)
        new = self.current()
        self.assertEqual((new.revision, new.correction_reason),
                         ('4', 'The paper copy reads revision 4.'))
        self.assertTrue(new.is_baseline)
        self.first.refresh_from_db()
        self.assertEqual(self.first.revision, '2', 'superseded, not overwritten')
        self.assertEqual(self.first.superseded_by, new)
        self.assertIsNotNone(self.first.superseded_at)

    def test_a_correction_may_go_lower(self):
        """It replaces a mistake; it does not follow it."""
        self.assertEqual(self.correct(revision='1').status_code, 201)
        self.assertEqual(self.current().revision, '1')

    def test_corrected_twice_the_chain_holds(self):
        self.correct(revision='3')
        second = self.current()
        self.correct(revision='4')
        second.refresh_from_db()
        self.assertEqual(second.superseded_by, self.current())
        self.assertEqual(DocumentStatus.objects.filter(manual=self.manual).count(), 3)

    def test_it_needs_the_password(self):
        response = self.correct(token=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'reauth_required')
        self.assertEqual(self.current(), self.first)

    def test_it_needs_a_reason(self):
        response = self.correct(reason='  ')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'reason_required')
        self.assertEqual(self.current(), self.first)

    def test_only_the_custodian(self):
        for user in (self.imr, self.acc_head):
            response = self.correct(user=user)
            self.assertEqual(response.status_code, 403, user.username)
            self.assertEqual(response.data['reason'], 'not_custodian')
        self.assertEqual(self.current(), self.first)

    def test_not_in_the_future(self):
        response = self.correct(effective_on=(self.today + datetime.timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'future_date')

    def test_not_once_a_change_has_been_made_effective(self):
        self.assertEqual(self.make_effective().status_code, 200)
        response = self.correct()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_correctable')
        self.assertEqual(DocumentStatus.objects.filter(manual=self.manual).count(), 2)

    def test_the_reader_screen_offers_it_only_while_it_is_allowed(self):
        path = '/api/manuals/%d/sections/' % self.manual.id
        self.assertTrue(self.as_(self.custodian).get(path).data['can_correct_baseline'])
        self.assertFalse(self.as_(self.imr).get(path).data['can_correct_baseline'])
        self.make_effective()
        self.assertFalse(self.as_(self.custodian).get(path).data['can_correct_baseline'])

    def test_the_next_change_follows_the_correction(self):
        self.correct(revision='4')
        data = self.as_(self.custodian).get(self.url + 'custodian/effective/').data
        self.assertEqual(data['suggested']['revision'], '5')
        response = self.make_effective(revision='3')
        self.assertEqual(response.data['reason'], 'revision_backwards')


class NoBaselineToCorrectTests(EffectiveFixture):

    def test_there_must_be_a_baseline(self):
        response = self.as_(self.custodian).post(
            '/api/manuals/%d/status/baseline/correct/' % self.manual.id,
            {'document_number': 'FAM 6.02', 'version': '01', 'revision': '1',
             'effective_on': self.today.isoformat(), 'reason': 'x'},
            format='json', HTTP_X_REAUTH_TOKEN=self.token(self.custodian))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_correctable')
