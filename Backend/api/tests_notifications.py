"""Notifications: who is told, how they are told, and when it is done.

Follows one proposal through concurrence and checks who hears about each
step - and who does not. Then the rules of the rebuilt inbox (Phase 2A):

- **Action required clears only when it is done**, by anyone entitled; the
  Encoder's copy of a Head-only request is info.
- **One notice per person per thing**, addressed to their senior post.
- **Every notice names its manual and exactly one cause**, and its words
  are stored when it is written.
- **Who was told, read and acted** is in the system log, one row per
  notification batch, per read and per resolving action.

Tests that expect an error assert the reason.
"""

import datetime

from django.db import IntegrityError, transaction

from api import notifications, system_log
from api.models import (
    AuditEvent, Concurrence, Notification, Office, Position, Proposal,
    SystemEvent,
)

from .tests_concurrence import ConcurrenceFixture


class NotificationFixture(ConcurrenceFixture):

    def inbox(self, user, **params):
        return self.as_(user).get('/api/notifications/', params).data

    def kinds_for(self, user):
        return [n['kind'] for n in self.inbox(user)['notifications']]

    def notice(self, user, kind):
        return Notification.objects.get(recipient=user, kind=kind)


class SubmissionNotifiesConcurringOffices(NotificationFixture):

    def test_every_concurring_office_is_told(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        for user in (self.bud_head, self.bud_enc, self.cmo_head):
            inbox = self.inbox(user)
            self.assertEqual(inbox['unread'], 1, user.username)
            first = inbox['notifications'][0]
            self.assertEqual(first['proposal_id'], proposal_id)
            self.assertEqual(first['manual'], 'FAM 6.02')
            self.assertEqual(first['title'],
                             'Accounting Office asks your office to concur on FAM 6.02')

    def test_the_head_must_act_and_the_encoder_is_informed(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.assertEqual(self.notice(self.bud_head, 'concurrence_requested').severity, 'action')
        self.assertEqual(self.notice(self.bud_enc, 'concurrence_requested').severity, 'info')
        self.assertEqual(self.notice(self.bud_head, 'concurrence_requested').addressed_position_title,
                         'Budget Office — Head')

    def test_the_proposing_office_is_not_told_of_its_own_submission(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.assertEqual(self.kinds_for(self.acc_head), [])
        self.assertEqual(self.kinds_for(self.acc_enc), [])


class DecisionsNotifyTheProposingOffice(NotificationFixture):

    def test_a_concurrence_reaches_the_encoder_and_the_head(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)

        for user in (self.acc_head, self.acc_enc):
            inbox = self.inbox(user)
            self.assertEqual(inbox['unread'], 1, user.username)
            self.assertEqual(inbox['notifications'][0]['title'],
                             'Budget Office concurred on FAM 6.02')
            self.assertEqual(inbox['notifications'][0]['severity'], 'info')

    def test_a_return_carries_the_feedback_and_the_section(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.RETURN,
                    feedback='Keep the five-day window for cheques over 1M.',
                    section=self.s1)

        for user in (self.acc_enc, self.acc_head):
            notice = self.inbox(user)['notifications'][0]
            self.assertEqual(notice['kind'], 'returned_by_office')
            self.assertEqual(notice['severity'], 'action')
            self.assertEqual(notice['title'], 'Budget Office returned FAM 6.02')
            self.assertEqual(notice['body'],
                             '“Keep the five-day window for cheques over 1M.” — 3.0 POLICIES')

    def test_the_last_concurrence_also_says_it_locked(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)
        self.decide(proposal_id, self.cmo_head, Concurrence.CONCUR)

        kinds = self.kinds_for(self.acc_head)
        self.assertIn('locked', kinds)
        self.assertEqual(kinds.count('concurred'), 2)

    def test_the_deciding_head_is_not_told_of_their_own_decision(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)
        self.assertEqual(self.kinds_for(self.bud_head), ['concurrence_requested'])

    def test_a_refused_decision_notifies_nobody(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        before = Notification.objects.count()
        response = self.decide(proposal_id, self.bud_enc, Concurrence.CONCUR)
        self.assertEqual(response.data['reason'], 'not_head')
        self.assertEqual(Notification.objects.count(), before)

    def test_someone_whose_post_has_ended_is_not_told(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)

        assignment = self.acc_enc.position_assignments.get()
        assignment.starts_on = self.today - datetime.timedelta(days=30)
        assignment.ends_on = self.today - datetime.timedelta(days=1)
        assignment.save()

        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)
        self.assertFalse(Notification.objects.filter(recipient=self.acc_enc).exists())


class ActionClearsWhenDone(NotificationFixture):

    def test_concurring_clears_the_heads_request_and_not_another_offices(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.CONCUR)

        budget = self.notice(self.bud_head, 'concurrence_requested')
        cash = self.notice(self.cmo_head, 'concurrence_requested')
        self.assertIsNotNone(budget.acted_at)
        self.assertEqual(budget.acted_by, self.bud_head)
        self.assertIsNone(cash.acted_at)

    def test_reading_an_action_does_not_clear_it(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.as_(self.bud_head).post('/api/notifications/read/', {}, format='json')

        self.assertEqual(self.inbox(self.bud_head)['unread'], 1)
        # The Encoder's info copy is cleared by reading.
        self.as_(self.bud_enc).post('/api/notifications/read/', {}, format='json')
        self.assertEqual(self.inbox(self.bud_enc)['unread'], 0)

    def test_resubmitting_clears_every_copy_of_the_return_once(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.bud_head, Concurrence.RETURN, feedback='Not yet.')
        version = Proposal.objects.get(pk=proposal_id).current_version()
        self.client.post(f'/api/proposals/{proposal_id}/sections/{self.s1.id}/check/',
                         {}, format='json')
        before = SystemEvent.objects.filter(kind=SystemEvent.NOTIFICATION_ACTED).count()

        response = self.submit(proposal_id)
        self.assertEqual(response.status_code, 200, response.data)

        returned = Notification.objects.filter(kind='returned_by_office')
        self.assertEqual({n.recipient for n in returned}, {self.acc_head, self.acc_enc})
        for notice in returned:
            self.assertIsNotNone(notice.acted_at)
            self.assertEqual(notice.acted_by, self.acc_head)
        acted = SystemEvent.objects.filter(kind=SystemEvent.NOTIFICATION_ACTED)
        self.assertEqual(acted.count(), before + 1)
        self.assertEqual(sorted(acted.last().detail['notices']),
                         sorted(n.pk for n in returned))
        self.assertEqual(version.number, 2)

    def test_withdrawing_clears_open_requests_and_tells_the_concurring_offices(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.as_(self.acc_head).post(
            f'/api/proposals/{proposal_id}/withdraw/', {'reason': 'Superseded.'},
            format='json', HTTP_X_REAUTH_TOKEN=self.token(self.acc_head))

        self.assertIsNotNone(self.notice(self.cmo_head, 'concurrence_requested').acted_at)
        withdrawn = self.notice(self.cmo_head, 'withdrawn')
        self.assertEqual(withdrawn.severity, 'info')
        self.assertEqual(withdrawn.body, '“Superseded.”')


class OneNoticePerPerson(NotificationFixture):

    def test_a_person_with_two_posts_in_an_office_gets_one_notice_as_head(self):
        encoder_post = Position.objects.get(office=self.budget, kind=Position.ENCODER)
        self.bud_head.position_assignments.create(position=encoder_post, starts_on=self.today)
        proposal_id = self.a_draft()
        self.submit(proposal_id)

        mine = Notification.objects.filter(recipient=self.bud_head)
        self.assertEqual(mine.count(), 1)
        self.assertEqual(mine.get().addressed_position.kind, Position.HEAD)
        self.assertEqual(mine.get().severity, 'action')

    def test_the_same_key_is_refused_by_the_database(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        original = self.notice(self.bud_head, 'concurrence_requested')
        copy = Notification(
            recipient=self.bud_head, kind=original.kind, severity='info', title='again',
            manual=original.manual, audit_event=original.audit_event,
            dedupe_key=original.dedupe_key,
        )
        with self.assertRaises(IntegrityError) as raised, transaction.atomic():
            copy.save()
        self.assertIn('recipient', str(raised.exception).lower())


class EveryNoticeIsComplete(NotificationFixture):

    def setUp(self):
        super().setUp()
        self.proposal_id = self.a_draft()
        self.submit(self.proposal_id)
        self.original = self.notice(self.bud_head, 'concurrence_requested')

    def attempt(self, **fields):
        values = dict(recipient=self.cmo_head, kind='concurred', severity='info',
                      title='x', manual=self.manual, audit_event=self.original.audit_event,
                      dedupe_key='test:1')
        values.update(fields)
        with self.assertRaises(IntegrityError) as raised, transaction.atomic():
            Notification.objects.create(**values)
        return str(raised.exception)

    def test_a_notice_without_a_manual_must_be_office_level(self):
        self.assertIn('notification_names_its_manual', self.attempt(manual=None))

    def test_a_notice_has_exactly_one_cause(self):
        self.assertIn('notification_has_exactly_one_cause', self.attempt(audit_event=None))
        event = system_log.record(SystemEvent.STALLED)
        self.assertIn('notification_has_exactly_one_cause', self.attempt(system_event=event))

    def test_only_an_action_can_be_acted_on(self):
        from django.utils import timezone
        self.assertIn('only_action_notifications_are_acted_on',
                      self.attempt(acted_at=timezone.now()))

    def test_the_words_are_stored_not_rebuilt(self):
        self.accounting.name = 'Accounting and Records Office'
        self.accounting.save(update_fields=['name'])
        self.assertEqual(self.inbox(self.bud_head)['notifications'][0]['title'],
                         'Accounting Office asks your office to concur on FAM 6.02')


class TheTrailOfWhoWasTold(NotificationFixture):

    def test_one_notified_row_lists_everyone_told(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        event = AuditEvent.objects.get(proposal_id=proposal_id, event=AuditEvent.SUBMITTED)

        notified = SystemEvent.objects.get(kind=SystemEvent.NOTIFIED)
        self.assertEqual(notified.actor_label, 'system')
        self.assertEqual(notified.detail['cause'], {'audit_event': event.pk})
        self.assertEqual({r['user'] for r in notified.detail['recipients']},
                         {self.bud_head.pk, self.bud_enc.pk, self.cmo_head.pk})
        self.assertEqual(system_log.verify(), (SystemEvent.objects.count(), None))

    def test_the_first_read_is_logged_and_a_second_is_not(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        reader = self.as_(self.bud_enc)
        reader.post('/api/notifications/read/', {}, format='json')
        reader.post('/api/notifications/read/', {}, format='json')

        reads = SystemEvent.objects.filter(kind=SystemEvent.NOTIFICATION_READ)
        self.assertEqual(reads.count(), 1)
        self.assertEqual(reads.get().actor, self.bud_enc)
        self.assertEqual(reads.get().detail['notices'],
                         [self.notice(self.bud_enc, 'concurrence_requested').pk])


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
        response = self.as_(self.acc_head).post('/api/notifications/read/', {}, format='json')
        self.assertEqual(response.data['marked'], 1)
        self.assertEqual(self.inbox(self.acc_head)['unread'], 0)

    def test_marking_chosen_notices_read(self):
        self.decide(self.proposal_id, self.cmo_head, Concurrence.CONCUR)
        first = Notification.objects.filter(recipient=self.acc_enc, kind='concurred').first()
        response = self.as_(self.acc_enc).post(
            '/api/notifications/read/', {'ids': [first.pk]}, format='json')
        self.assertEqual(response.data['marked'], 1)
        self.assertTrue(Notification.objects.filter(
            recipient=self.acc_enc, read_at__isnull=True).exists())

    def test_bad_input_is_refused_with_the_reason(self):
        client = self.as_(self.acc_head)
        for body, reason in (({'proposal_id': 'x'}, 'invalid_proposal'),
                             ({'ids': 'all'}, 'invalid_ids')):
            response = client.post('/api/notifications/read/', body, format='json')
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data['reason'], reason)

    def test_the_page_filters_by_severity_and_pages(self):
        everything = self.inbox(self.bud_head)
        self.assertEqual(everything['count'], 1)
        self.assertEqual(self.inbox(self.bud_head, filter='info')['count'], 0)
        self.assertEqual(self.inbox(self.bud_head, filter='action')['count'], 1)
        for params, reason in (({'filter': 'urgent'}, 'invalid_filter'),
                               ({'page': '0'}, 'invalid_page')):
            response = self.as_(self.bud_head).get('/api/notifications/', params)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data['reason'], reason)

    def test_the_inbox_needs_a_login(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get('/api/notifications/').status_code, 401)


class QmsStagesNotify(NotificationFixture):
    """The IMR's and custodian's steps used to notify nobody."""

    def setUp(self):
        super().setUp()
        qms = Office.objects.create(name='Quality Management Office', abbreviation='QMS')
        self.imr = self.person('imr', qms, Position.IMR)
        self.custodian = self.person('custodian', qms, Position.DOCUMENT_CUSTODIAN)
        self.proposal_id = self.a_draft()
        self.submit(self.proposal_id)
        self.proposal = Proposal.objects.get(pk=self.proposal_id)

    def event(self, kind, status, office=None, actor=None, detail=''):
        Proposal.objects.filter(pk=self.proposal_id).update(status=status)
        self.proposal.refresh_from_db()
        office = office or self.accounting
        event = AuditEvent.objects.create(
            proposal=self.proposal, version=self.proposal.current_version(), event=kind,
            actor=actor or self.acc_head, office=office, office_name_at_time=office.name,
            detail=detail)
        notifications.notify(event)
        return event

    def test_complete_signed_copies_ask_the_imr_and_clear_the_lock_notice(self):
        self.event(AuditEvent.LOCKED, Proposal.AWAITING_SIGNATURE, actor=self.cmo_head)
        self.event(AuditEvent.PACKAGE_COMPLETE, Proposal.READY_FOR_IMR, actor=self.acc_enc)

        ready = self.notice(self.imr, 'ready_for_imr')
        self.assertEqual(ready.severity, 'action')
        self.assertEqual(ready.addressed_position_title,
                         'Quality Management Office — Integrated Management Representative')
        locked = self.notice(self.acc_head, 'locked')
        self.assertEqual(locked.acted_by, self.acc_enc)

    def test_a_denial_informs_every_office_involved(self):
        self.event(AuditEvent.IMR_DENIED, Proposal.DENIED, office=self.imr_office(),
                   actor=self.imr, detail='Conflicts with the 2026 circular.')
        for user in (self.acc_head, self.acc_enc, self.bud_head, self.cmo_head):
            notice = self.notice(user, 'imr_denied')
            self.assertEqual(notice.severity, 'info')
            self.assertEqual(notice.body, '“Conflicts with the 2026 circular.”')

    def test_effective_informs_and_clears_the_custodians_request(self):
        self.event(AuditEvent.APPROVAL_UPLOADED, Proposal.WITH_CUSTODIAN,
                   office=self.imr_office(), actor=self.imr)
        self.assertEqual(self.notice(self.custodian, 'approval_uploaded').severity, 'action')
        self.assertEqual(self.notice(self.acc_head, 'approval_uploaded').severity, 'info')

        self.event(AuditEvent.MADE_EFFECTIVE, Proposal.EFFECTIVE,
                   office=self.imr_office(), actor=self.custodian)
        self.assertEqual(self.notice(self.custodian, 'approval_uploaded').acted_by, self.custodian)
        self.assertEqual(self.notice(self.bud_enc, 'made_effective').severity, 'info')

    def test_the_imr_deciding_through_the_screen_notifies(self):
        Proposal.objects.filter(pk=self.proposal_id).update(status=Proposal.READY_FOR_IMR)
        response = self.as_(self.imr).post(
            f'/api/proposals/{self.proposal_id}/imr/',
            {'decision': 'deny', 'comments': 'Out of scope.'}, format='json',
            HTTP_X_REAUTH_TOKEN=self.token(self.imr))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.notice(self.acc_head, 'imr_denied').body, '“Out of scope.”')

    def imr_office(self):
        return Office.objects.get(abbreviation='QMS')
