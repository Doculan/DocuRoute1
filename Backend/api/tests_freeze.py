"""Phase 3D: the change freeze - "do not revise now" before an audit.

The rules with teeth:

- **What waits**: starting a proposal, sending to the Head, submitting
  and making effective are refused (`frozen`), saying until when - and
  only inside the freeze's scope (everything, offices, or series).
- **What carries on**: editing and checking drafts, concurring and
  returning, and every GET.
- **Exceptions** let exactly one proposal or one manual through.
- **Lifting** ends every block at once and tells the offices; a freeze
  past its expected end tells the admin until it is lifted or extended.
- **Deadlines**: overdue, escalation and the weekly repeat pause for what
  a freeze covers, and are caught up once it is lifted. Reminders and the
  due day are not paused.
- Starting, lifting, extending and exceptions ask for the password.

Tests that expect an error assert the reason.
"""

import datetime

from django.utils import timezone

from api import deadline_ladder, freeze_views, monitoring
from api.models import (
    Concurrence, CustomUser, DocumentStatus, Freeze, FreezeException, Manual, ManualSection,
    ManualSeries, ManualSeriesOffice, Notification, OfficeLink, Proposal, SystemEvent,
)
from api.views import issue_reauth_token

from .tests_concurrence import REASON, ConcurrenceFixture
from .tests_effective import EffectiveFixture
from .tests_ladder import LadderFixture


def make_admin(username='freeze_admin'):
    return CustomUser.objects.create_user(
        username=username, password='pw', role='admin', is_approved=True,
        system_role=CustomUser.SYSTEM_ADMIN)


class FreezeAdmin:
    """The admin's calls, shared by the fixtures below."""

    def freeze(self, scope='all', offices=(), series=(), days=10, token=True, **body):
        data = {'reason': 'ISO 9001 surveillance audit', 'scope': scope,
                'expected_end_on': (timezone.localdate() + datetime.timedelta(days=days)).isoformat(),
                **({'office_ids': [o.pk for o in offices]} if offices else {}),
                **({'series_ids': [s.pk for s in series]} if series else {}), **body}
        headers = {'HTTP_X_REAUTH_TOKEN': issue_reauth_token(self.admin)} if token else {}
        return self.as_(self.admin).post('/api/admin/freezes/', data, format='json', **headers)

    def lift(self, freeze_id, token=True):
        headers = {'HTTP_X_REAUTH_TOKEN': issue_reauth_token(self.admin)} if token else {}
        return self.as_(self.admin).post(f'/api/admin/freezes/{freeze_id}/lift/', {},
                                         format='json', **headers)

    def extend(self, freeze_id, days, token=True):
        headers = {'HTTP_X_REAUTH_TOKEN': issue_reauth_token(self.admin)} if token else {}
        until = (timezone.localdate() + datetime.timedelta(days=days)).isoformat()
        return self.as_(self.admin).post(f'/api/admin/freezes/{freeze_id}/extend/',
                                         {'expected_end_on': until}, format='json', **headers)

    def except_(self, freeze_id, token=True, reason='Corrective action from the last audit', **target):
        headers = {'HTTP_X_REAUTH_TOKEN': issue_reauth_token(self.admin)} if token else {}
        return self.as_(self.admin).post(f'/api/admin/freezes/{freeze_id}/exceptions/',
                                         {**target, 'reason': reason}, format='json', **headers)


class FreezeFixture(FreezeAdmin, ConcurrenceFixture):

    def setUp(self):
        super().setUp()
        self.admin = make_admin()
        # A second series Accounting also concurs on.
        self.other_series = ManualSeries.objects.create(code='QM', title='Quality Manual',
                                                        owning_office=self.vpaf)
        ManualSeriesOffice.objects.create(series=self.other_series, office=self.accounting,
                                          relationship=OfficeLink.CONCURRING)
        self.other = Manual.objects.create(title='QM 1.01', series=self.other_series)
        ManualSection.objects.create(manual=self.other, subtitle='1.0 PURPOSE', order=0,
                                     content='This manual sets the quality policy.', tag='POLICY')

    def start(self, user=None, manual=None):
        user = user or self.acc_enc
        return self.as_(user).post('/api/proposals/', {'manual_id': (manual or self.manual).pk},
                                   format='json', HTTP_X_REAUTH_TOKEN=self.token(user))

    def assert_frozen(self, response, until_days=10):
        self.assertEqual((response.status_code, response.data.get('reason')), (409, 'frozen'),
                         getattr(response, 'data', None))
        until = timezone.localdate() + datetime.timedelta(days=until_days)
        self.assertIn(f'Frozen for audit until {until:%d %b %Y}', response.data['error'])
        self.assertEqual(response.data['freeze']['expected_end_on'], until)


# --- starting one --------------------------------------------

class StartingOne(FreezeFixture):

    def test_the_admin_starts_one_with_the_password(self):
        response = self.freeze()
        self.assertEqual(response.status_code, 201, response.data)
        made = Freeze.objects.get()
        self.assertEqual((made.scope, made.started_by, made.lifted_at), (Freeze.ALL, self.admin, None))
        self.assertTrue(SystemEvent.objects.filter(kind=SystemEvent.FREEZE_STARTED).exists())

    def test_refusals_name_the_reason(self):
        cases = [
            (dict(reason=''), 'reason_required'),
            (dict(reason='x' * 301), 'reason_required'),
            (dict(days=-1), 'invalid_date'),
            (dict(scope='some'), 'invalid_scope'),
            (dict(scope='offices'), 'invalid_offices'),
            (dict(scope='series'), 'invalid_series'),
            (dict(scope='offices', office_ids=[999999]), 'invalid_offices'),
            (dict(token=False), 'reauth_required'),
        ]
        for kwargs, reason in cases:
            self.assertEqual(self.freeze(**kwargs).data.get('reason'), reason, kwargs)
        self.assertFalse(Freeze.objects.exists())

    def test_only_the_admin(self):
        response = self.as_(self.acc_head).post('/api/admin/freezes/', {}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.as_(self.acc_head).get('/api/admin/freezes/').status_code, 403)

    def test_the_offices_it_covers_are_told_and_no_others(self):
        self.freeze(scope='offices', offices=[self.budget])
        told = set(Notification.objects.filter(kind=Notification.FREEZE)
                   .values_list('recipient__username', flat=True))
        self.assertEqual(told, {'bud_head', 'bud_enc'})
        notice = Notification.objects.filter(kind=Notification.FREEZE, recipient=self.bud_head).get()
        self.assertTrue(notice.title.startswith('Frozen for audit until'), notice.title)
        self.assertEqual(notice.severity, 'info')

    def test_a_series_freeze_tells_the_offices_that_concur_on_it(self):
        self.freeze(scope='series', series=[self.other_series])
        told = set(Notification.objects.filter(kind=Notification.FREEZE)
                   .values_list('recipient__username', flat=True))
        self.assertEqual(told, {'acc_head', 'acc_enc'})


# --- what waits, and only inside scope -----------------------

class WhatWaits(FreezeFixture):

    def test_starting_a_proposal_waits(self):
        self.freeze()
        self.assert_frozen(self.start())
        self.assertFalse(Proposal.objects.exists())

    def test_sending_to_the_head_and_submitting_wait(self):
        proposal_id = self.a_draft()
        self.freeze()
        self.assert_frozen(self.send_to_head(proposal_id))
        Proposal.objects.filter(pk=proposal_id).update(status=Proposal.WITH_HEAD)
        response = self.as_(self.acc_head).post(f'/api/proposals/{proposal_id}/submit/', {},
                                                format='json', HTTP_X_REAUTH_TOKEN=self.token(self.acc_head))
        self.assert_frozen(response)
        self.assertEqual(Proposal.objects.get(pk=proposal_id).status, Proposal.WITH_HEAD)

    def test_an_office_freeze_stops_only_those_offices(self):
        self.freeze(scope='offices', offices=[self.budget])
        self.assert_frozen(self.start(self.bud_enc))
        self.assertEqual(self.start(self.acc_enc).status_code, 201)

    def test_a_series_freeze_stops_only_its_documents(self):
        self.freeze(scope='series', series=[self.other_series])
        self.assert_frozen(self.start(manual=self.other))
        self.assertEqual(self.start(manual=self.manual).status_code, 201)


class WhatCarriesOn(FreezeFixture):

    def test_drafts_stay_editable_and_checkable(self):
        proposal_id = self.a_draft()
        self.freeze()
        response = self.client.put(f'/api/proposals/{proposal_id}/sections/{self.s2.id}/',
                                   {'new_text': 'The Accounting Staff verifies it within a day.'},
                                   format='json')
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post(f'/api/proposals/{proposal_id}/sections/{self.s2.id}/check/',
                                    {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_concurrence_continues(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.freeze()
        self.assertEqual(self.decide(proposal_id, self.bud_head, Concurrence.CONCUR).status_code, 200)
        self.assertEqual(self.decide(proposal_id, self.cmo_head, Concurrence.CONCUR).status_code, 200)
        # Locking is not blocked: the documents are made for signing.
        self.assertEqual(Proposal.objects.get(pk=proposal_id).status, Proposal.AWAITING_SIGNATURE)

    def test_no_get_is_blocked_and_each_says_so(self):
        proposal_id = self.a_draft()
        self.freeze()
        for user, url in ((self.acc_enc, f'/api/proposals/{proposal_id}/full/'),
                          (self.acc_enc, f'/api/manuals/{self.manual.pk}/sections/'),
                          (self.acc_enc, '/api/action-banner/'),
                          (self.acc_enc, '/api/proposals/'),
                          (self.admin, '/api/admin/freezes/')):
            response = self.as_(user).get(url)
            self.assertEqual(response.status_code, 200, url)
        full = self.as_(self.acc_enc).get(f'/api/proposals/{proposal_id}/full/').data
        self.assertEqual((full['freeze'] or {}).get('reason'), 'ISO 9001 surveillance audit')
        sections = self.as_(self.acc_enc).get(f'/api/manuals/{self.manual.pk}/sections/').data
        self.assertIsNotNone(sections['freeze'])


# --- exceptions and lifting ----------------------------------

class Exceptions(FreezeFixture):

    def test_a_proposal_exception_lets_exactly_that_one_through(self):
        ours = self.a_draft()
        self.client = self.as_(self.bud_enc)           # Budget drafts its own, ready to send
        theirs = self.as_(self.bud_enc).post('/api/proposals/', {'manual_id': self.manual.pk},
                                             format='json',
                                             HTTP_X_REAUTH_TOKEN=self.token(self.bud_enc)).data['id']
        self.client.patch(f'/api/proposals/{theirs}/', {'overall_reason': REASON}, format='json')
        self.client.put(f'/api/proposals/{theirs}/sections/{self.s2.id}/',
                        {'new_text': 'The Budget Staff verifies the request.'}, format='json')
        self.client.post(f'/api/proposals/{theirs}/sections/{self.s2.id}/check/', {}, format='json')
        freeze_id = self.freeze().data['id']
        self.assertEqual(self.except_(freeze_id, proposal_id=ours).status_code, 201)
        self.assertEqual(self.send_to_head(ours).status_code, 200)
        self.assert_frozen(self.send_to_head(theirs, self.bud_enc))

    def test_a_manual_exception_lets_its_proposals_through(self):
        freeze_id = self.freeze().data['id']
        self.assertEqual(self.except_(freeze_id, manual_id=self.other.pk).status_code, 201)
        self.assertEqual(self.start(manual=self.other).status_code, 201)
        self.assert_frozen(self.start(manual=self.manual))
        self.assertTrue(SystemEvent.objects.filter(kind=SystemEvent.FREEZE_EXCEPTION_GRANTED,
                                                   manual=self.other).exists())

    def test_refusals_name_the_reason(self):
        freeze_id = self.freeze().data['id']
        cases = [
            (dict(), 'invalid_exception'),
            (dict(manual_id=999999), 'invalid_exception'),
            (dict(manual_id=self.other.pk, reason=''), 'reason_required'),
            (dict(manual_id=self.other.pk, token=False), 'reauth_required'),
        ]
        for kwargs, reason in cases:
            self.assertEqual(self.except_(freeze_id, **kwargs).data.get('reason'), reason, kwargs)
        self.assertFalse(FreezeException.objects.exists())


class Lifting(FreezeFixture):

    def test_lifting_ends_every_block_at_once(self):
        proposal_id = self.a_draft()
        freeze_id = self.freeze().data['id']
        self.assert_frozen(self.send_to_head(proposal_id))
        self.assert_frozen(self.start(manual=self.other))
        self.assertEqual(self.lift(freeze_id, token=False).data.get('reason'), 'reauth_required')
        self.assertEqual(self.lift(freeze_id).status_code, 200)
        self.assertEqual(self.send_to_head(proposal_id).status_code, 200)
        self.assertEqual(self.start(manual=self.other).status_code, 201)
        self.assertEqual(self.lift(freeze_id).data.get('reason'), 'not_in_force')

    def test_any_freeze_in_force_blocks(self):
        first = self.freeze(scope='offices', offices=[self.accounting]).data['id']
        self.freeze(scope='series', series=[self.series])
        self.lift(first)
        self.assert_frozen(self.start())

    def test_the_offices_are_told_it_is_lifted(self):
        freeze_id = self.freeze(scope='offices', offices=[self.budget]).data['id']
        self.lift(freeze_id)
        self.assertEqual(set(Notification.objects.filter(
            kind=Notification.FREEZE, title='The change freeze is lifted',
        ).values_list('recipient__username', flat=True)), {'bud_head', 'bud_enc'})
        self.assertTrue(SystemEvent.objects.filter(kind=SystemEvent.FREEZE_LIFTED).exists())

    def test_past_its_end_the_admin_is_told_once_until_extended(self):
        freeze_id = self.freeze(days=1).data['id']
        later = timezone.now() + datetime.timedelta(days=3)
        self.assertEqual(freeze_views.monitor(later)['past_end'], 1)
        self.assertEqual(freeze_views.monitor(later)['past_end'], 0)
        notice = Notification.objects.get(kind=Notification.FREEZE, recipient=self.admin,
                                          severity='action')
        self.assertIsNone(notice.acted_at)
        self.assertEqual(self.extend(freeze_id, 20, token=False).data.get('reason'), 'reauth_required')
        self.assertEqual(self.extend(freeze_id, 20).status_code, 200)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.acted_at)
        self.assertEqual(Freeze.objects.get().expected_end_on,
                         timezone.localdate() + datetime.timedelta(days=20))
        self.assertTrue(SystemEvent.objects.filter(kind=SystemEvent.FREEZE_EXTENDED).exists())


# --- what people see -----------------------------------------

class TheActionRow(FreezeFixture):

    def banner(self, user):
        return self.as_(user).get('/api/action-banner/').data

    def test_the_offices_it_covers_see_one_line_others_none(self):
        self.freeze(scope='offices', offices=[self.budget])
        self.freeze(scope='offices', offices=[self.budget], reason='Second audit')
        frozen = self.banner(self.bud_enc)['freeze']
        # One freeze, never a list: the row stays at most two lines.
        self.assertIsInstance(frozen, dict)
        self.assertEqual(frozen['reason'], 'ISO 9001 surveillance audit')
        self.assertIsNone(self.banner(self.acc_enc)['freeze'])

    def test_the_admin_and_qms_staff_see_it_without_an_office(self):
        self.freeze(scope='offices', offices=[self.budget])
        self.assertIsNotNone(self.banner(self.admin)['freeze'])

    def test_with_none_in_force_nothing(self):
        self.assertIsNone(self.banner(self.acc_enc)['freeze'])
        self.assertIsNone(self.as_(self.acc_enc).get(
            f'/api/manuals/{self.manual.pk}/sections/').data['freeze'])


# --- making effective ----------------------------------------

class MakingEffectiveWaits(FreezeAdmin, EffectiveFixture):

    def setUp(self):
        super().setUp()
        self.admin = make_admin()

    def test_refused_with_nothing_written_then_allowed_once_lifted(self):
        freeze_id = self.freeze().data['id']
        response = self.make_effective()
        self.assertEqual((response.status_code, response.data.get('reason')), (409, 'frozen'))
        self.assertIn('Making it effective waits', response.data['error'])
        self.assert_nothing_written()
        # Reading the form is not blocked.
        self.assertEqual(self.as_(self.custodian).get(self.url + 'custodian/effective/').status_code, 200)
        self.lift(freeze_id)
        self.assertEqual(self.make_effective().status_code, 200)
        self.assertTrue(DocumentStatus.objects.filter(proposal=self.proposal).exists())

    def test_an_exception_for_the_manual_lets_it_through(self):
        freeze_id = self.freeze().data['id']
        self.except_(freeze_id, manual_id=self.manual.pk)
        self.assertEqual(self.make_effective().status_code, 200)

    def test_the_custodian_sees_why(self):
        self.freeze()
        full = self.as_(self.custodian).get(self.url + 'full/').data
        self.assertTrue(full['can_make_effective'])
        self.assertEqual((full['freeze'] or {}).get('reason'), 'ISO 9001 surveillance audit')


# --- deadlines -----------------------------------------------

class DeadlinesPause(FreezeAdmin, LadderFixture):

    def setUp(self):
        super().setUp()
        self.admin_user = self.admin

    def test_overdue_pauses_and_is_caught_up_after_lifting(self):
        self.owed(days=1, reminders=[])
        freeze_id = self.freeze(days=30).data['id']
        paused = []
        sent = deadline_ladder.send(lambda: None, now=self.start + datetime.timedelta(days=8),
                                    paused=paused)
        self.assertEqual((sent, len(paused)), (0, 2))       # overdue and escalated, held
        self.assertFalse(self.told(Notification.DEADLINE_OVERDUE).exists())
        self.lift(freeze_id)
        self.assertEqual(self.run_on(8), 2)
        self.assertTrue(self.told(Notification.DEADLINE_OVERDUE, self.acc_head).exists())
        self.assertTrue(self.told(Notification.DEADLINE_ESCALATED, self.vp_head).exists())

    def test_reminders_and_the_due_day_are_not_paused(self):
        self.owed(days=3, reminders=[1])
        self.freeze(days=30)
        self.assertEqual(self.run_on(2), 1)
        self.assertEqual(self.run_on(3), 1)
        self.assertEqual(self.run_on(4), 0)                  # overdue: paused

    def test_only_what_the_freeze_covers(self):
        self.owed(office=self.bud, days=1, reminders=[])
        self.owed(office=self.acc, days=1, reminders=[])
        self.freeze(scope='offices', offices=[self.acc], days=30)
        self.assertEqual(self.run_on(2), 1)
        self.assertTrue(self.told(Notification.DEADLINE_OVERDUE, self.bud_head).exists())
        self.assertFalse(self.told(Notification.DEADLINE_OVERDUE, self.acc_head).exists())

    def test_an_exception_for_every_manual_owed_unpauses_it(self):
        self.owed(manuals=[self.m1], days=1, reminders=[])
        freeze_id = self.freeze(days=30).data['id']
        self.assertEqual(self.run_on(2), 0)
        self.except_(freeze_id, manual_id=self.m1.pk)
        self.assertEqual(self.run_on(2), 1)

    def test_the_run_counts_them_and_the_dry_run_says_so(self):
        self.owed(days=1, reminders=[])
        self.freeze(days=30)
        counts = monitoring.run(only=['deadlines'], now=self.start + datetime.timedelta(days=2))
        self.assertEqual((counts['deadline_notices_sent'], counts['deadline_notices_paused_by_freeze']),
                         (0, 1))
        plan = monitoring.dry_run(self.start + datetime.timedelta(days=2))
        self.assertEqual((plan['deadlines'], plan['paused_by_freeze']), ([], 1))

    def test_the_tag_says_frozen_for_audit(self):
        self.owed(manuals=[self.m1], days=10)
        self.freeze(scope='series', series=[self.fam], days=30)
        tag = self.as_(self.acc_head).get(f'/api/manuals/{self.m1.pk}/sections/').data['deadline']
        self.assertEqual((tag['frozen'] or {}).get('reason'), 'ISO 9001 surveillance audit')

    def test_a_deadline_inside_the_freeze_tells_the_admin_once(self):
        deadline = self.owed(days=5)
        self.freeze(days=30)                                 # raised at start
        notice = Notification.objects.get(kind=Notification.FREEZE, recipient=self.admin,
                                          dedupe_key__contains=':deadline:')
        self.assertIn(deadline.title, notice.title)
        self.assertEqual(freeze_views.monitor()['deadlines_inside'], 0)
