"""Notifications for concurrence.

The bug: after a concurring office concurred or returned a proposal,
nothing told the proposing office. It had to open the proposal to find
out. These tests follow one proposal through the concurrence stage and
check who hears about each step - and who does not.
"""

import datetime

from api.models import AuditEvent, Concurrence, Notification

from .tests_concurrence import ConcurrenceFixture


class NotificationFixture(ConcurrenceFixture):

    def inbox(self, user):
        return self.as_(user).get('/api/notifications/').data

    def events_for(self, user):
        return [n['event'] for n in self.inbox(user)['notifications']]


class SubmissionNotifiesConcurringOffices(NotificationFixture):

    def test_every_concurring_office_is_told(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        for user in (self.bud_head, self.bud_enc, self.cmo_head):
            inbox = self.inbox(user)
            self.assertEqual(inbox['unread'], 1, user.username)
            self.assertEqual(inbox['notifications'][0]['proposal_id'], proposal_id)
            self.assertIn('Accounting Office asks your office to concur',
                          inbox['notifications'][0]['message'])

    def test_the_proposing_office_is_not_told_of_its_own_submission(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.assertEqual(self.events_for(self.acc_head), [])
        # The Encoder is in the proposing office, not a concurring one.
        self.assertEqual(self.events_for(self.acc_enc), [])


class DecisionsNotifyTheProposingOffice(NotificationFixture):

    def test_a_concurrence_reaches_the_encoder_and_the_head(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)

        for user in (self.acc_head, self.acc_enc):
            inbox = self.inbox(user)
            self.assertEqual(inbox['unread'], 1, user.username)
            self.assertEqual(inbox['notifications'][0]['message'],
                             'Budget Office concurred on FAM 6.02.')

    def test_a_return_carries_the_feedback(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.RETURN,
                    feedback='Keep the five-day window for cheques over 1M.')

        notice = self.inbox(self.acc_enc)['notifications'][0]
        self.assertEqual(notice['event'], AuditEvent.RETURNED)
        self.assertEqual(notice['message'],
                         'Budget Office returned FAM 6.02 with feedback.')
        self.assertEqual(notice['detail'],
                         'Keep the five-day window for cheques over 1M.')

    def test_the_last_concurrence_also_says_it_locked(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)
        self.decide(proposal_id, self.cmo_head, Concurrence.CONCUR)

        events = self.events_for(self.acc_head)
        self.assertIn(AuditEvent.LOCKED, events)
        self.assertEqual(events.count(AuditEvent.CONCURRED), 2)

    def test_the_deciding_head_is_not_told_of_their_own_decision(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)
        # Only the submission notice, from before.
        self.assertEqual(self.events_for(self.bud_head), [AuditEvent.SUBMITTED])

    def test_a_refused_decision_notifies_nobody(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        before = Notification.objects.count()
        # An Encoder cannot commit the office.
        self.decide(proposal_id, self.bud_enc, Concurrence.CONCUR)
        self.assertEqual(Notification.objects.count(), before)

    def test_someone_whose_post_has_ended_is_not_told(self):
        proposal_id = self.a_draft()        # the Encoder drafts first
        self.submit(proposal_id)

        assignment = self.acc_enc.position_assignments.get()
        assignment.starts_on = self.today - datetime.timedelta(days=30)
        assignment.ends_on = self.today - datetime.timedelta(days=1)
        assignment.save()

        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)
        self.assertFalse(Notification.objects.filter(user=self.acc_enc).exists())


class ReadingNotifications(NotificationFixture):

    def setUp(self):
        super().setUp()
        self.proposal_id = self.a_draft()
        self.submit(self.proposal_id)
        self.decide(self.proposal_id, self.bud_head, Concurrence.CONCUR)

    def test_opening_the_proposal_marks_its_notices_read(self):
        self.assertEqual(self.inbox(self.acc_enc)['unread'], 1)
        self.as_(self.acc_enc).get(f'/api/proposals/{self.proposal_id}/full/')
        inbox = self.inbox(self.acc_enc)
        self.assertEqual(inbox['unread'], 0)
        self.assertTrue(inbox['notifications'][0]['read'])

    def test_opening_it_does_not_read_them_for_anyone_else(self):
        self.as_(self.acc_enc).get(f'/api/proposals/{self.proposal_id}/full/')
        self.assertEqual(self.inbox(self.acc_head)['unread'], 1)

    def test_mark_all_read(self):
        response = self.as_(self.acc_head).post(
            '/api/notifications/read/', {}, format='json')
        self.assertEqual(response.data['marked'], 1)
        self.assertEqual(self.inbox(self.acc_head)['unread'], 0)

    def test_a_bad_proposal_id_is_refused(self):
        response = self.as_(self.acc_head).post(
            '/api/notifications/read/', {'proposal_id': 'x'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_the_inbox_needs_a_login(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get('/api/notifications/').status_code, 401)
