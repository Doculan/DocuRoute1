"""The Encoder-to-Head step (Phase 2B).

    Drafting (Encoder) --Send to Head--> With Head --Submit--> In concurrence
            ^                               |
            '-- Return to Encoder / Recall --'

The rules with teeth:

- **The Head sees what the Encoder read.** Sending needs the same bar as
  submitting, and the text is frozen while it is with the Head.
- **The Head submits only what was sent**, unless the Head drafted it or
  the office has no Encoder.
- **Every step notifies and is recorded**; a missing Head or Encoder falls
  back as the decisions require.

Tests that expect an error assert the reason.
"""

from datetime import timedelta

from django.utils import timezone

from api import monitoring
from api.models import (
    AuditEvent, CustomUser, Notification, Position, PositionAssignment,
    Proposal,
)

from .tests_concurrence import REASON, ConcurrenceFixture


class HeadStepFixture(ConcurrenceFixture):

    def post(self, user, proposal_id, action, body=None, token=False):
        extra = {'HTTP_X_REAUTH_TOKEN': self.token(user)} if token else {}
        return self.as_(user).post(f'/api/proposals/{proposal_id}/{action}/',
                                   body or {}, format='json', **extra)

    def status(self, proposal_id):
        return Proposal.objects.get(pk=proposal_id).status

    def events(self, proposal_id):
        return list(AuditEvent.objects.filter(proposal_id=proposal_id)
                    .order_by('at', 'pk').values_list('event', flat=True))

    def notices(self, user, kind):
        return Notification.objects.filter(recipient=user, kind=kind)

    def end_post(self, user):
        assignment = user.position_assignments.get()
        assignment.starts_on = self.today - timedelta(days=30)
        assignment.ends_on = self.today - timedelta(days=1)
        assignment.save()


class SendingToTheHead(HeadStepFixture):

    def test_the_encoder_sends_a_ready_draft_without_a_password(self):
        proposal_id = self.a_draft()

        response = self.send_to_head(proposal_id)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(proposal_id), Proposal.WITH_HEAD)
        self.assertEqual(self.events(proposal_id)[-1], AuditEvent.SENT_TO_HEAD)
        notice = self.notices(self.acc_head, Notification.SENT_TO_HEAD).get()
        self.assertEqual(notice.severity, 'action')
        self.assertEqual(notice.title, 'FAM 6.02 is with you to submit')

    def test_a_draft_that_is_not_ready_is_not_sent(self):
        proposal_id = self.client.post(
            '/api/proposals/', {'manual_id': self.manual.id}, format='json',
            HTTP_X_REAUTH_TOKEN=self.token(self.acc_enc)).data['id']

        response = self.send_to_head(proposal_id)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_ready')
        self.assertEqual(self.status(proposal_id), Proposal.DRAFT)

    def test_an_edit_after_the_check_stops_the_send(self):
        proposal_id = self.a_draft()
        self.client.put(f'/api/proposals/{proposal_id}/sections/{self.s1.id}/',
                        {'new_text': 'The Cashier shall release it within two days.'},
                        format='json')

        response = self.send_to_head(proposal_id)

        self.assertEqual(response.data['reason'], 'not_ready')
        self.assertIn('need a check', response.data['error'])

    def test_the_head_does_not_send_to_themselves(self):
        proposal_id = self.a_draft()
        response = self.send_to_head(proposal_id, self.acc_head)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'head_submits_directly')

    def test_another_office_cannot_send_it(self):
        proposal_id = self.a_draft()
        response = self.send_to_head(proposal_id, self.bud_enc)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'not_encoder')

    def test_with_the_head_the_text_is_frozen(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)

        edit = self.client.put(f'/api/proposals/{proposal_id}/sections/{self.s1.id}/',
                               {'new_text': 'Changed while with the Head.'}, format='json')
        reason = self.client.patch(f'/api/proposals/{proposal_id}/',
                                   {'overall_reason': 'Changed.'}, format='json')

        for response in (edit, reason):
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data['reason'], 'with_head')

    def test_it_still_holds_the_offices_slot(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        response = self.client.post('/api/proposals/', {'manual_id': self.manual.id},
                                    format='json', HTTP_X_REAUTH_TOKEN=self.token(self.acc_enc))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'already_open')
        self.assertEqual(response.data['proposal_id'], proposal_id)


class TheHeadSubmits(HeadStepFixture):

    def test_the_head_submits_what_was_sent_and_the_notice_clears(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)

        response = self.post(self.acc_head, proposal_id, 'submit', token=True)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(proposal_id), Proposal.CONCURRENCE)
        notice = self.notices(self.acc_head, Notification.SENT_TO_HEAD).get()
        self.assertEqual(notice.acted_by, self.acc_head)

    def test_an_encoders_draft_must_be_sent_first(self):
        proposal_id = self.a_draft()
        response = self.post(self.acc_head, proposal_id, 'submit', token=True)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'send_to_head_first')
        self.assertEqual(self.status(proposal_id), Proposal.DRAFT)

    def test_a_head_submits_their_own_draft_directly(self):
        proposal_id = self.as_(self.acc_head).post(
            '/api/proposals/', {'manual_id': self.manual.id}, format='json',
            HTTP_X_REAUTH_TOKEN=self.token(self.acc_head)).data['id']
        head = self.as_(self.acc_head)
        head.patch(f'/api/proposals/{proposal_id}/', {'overall_reason': REASON}, format='json')
        head.put(f'/api/proposals/{proposal_id}/sections/{self.s1.id}/',
                 {'new_text': 'The Cashier shall release the cheque within one day.'},
                 format='json')
        head.post(f'/api/proposals/{proposal_id}/sections/{self.s1.id}/check/', {}, format='json')

        response = self.post(self.acc_head, proposal_id, 'submit', token=True)

        self.assertEqual(response.status_code, 200, response.data)

    def test_with_no_encoder_the_head_submits_directly(self):
        proposal_id = self.a_draft()
        self.end_post(self.acc_enc)
        response = self.post(self.acc_head, proposal_id, 'submit', token=True)
        self.assertEqual(response.status_code, 200, response.data)

    def test_the_screen_offers_each_person_only_what_they_can_do(self):
        proposal_id = self.a_draft()
        def flags(user):
            data = self.as_(user).get(f'/api/proposals/{proposal_id}/full/').data
            return {k for k in ('can_submit', 'can_send_to_head', 'can_recall',
                                'can_return_to_encoder', 'can_withdraw') if data[k]}
        self.assertEqual(flags(self.acc_enc), {'can_send_to_head'})
        self.assertEqual(flags(self.acc_head), {'can_withdraw'})
        self.send_to_head(proposal_id)
        self.assertEqual(flags(self.acc_enc), {'can_recall'})
        self.assertEqual(flags(self.acc_head),
                         {'can_submit', 'can_return_to_encoder', 'can_withdraw'})


class RecallAndReturn(HeadStepFixture):

    def test_the_encoder_recalls_it_and_the_head_is_told(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)

        response = self.post(self.acc_enc, proposal_id, 'recall')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(proposal_id), Proposal.DRAFT)
        self.assertEqual(self.notices(self.acc_head, Notification.RECALLED).get().severity, 'info')
        self.assertEqual(self.notices(self.acc_head, Notification.SENT_TO_HEAD).get().acted_by,
                         self.acc_enc)

    def test_recall_is_the_encoders_and_only_while_with_the_head(self):
        proposal_id = self.a_draft()
        early = self.post(self.acc_enc, proposal_id, 'recall')
        self.assertEqual((early.status_code, early.data['reason']), (409, 'not_with_head'))
        self.send_to_head(proposal_id)
        by_head = self.post(self.acc_head, proposal_id, 'recall')
        self.assertEqual((by_head.status_code, by_head.data['reason']), (403, 'not_encoder'))

    def test_the_head_returns_it_with_a_note_and_the_encoder_must_act(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)

        response = self.post(self.acc_head, proposal_id, 'return-to-encoder',
                             {'note': 'Keep the five-day window for large cheques.'})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.status(proposal_id), Proposal.DRAFT)
        event = AuditEvent.objects.filter(proposal_id=proposal_id).latest('at')
        self.assertEqual(event.event, AuditEvent.RETURNED_TO_ENCODER)
        self.assertEqual(event.detail, 'Keep the five-day window for large cheques.')
        notice = self.notices(self.acc_enc, Notification.RETURNED_TO_ENCODER).get()
        self.assertEqual(notice.severity, 'action')
        self.assertEqual(notice.body, '“Keep the five-day window for large cheques.”')

    def test_returning_needs_a_note_and_the_head(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        bare = self.post(self.acc_head, proposal_id, 'return-to-encoder', {'note': ' '})
        self.assertEqual((bare.status_code, bare.data['reason']), (400, 'note_required'))
        by_encoder = self.post(self.acc_enc, proposal_id, 'return-to-encoder', {'note': 'x'})
        self.assertEqual((by_encoder.status_code, by_encoder.data['reason']), (403, 'not_head'))

    def test_sending_again_clears_the_return(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        self.post(self.acc_head, proposal_id, 'return-to-encoder', {'note': 'Shorter, please.'})

        self.assertEqual(self.send_to_head(proposal_id).status_code, 200)

        self.assertEqual(self.notices(self.acc_enc, Notification.RETURNED_TO_ENCODER)
                         .get().acted_by, self.acc_enc)

    def test_the_head_may_still_withdraw_it_and_the_notice_clears(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        response = self.post(self.acc_head, proposal_id, 'withdraw',
                             {'reason': 'Superseded.'}, token=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNotNone(self.notices(self.acc_head, Notification.SENT_TO_HEAD)
                             .get().acted_at)


class WhenAPostIsEmpty(HeadStepFixture):

    def test_no_head_sends_it_to_the_office_above_and_the_admin(self):
        vp_head = self.person('vp_head', self.vpaf, Position.HEAD)
        admin = CustomUser.objects.create_user(
            username='admin', password='x', role='admin', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN)
        proposal_id = self.a_draft()
        self.end_post(self.acc_head)

        self.send_to_head(proposal_id)

        for user in (vp_head, admin):
            notice = self.notices(user, Notification.SENT_TO_HEAD).get()
            self.assertEqual(notice.title, 'FAM 6.02 is waiting for a Head')
            self.assertEqual(notice.severity, 'action')

    def test_no_encoder_tells_the_head_who_returned_it(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        self.end_post(self.acc_enc)

        self.post(self.acc_head, proposal_id, 'return-to-encoder', {'note': 'Redo the dates.'})

        notice = self.notices(self.acc_head, Notification.RETURNED_TO_ENCODER).get()
        self.assertEqual(notice.title, 'FAM 6.02 is back in draft')


class WhatTheOfficeSees(HeadStepFixture):

    def sections(self, user):
        return {s['key']: s for s in
                self.as_(user).get('/api/needs-action/').data['sections']}

    def banner(self, user):
        return self.as_(user).get('/api/action-banner/').data

    def test_needs_your_action_says_whose_turn_it_is(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        self.assertEqual(self.sections(self.acc_head)['with_head']['items'][0]['label'],
                         'Submit or return')
        self.assertEqual(self.sections(self.acc_enc)['with_head']['items'][0]['label'],
                         'Waiting on your Head')

        self.post(self.acc_head, proposal_id, 'return-to-encoder', {'note': 'Shorter.'})

        returned = self.sections(self.acc_enc)['returned']['items'][0]
        self.assertEqual(returned['label'], 'Redraft — returned by your Head')
        self.assertNotIn('returned', self.sections(self.acc_head))

    def test_the_banner_names_returned_work_until_it_is_sent_on(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, 'return', feedback='Not yet.')

        for user in (self.acc_enc, self.acc_head):
            banner = self.banner(user)
            self.assertEqual(banner['total'], 1, user.username)
            self.assertEqual(banner['items'][0]['by'], 'Budget Office')
        self.assertEqual(self.banner(self.bud_head)['total'], 0)

        self.client.post(f'/api/proposals/{proposal_id}/sections/{self.s1.id}/check/',
                         {}, format='json')
        self.send_to_head(proposal_id)
        self.assertEqual(self.banner(self.acc_enc)['total'], 0)

    def test_a_recalled_draft_is_not_returned_work(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        self.post(self.acc_enc, proposal_id, 'recall')
        self.assertEqual(self.banner(self.acc_enc)['total'], 0)


class StalledWithTheHead(HeadStepFixture):

    def test_three_days_with_the_head_is_a_stall_the_head_must_act_on(self):
        proposal_id = self.a_draft()
        self.send_to_head(proposal_id)
        AuditEvent.objects.filter(proposal_id=proposal_id, event=AuditEvent.SENT_TO_HEAD) \
            .update(at=timezone.now() - timedelta(days=4))

        self.assertEqual(monitoring.run(only=['stalls'])['stalls_flagged'], 1)

        stall = self.notices(self.acc_head, Notification.STALLED).get()
        self.assertEqual(stall.severity, 'action')
        self.assertEqual(stall.title, 'FAM 6.02: 4 days with the Head')
        self.assertEqual(self.notices(self.acc_enc, Notification.STALLED).get().severity, 'info')


class TheLastActivityMoves(HeadStepFixture):

    def test_a_transition_updates_the_proposals_last_activity(self):
        proposal_id = self.a_draft()
        Proposal.objects.filter(pk=proposal_id).update(
            updated_at=timezone.now() - timedelta(days=10))

        self.send_to_head(proposal_id)

        updated = Proposal.objects.get(pk=proposal_id).updated_at
        self.assertGreater(updated, timezone.now() - timedelta(minutes=1))
