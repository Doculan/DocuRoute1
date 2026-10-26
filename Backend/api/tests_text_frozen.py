"""After submission the text does not change - except through a return.

The rules with teeth (fixed after `v4.2.0-p3`, which allowed edits out for
concurrence: an edit made no new version and left earlier concurrences
standing on text that no longer existed):

- **Edits only in Draft.** Out for concurrence, with the Head or later,
  a section's text, a new section, the overall reason and the AI check
  are all refused (`not_open`, `with_head`), and nothing is written.
- **Each concurrence records what it agreed to**: the version's content
  hash (the overall reason and every proposed text).
- **The lock compares.** If any concurrence's hash no longer matches the
  text, the lock is refused (`content_changed`) and the deciding office's
  concurrence is not kept. Concurrences recorded before the hash existed
  are not compared, and the lock's record says so.
- **The signatory offices hear of the lock**: the Heads of the approving
  offices on the route, for information; the system admin where an
  approving office has no Head, as in the deadline ladder.

Tests that expect an error assert the reason.
"""

from api.models import (
    AuditEvent, Concurrence, CustomUser, Notification, Position, Proposal, SectionChange,
)

from .tests_concurrence import REASON, ConcurrenceFixture

NEW_TEXT = "The Cashier shall release the cheque within one day."


class EditsOnlyInDraft(ConcurrenceFixture):

    def submitted(self):
        proposal_id = self.a_draft()
        self.assertEqual(self.submit(proposal_id).status_code, 200)
        return proposal_id

    def attempts(self, proposal_id):
        """Every way the requesting office could change the text."""
        return {
            'edit a changed section': self.client.put(
                f'/api/proposals/{proposal_id}/sections/{self.s1.id}/',
                {'new_text': 'The Cashier shall release the cheque at once.'}, format='json'),
            'add a section': self.client.put(
                f'/api/proposals/{proposal_id}/sections/{self.s2.id}/',
                {'new_text': 'The Accounting Staff verifies it twice.'}, format='json'),
            'change the reason': self.client.patch(
                f'/api/proposals/{proposal_id}/',
                {'overall_reason': 'A different reason for the change, given later.'},
                format='json'),
            'run a check': self.client.post(
                f'/api/proposals/{proposal_id}/sections/{self.s1.id}/check/', {}, format='json'),
        }

    def test_out_for_concurrence_nothing_changes(self):
        proposal_id = self.submitted()
        version = Proposal.objects.get(pk=proposal_id).current_version()
        before = version.content_hash()
        for what, response in self.attempts(proposal_id).items():
            self.assertEqual((response.status_code, response.data.get('reason')),
                             (409, 'not_open'), what)
        version.refresh_from_db()
        self.assertEqual(version.content_hash(), before)
        self.assertEqual(SectionChange.objects.get(version=version).new_text, NEW_TEXT)

    def test_after_it_is_locked_nothing_changes_either(self):
        proposal_id = self.submitted()
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)
        self.decide(proposal_id, self.cmo_head, Concurrence.CONCUR)
        for what, response in self.attempts(proposal_id).items():
            self.assertEqual((response.status_code, response.data.get('reason')),
                             (409, 'not_open'), what)

    def test_with_the_head_it_waits_for_the_head(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        for what, response in self.attempts(proposal_id).items():
            self.assertEqual(response.data.get('reason'), 'with_head', what)

    def test_a_return_makes_a_new_draft_that_can_be_edited(self):
        proposal_id = self.submitted()
        self.decide(proposal_id, self.bud_head, Concurrence.RETURN, feedback='Say which day.')
        response = self.client.put(f'/api/proposals/{proposal_id}/sections/{self.s1.id}/',
                                   {'new_text': 'The Cashier shall release it by Friday.'},
                                   format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Proposal.objects.get(pk=proposal_id).current_version().number, 2)


class ConcurrenceAgainstTheText(ConcurrenceFixture):

    def setUp(self):
        super().setUp()
        self.proposal_id = self.a_draft()
        self.submit(self.proposal_id)
        self.version = Proposal.objects.get(pk=self.proposal_id).current_version()

    def test_each_concurrence_records_the_versions_hash(self):
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        recorded = Concurrence.objects.get(version=self.version, office=self.budget)
        self.assertEqual(recorded.content_hash, self.version.content_hash())
        self.assertEqual(len(recorded.content_hash), 64)

    def test_the_hash_covers_the_text_and_the_reason(self):
        first = self.version.content_hash()
        SectionChange.objects.filter(version=self.version).update(new_text='Other text.')
        second = self.version.content_hash()
        self.version.overall_reason = REASON + ' And more.'
        self.version.save(update_fields=['overall_reason'])
        self.assertEqual(len({first, second, self.version.content_hash()}), 3)

    def assert_lock_refused(self, response):
        self.assertEqual((response.status_code, response.data.get('reason')),
                         (409, 'content_changed'))
        self.assertIn('Budget Office', response.data['error'])
        proposal = Proposal.objects.get(pk=self.proposal_id)
        self.assertEqual((proposal.status, proposal.dcr_number), (Proposal.CONCURRENCE, ''))
        self.assertFalse(Concurrence.objects.filter(version=self.version, office=self.cash).exists())
        self.assertFalse(AuditEvent.objects.filter(proposal=proposal, event=AuditEvent.LOCKED).exists())

    def test_the_lock_is_refused_if_the_text_changed_after_a_concurrence(self):
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        # However it happened - the defect, a script, the database - the
        # text is no longer what Budget agreed to.
        SectionChange.objects.filter(version=self.version).update(new_text='Changed afterwards.')
        self.assert_lock_refused(self.decide(self.proposal_id, self.cmo_head, Concurrence.CONCUR))

    def test_and_if_the_reason_changed(self):
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        self.version.overall_reason = REASON + ' Amended after Budget concurred.'
        self.version.save(update_fields=['overall_reason'])
        self.assert_lock_refused(self.decide(self.proposal_id, self.cmo_head, Concurrence.CONCUR))

    def test_unchanged_text_locks(self):
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        response = self.decide(self.proposal_id, self.cmo_head, Concurrence.CONCUR)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Proposal.objects.get(pk=self.proposal_id).status,
                         Proposal.AWAITING_SIGNATURE)

    def test_a_concurrence_from_before_the_hash_is_not_compared_and_is_said(self):
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)
        Concurrence.objects.filter(version=self.version, office=self.budget).update(content_hash=None)
        response = self.decide(self.proposal_id, self.cmo_head, Concurrence.CONCUR)
        self.assertEqual(response.status_code, 200, response.data)
        locked = AuditEvent.objects.get(proposal_id=self.proposal_id, event=AuditEvent.LOCKED)
        self.assertIn('1 concurrence(s) recorded before content hashing, not compared', locked.detail)


class TheSignatoriesHearOfTheLock(ConcurrenceFixture):
    """The route here is the VPAF (owner), then the President."""

    def lock(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)
        self.decide(proposal_id, self.cmo_head, Concurrence.CONCUR)
        self.assertEqual(Proposal.objects.get(pk=proposal_id).status, Proposal.AWAITING_SIGNATURE)

    def ahead(self, user):
        return Notification.objects.filter(kind=Notification.SIGNING_AHEAD, recipient=user)

    def test_the_heads_of_the_approving_offices_for_information(self):
        vpaf_head = self.person('vpaf_head', self.vpaf, Position.HEAD)
        president_head = self.person('president_head', self.president, Position.HEAD)
        self.lock()
        for head in (vpaf_head, president_head):
            self.assertEqual(self.ahead(head).count(), 1, head.username)
            notice = self.ahead(head).get()
            self.assertEqual(notice.severity, 'info')
            self.assertTrue(notice.title.endswith('documents coming to you to sign'), notice.title)
        # The requesting office has its own notice, and not this one.
        self.assertTrue(Notification.objects.filter(kind=Notification.LOCKED,
                                                    recipient=self.acc_head).exists())
        self.assertFalse(Notification.objects.filter(kind=Notification.SIGNING_AHEAD,
                                                     recipient__in=[self.acc_head, self.acc_enc])
                         .exists())

    def test_an_owner_that_proposed_gets_its_own_notice_only(self):
        """The VP's own staff draft changes to the manual the VP signs."""
        from api.models import ManualSeriesOffice, OfficeLink
        ManualSeriesOffice.objects.create(series=self.series, office=self.vpaf,
                                          relationship=OfficeLink.CONCURRING)
        vpaf_head = self.person('vpaf_head', self.vpaf, Position.HEAD)
        president_head = self.person('president_head', self.president, Position.HEAD)
        client = self.as_(vpaf_head)
        proposal_id = client.post('/api/proposals/', {'manual_id': self.manual.id}, format='json',
                                  HTTP_X_REAUTH_TOKEN=self.token(vpaf_head)).data['id']
        client.patch(f'/api/proposals/{proposal_id}/', {'overall_reason': REASON}, format='json')
        client.put(f'/api/proposals/{proposal_id}/sections/{self.s1.id}/',
                   {'new_text': NEW_TEXT}, format='json')
        client.post(f'/api/proposals/{proposal_id}/sections/{self.s1.id}/check/', {}, format='json')
        self.assertEqual(self.submit(proposal_id, vpaf_head).status_code, 200)
        for head in (self.acc_head, self.bud_head, self.cmo_head):
            self.decide(proposal_id, head, Concurrence.CONCUR)
        self.assertEqual(Proposal.objects.get(pk=proposal_id).status, Proposal.AWAITING_SIGNATURE)
        self.assertTrue(Notification.objects.filter(kind=Notification.LOCKED,
                                                    recipient=vpaf_head).exists())
        self.assertFalse(self.ahead(vpaf_head).exists())
        self.assertEqual(self.ahead(president_head).count(), 1)

    def test_an_approving_office_with_no_head_tells_the_system_admin(self):
        vpaf_head = self.person('vpaf_head', self.vpaf, Position.HEAD)
        admin = CustomUser.objects.create_user(
            username='lock_admin', password='pw', role='admin', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN)
        self.lock()                                     # the President's office has no Head
        self.assertEqual(self.ahead(vpaf_head).count(), 1)
        self.assertEqual(self.ahead(admin).count(), 1)
        notice = self.ahead(admin).get()
        self.assertEqual(notice.severity, 'info')
