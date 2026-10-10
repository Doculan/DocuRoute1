"""Phase 4b: the approving authority's signed DCR, and the custodian's return.

What has teeth here:

**After the IMR accepts, the IMR or requesting office uploads the DCR the
approving authority signed**, and the request goes to the custodian.
Other QMS colleagues do not inherit this permission from their office.

**The custodian returns a package for defects only.** They name which
signed copies are defective and say why. Only those copies may then be
replaced - with a reason and the password - and once every one of them
has been, the package is back with the custodian. Content never changes
here: nothing in this stage writes a section.

Every test that expects an error asserts the reason, not only the status.
"""

from api.models import (
    Attachment, AuditEvent, Notification, Position, PositionAssignment, Proposal,
    QmsDecision, SectionChange,
)
from api.tests_package import a_file, pdf_bytes
from api.tests_qms import QmsFixture


class ApprovalFixture(QmsFixture):
    """A request the IMR has accepted."""

    def setUp(self):
        super().setUp()
        response = self.imr_decides('accept', 'In order.')
        assert response.status_code == 200, response.data
        self.assertEqual(self.status(), Proposal.AWAITING_APPROVAL)

    def upload_approval(self, user=None, file=None):
        return self.upload(Attachment.APPROVED_DCR, file or a_file('approved.pdf'), user=user)

    def returns(self, kinds, comments='The signature on page 1 is missing.',
                user=None):
        return self.as_(user or self.custodian).post(
            self.url + 'custodian/return/', {'kinds': kinds, 'comments': comments},
            format='json',
        )

    def current(self, kind):
        return Attachment.objects.get(proposal=self.proposal, kind=kind,
                                      superseded_at__isnull=True)


# --- the approving authority's signed DCR --------------------

class ApprovalUploadTests(ApprovalFixture):

    def test_imr_upload_moves_to_custodian_and_records_the_actual_position(self):
        import io
        from docx import Document
        response = self.upload_approval(user=self.imr)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)
        scan = self.current(Attachment.APPROVED_DCR)
        self.assertEqual(scan.created_by, self.imr)
        self.assertEqual(scan.created_as, 'Quality Management Office — Integrated Management Representative')
        for event in self.proposal.events.filter(actor=self.imr, event__in=[
                AuditEvent.SCAN_UPLOADED, AuditEvent.APPROVAL_UPLOADED]):
            self.assertEqual(event.office, self.qms)
            self.assertEqual(event.position.kind, Position.IMR)
        report = self.as_(self.imr).post(self.url + 'trail-report/', {}, format='json')
        self.assertEqual(report.status_code, 200)
        doc = Document(io.BytesIO(report.content))
        text = '\n'.join(p.text for p in doc.paragraphs) + '\n'.join(
            c.text for t in doc.tables for r in t.rows for c in r.cells)
        self.assertIn('With the Document Custodian', text)
        self.assertIn(scan.created_as, text)

    def test_handoff_notifies_the_requesting_office_and_custodian_only(self):
        colleague = self.qms_person('qms_encoder', Position.ENCODER)
        self.upload_approval(user=self.imr)
        event = self.proposal.events.get(event=AuditEvent.APPROVAL_UPLOADED)
        recipients = set(Notification.objects.filter(event=event).values_list('user_id', flat=True))
        self.assertEqual(recipients, {self.acc_enc.id, self.acc_head.id, self.custodian.id})
        from api.notifications import message
        self.assertIn('uploaded by the IMR; awaiting Document Custodian acceptance', message(event))
        self.assertNotIn(colleague.id, recipients)

    def test_office_fallback_notifies_custodian_without_claiming_imr_upload(self):
        self.upload_approval()
        event = self.proposal.events.get(event=AuditEvent.APPROVAL_UPLOADED)
        self.assertTrue(Notification.objects.filter(event=event, user=self.custodian).exists())
        from api.notifications import message
        self.assertIn('uploaded by Accounting Office', message(event))

    def test_former_custodian_with_another_active_post_is_not_notified(self):
        from datetime import timedelta
        PositionAssignment.objects.filter(user=self.custodian).update(
            starts_on=self.today - timedelta(days=2), ends_on=self.today - timedelta(days=1))
        encoder, _ = Position.objects.get_or_create(office=self.qms, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=self.custodian, position=encoder, starts_on=self.today)
        self.upload_approval(user=self.imr)
        self.assertFalse(Notification.objects.filter(user=self.custodian, event__event=AuditEvent.APPROVAL_UPLOADED).exists())

    def test_imr_can_find_accepted_proposals_until_upload(self):
        queue = self.as_(self.imr).get('/api/qms/queue/').data
        self.assertEqual([p['id'] for p in queue['approval']], [self.proposal.id])
        rows = self.as_(self.imr).get(self.url + 'package/').data['scans']
        self.assertTrue(rows[Attachment.APPROVED_DCR]['can_upload'])
        self.assertFalse(rows[Attachment.SIGNED_DCR]['can_replace'])
        self.upload_approval(user=self.imr)
        self.assertEqual(self.as_(self.imr).get('/api/qms/queue/').data['approval'], [])
        self.assertEqual([p['id'] for p in self.as_(self.custodian).get('/api/qms/queue/').data['custodian']], [self.proposal.id])

    def test_qms_office_membership_alone_does_not_allow_upload(self):
        colleague = self.qms_person('qms_encoder', Position.ENCODER)
        for user in (colleague, self.custodian):
            self.assertFalse(self.as_(user).get(self.url + 'package/').data['scans'][Attachment.APPROVED_DCR]['can_upload'])
            self.assertEqual(self.upload_approval(user=user).status_code, 403)
        self.assertEqual(self.status(), Proposal.AWAITING_APPROVAL)

    def test_imr_cannot_skip_acceptance_or_upload_other_copies(self):
        Proposal.objects.filter(pk=self.proposal.pk).update(status=Proposal.READY_FOR_IMR)
        self.assertEqual(self.upload_approval(user=self.imr).status_code, 409)
        self.assertEqual(self.upload(Attachment.SIGNED_PAGES, user=self.imr).status_code, 403)
        self.assertFalse(self.proposal.events.filter(event=AuditEvent.APPROVAL_UPLOADED).exists())

    def test_invalid_imr_scan_does_not_advance_or_notify(self):
        response = self.upload_approval(user=self.imr, file=a_file('bad.pdf', b'bad'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.status(), Proposal.AWAITING_APPROVAL)
        self.assertFalse(Notification.objects.filter(event__event=AuditEvent.APPROVAL_UPLOADED).exists())

    def test_ended_imr_assignment_cannot_upload(self):
        from datetime import timedelta
        PositionAssignment.objects.filter(user=self.imr).update(
            starts_on=self.today - timedelta(days=2), ends_on=self.today - timedelta(days=1))
        self.assertEqual(self.upload_approval(user=self.imr).status_code, 403)
        self.assertFalse(self.as_(self.imr).get(self.url + 'package/').data['scans'][Attachment.APPROVED_DCR]['can_upload'])

    def test_imr_can_replace_only_the_returned_final_dcr_with_password(self):
        self.upload_approval(user=self.imr)
        old = self.current(Attachment.APPROVED_DCR)
        self.assertEqual(self.replace(old.id, user=self.imr).status_code, 409)
        self.assertEqual(self.returns([Attachment.APPROVED_DCR]).status_code, 200)
        self.assertEqual(len(self.as_(self.imr).get('/api/qms/queue/').data['approval']), 1)
        self.assertEqual(self.replace(old.id, user=self.imr, token=False).status_code, 403)
        self.assertEqual(self.replace(old.id, user=self.imr).status_code, 200)
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)
        old.refresh_from_db()
        self.assertFalse(old.is_current)
        self.assertEqual(self.current(Attachment.APPROVED_DCR).created_by, self.imr)

    def test_the_office_uploads_it_and_the_request_goes_to_the_custodian(self):
        response = self.upload_approval()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)
        self.assertEqual(self.current(Attachment.APPROVED_DCR).created_as,
                         'Accounting Office — Encoder')
        self.assertTrue(self.proposal.events.filter(event=AuditEvent.APPROVAL_UPLOADED).exists())

    def test_the_sections_stay_held(self):
        self.upload_approval()
        self.assertTrue(all(self.held()))

    def test_another_office_may_not_upload_it(self):
        response = self.upload_approval(user=self.bud_head)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'not_in_office')

    def test_it_cannot_arrive_before_the_imr_accepts(self):
        Proposal.objects.filter(pk=self.proposal.pk).update(status=Proposal.READY_FOR_IMR)
        response = self.upload_approval()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_accepting_scans')

    def test_nor_after_a_denial(self):
        Proposal.objects.filter(pk=self.proposal.pk).update(status=Proposal.DENIED)
        response = self.upload_approval()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_accepting_scans')

    def test_it_is_checked_like_any_scan(self):
        response = self.upload_approval(file=a_file('x.pdf', b'not a pdf'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'unsupported_type')
        self.assertEqual(self.status(), Proposal.AWAITING_APPROVAL)

    def test_once_with_the_custodian_nothing_is_replaced_without_a_return(self):
        """The custodian has the package; a defect goes back through them."""
        self.upload_approval()
        response = self.replace(self.current(Attachment.APPROVED_DCR).id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_accepting_scans')

    def test_the_package_shows_where_it_may_be_uploaded(self):
        rows = self.as_(self.acc_enc).get(self.url + 'package/').data['scans']
        self.assertTrue(rows[Attachment.APPROVED_DCR]['can_upload'])
        self.assertFalse(rows[Attachment.SIGNED_DCR]['can_replace'])
        other = self.as_(self.bud_head).get(self.url + 'package/').data['scans']
        self.assertFalse(other[Attachment.APPROVED_DCR]['can_upload'])


# --- the custodian's return ----------------------------------

class ReturnTests(ApprovalFixture):

    def setUp(self):
        super().setUp()
        self.upload_approval()
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)

    def test_the_custodian_returns_it_naming_the_defects(self):
        response = self.returns([Attachment.APPROVED_DCR])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), Proposal.PACKAGE_RETURNED)
        decision = QmsDecision.objects.get(proposal=self.proposal, stage='custodian')
        self.assertEqual(decision.outcome, 'return')
        self.assertEqual(decision.returned_kinds, [Attachment.APPROVED_DCR])
        self.assertEqual(decision.decided_as,
                         'Quality Management Office — Document Custodian')
        self.assertTrue(self.proposal.events.filter(event=AuditEvent.PACKAGE_RETURNED).exists())
        self.assertTrue(all(self.held()), 'content is untouched and still held')

    def test_every_office_involved_sees_why(self):
        self.returns([Attachment.SIGNED_DCR], 'Page 2 is unreadable.')
        for user in (self.acc_enc, self.bud_head):
            decisions = self.as_(user).get(self.url + 'full/').data['qms_decisions']
            self.assertEqual(decisions[-1]['outcome'], 'return')
            self.assertEqual(decisions[-1]['comments'], 'Page 2 is unreadable.')

    def test_a_return_needs_a_reason(self):
        response = self.returns([Attachment.SIGNED_DCR], '  ')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'comments_required')
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)

    def test_a_return_names_at_least_one_signed_copy(self):
        response = self.returns([])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'no_defect_named')

    def test_only_signed_copies_can_be_returned(self):
        """The generated documents came from locked content; they are not
        a package defect the office could fix."""
        response = self.returns([Attachment.DCR_GENERATED])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'unknown_kind')

    def test_only_the_custodian_returns(self):
        for user in (self.imr, self.acc_head):
            response = self.returns([Attachment.SIGNED_DCR], user=user)
            self.assertEqual(response.status_code, 403, user.username)
            self.assertEqual(response.data['reason'], 'not_custodian')

    def test_never_on_their_own_offices_request(self):
        position, _ = Position.objects.get_or_create(office=self.accounting, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=self.custodian, position=position, starts_on=self.today)
        response = self.returns([Attachment.SIGNED_DCR])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'conflict_of_interest')

    def test_only_a_package_with_the_custodian(self):
        self.returns([Attachment.SIGNED_DCR])
        response = self.returns([Attachment.SIGNED_DCR])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_with_custodian')

    def test_the_custodian_sees_whether_they_can_return(self):
        self.assertTrue(self.as_(self.custodian).get(self.url + 'full/').data['can_custodian_return'])
        self.assertFalse(self.as_(self.imr).get(self.url + 'full/').data['can_custodian_return'])

    def test_the_queue_holds_only_what_waits_on_the_custodian(self):
        self.assertEqual([r['id'] for r in
                          self.as_(self.custodian).get('/api/qms/queue/').data['custodian']],
                         [self.proposal.id])
        self.returns([Attachment.SIGNED_DCR])
        self.assertEqual(self.as_(self.custodian).get('/api/qms/queue/').data['custodian'], [])


class FixingAReturnTests(ApprovalFixture):

    def setUp(self):
        super().setUp()
        self.upload_approval()
        response = self.returns([Attachment.SIGNED_DCR, Attachment.APPROVED_DCR])
        assert response.status_code == 200, response.data

    def test_only_the_named_copies_can_be_replaced(self):
        response = self.replace(self.current(Attachment.SIGNED_PAGES).id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_returned')

    def test_replacing_a_named_copy_needs_a_reason_and_the_password(self):
        scan = self.current(Attachment.SIGNED_DCR)
        response = self.replace(scan.id, token=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'reauth_required')
        response = self.replace(scan.id, reason=' ')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'reason_required')

    def test_partly_fixed_it_stays_returned(self):
        response = self.replace(self.current(Attachment.SIGNED_DCR).id)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), Proposal.PACKAGE_RETURNED)

    def test_every_named_copy_replaced_and_it_is_back_with_the_custodian(self):
        self.replace(self.current(Attachment.SIGNED_DCR).id)
        response = self.replace(self.current(Attachment.APPROVED_DCR).id,
                                file=a_file('approved-again.pdf', pdf_bytes('Signed again.')))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), Proposal.WITH_CUSTODIAN)
        self.assertTrue(self.proposal.events.filter(
            event=AuditEvent.PACKAGE_COMPLETE, detail__icontains='custodian').exists())

    def test_the_package_marks_what_to_replace(self):
        rows = self.as_(self.acc_enc).get(self.url + 'package/').data['scans']
        self.assertTrue(rows[Attachment.SIGNED_DCR]['can_replace'])
        self.assertTrue(rows[Attachment.APPROVED_DCR]['can_replace'])
        self.assertFalse(rows[Attachment.SIGNED_PAGES]['can_replace'])
        self.assertTrue(rows[Attachment.SIGNED_DCR]['returned'])

    def test_nothing_in_this_stage_touches_the_text(self):
        before = list(SectionChange.objects.filter(
            version__proposal=self.proposal).values_list('new_text', flat=True))
        self.s1.refresh_from_db()
        text = self.s1.content
        self.replace(self.current(Attachment.SIGNED_DCR).id)
        self.replace(self.current(Attachment.APPROVED_DCR).id)
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.content, text)
        self.assertEqual(before, list(SectionChange.objects.filter(
            version__proposal=self.proposal).values_list('new_text', flat=True)))
