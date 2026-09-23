"""Phase 4a: the IMR's decision, the hold on sections, the QMS portal.

What has teeth here:

**Only a current IMR decides, never on their own office's request, and
with the password again.** Deny needs a reason, closes the request, and
the reason is visible to every office involved.

**A request holds its sections until it is closed** - not only while it
is drafted. After the lock, no other office may start changing the same
text, and no one may edit it directly.

**The server says which portal someone belongs in.**

**QMS staff read every document** once access is by position; they do
not thereby gain the right to propose.

Every test that expects an error asserts the reason, not only the status.
"""

from api.models import (
    Attachment, AuditEvent, CustomUser, Office, Position, PositionAssignment,
    Proposal, QmsDecision, SectionChange,
)
from api.tests_package import PackageTestCase, a_file, image_bytes


class QmsFixture(PackageTestCase):
    """A request ready for the IMR, and a QMS office to decide it."""

    def setUp(self):
        super().setUp()
        self.qms = Office.objects.create(name='Quality Management Office', abbreviation='QMO')
        self.imr = self.qms_person('the_imr', Position.IMR)
        self.custodian = self.qms_person('the_custodian', Position.DOCUMENT_CUSTODIAN)
        self.upload(Attachment.SIGNED_DCR)
        self.upload(Attachment.SIGNED_PAGES, a_file('p.png', image_bytes('PNG'), 'image/png'))
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, Proposal.READY_FOR_IMR)

    def qms_person(self, username, kind):
        user = self.person(username, self.qms, kind)
        user.system_role = CustomUser.QMS_STAFF
        user.save(update_fields=['system_role'])
        return user

    def imr_decides(self, decision, comments='', user=None, token=True):
        # Not `decide`: that is the concurrence fixture's, which locking uses.
        user = user or self.imr
        extra = {'HTTP_X_REAUTH_TOKEN': self.token(user)} if token else {}
        return self.as_(user).post(
            self.url + 'imr/', {'decision': decision, 'comments': comments},
            format='json', **extra,
        )

    def held(self):
        return list(SectionChange.objects.filter(
            version__proposal=self.proposal).values_list('is_open', flat=True))

    def status(self):
        return Proposal.objects.get(pk=self.proposal.pk).status


# --- the IMR's decision --------------------------------------

class ImrDecisionTests(QmsFixture):

    def test_accepting_moves_it_to_the_approving_authority(self):
        response = self.imr_decides('accept', 'In order.')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), Proposal.AWAITING_APPROVAL)

        decision = QmsDecision.objects.get(proposal=self.proposal)
        self.assertEqual((decision.stage, decision.outcome), ('imr', 'accept'))
        self.assertEqual(decision.decided_as,
                         'Quality Management Office — Integrated Management Representative')
        self.assertTrue(self.proposal.events.filter(event=AuditEvent.IMR_ACCEPTED).exists())

    def test_an_accepted_request_still_holds_its_sections(self):
        self.imr_decides('accept')
        self.assertTrue(all(self.held()))

    def test_denying_closes_it_releases_its_sections_and_says_why(self):
        response = self.imr_decides('deny', 'The release window conflicts with FAM 6.03.')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(), Proposal.DENIED)
        self.assertFalse(any(self.held()))
        self.assertTrue(self.proposal.events.filter(event=AuditEvent.IMR_DENIED).exists())

        # Every office involved sees the reason.
        for user in (self.acc_enc, self.bud_head, self.cmo_head):
            decisions = self.as_(user).get(self.url + 'full/').data['qms_decisions']
            self.assertEqual(decisions[0]['outcome'], 'deny')
            self.assertEqual(decisions[0]['comments'],
                             'The release window conflicts with FAM 6.03.')

    def test_a_denial_needs_a_reason(self):
        response = self.imr_decides('deny', '   ')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'comments_required')
        self.assertEqual(self.status(), Proposal.READY_FOR_IMR)

    def test_deciding_needs_the_password(self):
        response = self.imr_decides('accept', token=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'reauth_required')
        self.assertEqual(self.status(), Proposal.READY_FOR_IMR)

    def test_only_the_imr_decides(self):
        for user in (self.custodian, self.acc_head, self.bud_head):
            response = self.imr_decides('accept', user=user)
            self.assertEqual(response.status_code, 403, user.username)
            self.assertEqual(response.data['reason'], 'not_imr')
        self.assertEqual(self.status(), Proposal.READY_FOR_IMR)

    def test_an_imr_never_decides_their_own_offices_request(self):
        position, _ = Position.objects.get_or_create(office=self.accounting, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=self.imr, position=position, starts_on=self.today)
        response = self.imr_decides('accept')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'conflict_of_interest')
        self.assertIn('Accounting Office', response.data['error'])
        self.assertFalse(self.as_(self.imr).get(self.url + 'full/').data['can_imr_decide'])

    def test_only_a_request_ready_for_the_imr(self):
        Proposal.objects.filter(pk=self.proposal.pk).update(status=Proposal.AWAITING_SIGNATURE)
        response = self.imr_decides('accept')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_ready_for_imr')

    def test_an_unknown_decision_is_refused(self):
        response = self.imr_decides('approve')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'unknown_decision')

    def test_after_the_decision_the_signed_copies_are_closed(self):
        """Option A: the IMR has judged these scans."""
        self.imr_decides('accept')
        scan = Attachment.objects.get(proposal=self.proposal, kind=Attachment.SIGNED_DCR,
                                      superseded_at__isnull=True)
        response = self.replace(scan.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_accepting_scans')

    def test_the_imr_sees_whether_they_can_decide(self):
        self.assertTrue(self.as_(self.imr).get(self.url + 'full/').data['can_imr_decide'])
        self.assertFalse(self.as_(self.acc_head).get(self.url + 'full/').data['can_imr_decide'])


# --- the queue and the portal --------------------------------

class QueueAndPortalTests(QmsFixture):

    def test_the_imr_sees_what_is_waiting(self):
        data = self.as_(self.imr).get('/api/qms/queue/').data
        self.assertEqual([r['id'] for r in data['imr']], [self.proposal.id])
        self.assertEqual(data['imr'][0]['dcr_number'], self.proposal.dcr_number)
        self.assertEqual(data['custodian'], [])

    def test_someone_without_the_position_sees_an_empty_queue(self):
        data = self.as_(self.custodian).get('/api/qms/queue/').data
        self.assertEqual(data['imr'], [])

    def test_the_queue_empties_once_decided(self):
        self.imr_decides('accept')
        self.assertEqual(self.as_(self.imr).get('/api/qms/queue/').data['imr'], [])

    def test_the_server_says_which_portal(self):
        admin = CustomUser.objects.create_user(
            username='sysadmin', password='x', is_approved=True, role='admin',
            system_role=CustomUser.SYSTEM_ADMIN)
        for user, portal in ((self.imr, 'qms'), (self.acc_enc, 'staff'), (admin, 'admin')):
            self.assertEqual(self.as_(user).get('/api/auth/me/').data['portal'], portal)
        me = self.as_(self.imr).get('/api/auth/me/').data
        self.assertTrue(me['is_imr'])
        self.assertFalse(me['is_custodian'])

    def test_the_portal_ignores_what_the_browser_claims(self):
        """The old routing read `role` from browser storage; `me` does not."""
        response = self.as_(self.acc_enc).get('/api/auth/me/', HTTP_X_ROLE='admin')
        self.assertEqual(response.data['portal'], 'staff')


# --- the hold on sections ------------------------------------

class HoldTests(QmsFixture):

    def admin(self):
        return CustomUser.objects.create_user(
            username='sysadmin', password='x', is_approved=True, role='admin',
            system_role=CustomUser.SYSTEM_ADMIN)

    def test_after_the_lock_no_other_office_may_take_the_section(self):
        """Found in the Phase 4 survey: the hold used to end at the lock."""
        client = self.as_(self.bud_enc)
        other = client.post('/api/proposals/', {'manual_id': self.manual.id},
                            format='json').data['id']
        response = client.put(f'/api/proposals/{other}/sections/{self.s1.id}/',
                              {'new_text': 'A different wording.'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_in_another_proposal')

    def test_a_held_section_cannot_be_edited_directly(self):
        response = self.as_(self.admin()).patch(
            f'/api/sections/{self.s1.id}/update/', {'content': 'Edited under the request.'},
            format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_held')
        self.assertIn(self.proposal.dcr_number, response.data['error'])
        self.s1.refresh_from_db()
        self.assertNotEqual(self.s1.content, 'Edited under the request.')

    def test_only_the_text_is_held(self):
        """Tag, order and page number are not what the offices agreed on."""
        response = self.as_(self.admin()).patch(
            f'/api/sections/{self.s1.id}/update/', {'tag': 'PROCEDURE'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_a_held_section_cannot_be_deleted_nor_its_manual(self):
        admin = self.admin()
        token = {'HTTP_X_REAUTH_TOKEN': self.token(admin)}
        response = self.as_(admin).delete(f'/api/sections/{self.s1.id}/delete/', **token)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_held')
        response = self.as_(admin).delete(f'/api/manuals/{self.manual.id}/delete/', **token)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_held')
        self.assertTrue(type(self.s1).objects.filter(pk=self.s1.pk).exists())

    def test_a_denial_frees_the_text(self):
        self.imr_decides('deny', 'Not this year.')
        response = self.as_(self.admin()).patch(
            f'/api/sections/{self.s1.id}/update/', {'content': 'Now it may change.'},
            format='json')
        self.assertEqual(response.status_code, 200, response.data)


# --- QMS staff read everything -------------------------------

class QmsReadingTests(QmsFixture):

    def test_qms_staff_read_a_document_their_office_is_not_linked_to(self):
        response = self.as_(self.custodian).get(f'/api/manuals/{self.manual.id}/sections/')
        self.assertEqual(response.status_code, 200, response.data)
        titles = [m['title'] for m in self.as_(self.custodian).get('/api/staff/manuals/').data]
        self.assertIn(self.manual.title, titles)

    def test_reading_is_not_proposing(self):
        response = self.as_(self.custodian).post(
            '/api/proposals/', {'manual_id': self.manual.id}, format='json')
        self.assertEqual(response.status_code, 403, response.data)
        self.assertIn(response.data['reason'], ('not_concurring', 'no_office'))


class MoreHeldPathsTests(QmsFixture):
    """Every other way section text is written directly also waits."""

    def admin(self):
        return CustomUser.objects.create_user(
            username='sysadmin', password='x', is_approved=True, role='admin',
            system_role=CustomUser.SYSTEM_ADMIN)

    def test_the_staff_edit_path_waits_too(self):
        response = self.as_(self.acc_enc).patch(
            f'/api/sections/{self.s1.id}/review/', {'content': 'Staff edit.'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_held')

    def test_a_v3_approval_cannot_write_a_held_section(self):
        from api.models import ManualRevision
        revision = ManualRevision.objects.create(
            section=self.s1, submitted_by=self.acc_enc, proposed_content='Old-flow text.',
            status='pending', change_reason='Left over from v3.')
        response = self.as_(self.imr).patch(
            f'/api/admin/revisions/{revision.id}/review/', {'status': 'approved'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_held')
        revision.refresh_from_db()
        self.assertEqual(revision.status, 'pending')

    def test_merging_a_held_section_waits(self):
        response = self.as_(self.admin()).post(
            f'/api/sections/{self.s2.id}/merge/', {'target_id': self.s1.id}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'section_held')


class ListsWithoutADepartmentTests(QmsFixture):
    """Under position-based access, a v3 department is not required.

    The manual list, the section search and "my revisions" used to refuse
    anyone without one, while saying "not yet assigned to an office" -
    turning away people who hold positions, which every v4 account is.
    """

    def test_a_position_holder_without_a_department_sees_their_documents(self):
        self.assertIsNone(self.acc_enc.department)
        response = self.as_(self.acc_enc).get('/api/staff/manuals/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(self.manual.title, [m['title'] for m in response.data])

    def test_someone_with_no_office_is_still_told_so(self):
        nobody = CustomUser.objects.create_user(username='nobody', password='x', is_approved=True)
        response = self.as_(nobody).get('/api/staff/manuals/')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'no_position')
