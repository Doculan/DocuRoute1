"""Phase 3C-2: a Head on leave delegates for a dated period.

The rules with teeth:

- **Only inside the period**: a delegate is refused (`not_head`) the day
  before it starts and the day after it ends, and at once when it is
  ended early.
- **Who may be one** (Q-6): a post holder in the office or the Head above;
  named by the Head in their own post, or the admin, with the password;
  never two periods overlapping.
- **The record**: the delegate's step is theirs, `acting_for` the Head,
  shown "(delegated)"; the Head's own steps carry nothing. Generated
  forms print position titles only - no delegate's name.
- **Notices** for the Head go to the delegate instead.
- **Maker-checker**: a delegate may not submit, concur on or return a
  proposal they drafted or sent to the Head.

Tests that expect an error assert the reason.
"""

import datetime

from django.utils import timezone

from api.models import (
    AuditEvent, Attachment, Concurrence, HeadDelegation, Notification, Position,
    PositionAssignment, Proposal, SystemEvent,
)
from api.views import issue_reauth_token

from .tests_generation import PackageFixture, all_text


class DelegationFixture(PackageFixture):

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.vpaf_head = self.person('vpaf_head', self.vpaf, Position.HEAD)
        self.budget_head_post = PositionAssignment.objects.get(
            user=self.bud_head, position__office=self.budget, position__kind=Position.HEAD)

    def delegate(self, office, to, by=None, starts=0, days=7, token=True, **extra):
        by = by or {self.budget: self.bud_head, self.accounting: self.acc_head}[office]
        body = {'delegate_id': to.pk if to else None,
                'starts_on': (self.today + datetime.timedelta(days=starts)).isoformat(),
                'ends_on': (self.today + datetime.timedelta(days=starts + days)).isoformat(),
                'reason': 'Annual leave', **extra}
        headers = {'HTTP_X_REAUTH_TOKEN': self.token(by)} if token else {}
        return self.as_(by).post(f'/api/offices/{office.pk}/delegations/', body,
                                 format='json', **headers)

    def submitted(self):
        """A proposal from Accounting, out for concurrence."""
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        return proposal_id

    def shift(self, days):
        """Move every delegation by `days`, as if that many days had passed."""
        for d in HeadDelegation.objects.all():
            HeadDelegation.objects.filter(pk=d.pk).update(
                starts_on=d.starts_on - datetime.timedelta(days=days),
                ends_on=d.ends_on - datetime.timedelta(days=days))


class MakingOne(DelegationFixture):

    def test_the_head_names_a_post_holder_with_the_password(self):
        response = self.delegate(self.budget, self.bud_enc)
        self.assertEqual(response.status_code, 201, response.data)
        made = HeadDelegation.objects.get()
        self.assertEqual((made.delegate, made.head_assignment, made.created_by),
                         (self.bud_enc, self.budget_head_post, self.bud_head))
        self.assertTrue(SystemEvent.objects.filter(kind=SystemEvent.DELEGATION_STARTED,
                                                   office=self.budget).exists())
        notice = Notification.objects.get(recipient=self.bud_enc, kind=Notification.DELEGATED)
        self.assertIn('Budget Office — Head', notice.title)

    def test_the_head_above_may_be_named_and_the_admin_may_name(self):
        from api.models import CustomUser
        admin = CustomUser.objects.create_user(username='admin', password='pw', is_approved=True,
                                               role='admin', system_role=CustomUser.SYSTEM_ADMIN)
        response = self.delegate(self.budget, self.vpaf_head, by=admin)
        self.assertEqual(response.status_code, 201, response.data)

    def test_refusals_name_the_reason(self):
        cases = [
            (dict(to=self.cmo_head), 'not_eligible'),                    # another office
            (dict(to=self.bud_head), 'invalid_delegate'),                # the Head themselves
            (dict(to=self.bud_enc, starts=-1), 'invalid_dates'),         # backdated
            (dict(to=self.bud_enc, days=-2), 'invalid_dates'),           # ends before it starts
            (dict(to=self.bud_enc, reason=''), 'reason_required'),
            (dict(to=self.bud_enc, token=False), 'reauth_required'),
            (dict(to=self.bud_enc, by=self.bud_enc), 'not_head'),        # an Encoder
        ]
        for kwargs, reason in cases:
            response = self.delegate(self.budget, **kwargs)
            self.assertEqual(response.data['reason'], reason, kwargs)
        self.assertFalse(HeadDelegation.objects.exists())

    def test_no_two_periods_overlap(self):
        self.delegate(self.budget, self.bud_enc, starts=0, days=7)
        response = self.delegate(self.budget, self.vpaf_head, starts=5, days=3)
        self.assertEqual((response.status_code, response.data['reason']), (409, 'delegation_overlaps'))
        self.assertEqual(self.delegate(self.budget, self.vpaf_head, starts=8, days=3).status_code, 201)

    def test_a_delegate_cannot_delegate_further(self):
        self.delegate(self.budget, self.bud_enc)
        response = self.delegate(self.budget, self.vpaf_head, by=self.bud_enc, starts=10)
        self.assertEqual(response.data['reason'], 'not_head')


class ActingInsideThePeriod(DelegationFixture):

    def concur(self, user, proposal_id):
        return self.decide(proposal_id, user, Concurrence.CONCUR)

    def test_before_during_and_after(self):
        proposal_id = self.submitted()
        self.delegate(self.budget, self.vpaf_head, starts=1, days=3)
        self.assertEqual(self.concur(self.vpaf_head, proposal_id).data['reason'],
                         'not_participating')                       # tomorrow, not yet
        self.shift(1)                                                # it starts today
        response = self.concur(self.vpaf_head, proposal_id)
        self.assertEqual(response.status_code, 200, response.data)

    def test_after_the_end_date_the_head_alone(self):
        self.delegate(self.budget, self.bud_enc, starts=0, days=1)
        self.shift(2)                                                # ended yesterday
        response = self.concur(self.bud_enc, self.submitted())
        self.assertEqual(response.data['reason'], 'not_head')

    def test_ending_early_restores_the_head_at_once(self):
        self.delegate(self.budget, self.bud_enc)
        made = HeadDelegation.objects.get()
        response = self.as_(self.bud_head).post(f'/api/delegations/{made.pk}/end/', {},
                                                format='json',
                                                HTTP_X_REAUTH_TOKEN=self.token(self.bud_head))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'ended')
        self.assertEqual(self.concur(self.bud_enc, self.submitted()).data['reason'], 'not_head')
        self.assertTrue(SystemEvent.objects.filter(kind=SystemEvent.DELEGATION_ENDED).exists())
        again = self.as_(self.bud_head).post(f'/api/delegations/{made.pk}/end/', {},
                                             format='json',
                                             HTTP_X_REAUTH_TOKEN=self.token(self.bud_head))
        self.assertEqual(again.data['reason'], 'already_ended')

    def test_the_step_is_the_delegates_acting_for_the_head(self):
        self.delegate(self.budget, self.vpaf_head)
        proposal_id = self.submitted()
        self.concur(self.vpaf_head, proposal_id)
        event = AuditEvent.objects.get(proposal_id=proposal_id, event=AuditEvent.CONCURRED)
        self.assertEqual((event.actor, event.acting_for, event.position.kind),
                         (self.vpaf_head, self.bud_head, Position.HEAD))
        shown = [e for e in self.as_(self.acc_head).get(
            f'/api/proposals/{proposal_id}/full/').data['events'] if e['event'] == 'concurred']
        self.assertEqual(shown[0]['by']['position'], 'Budget Office — Head (delegated)')

    def test_the_heads_own_steps_carry_nothing(self):
        proposal_id = self.submitted()
        self.concur(self.bud_head, proposal_id)
        self.assertFalse(AuditEvent.objects.filter(acting_for__isnull=False).exists())

    def test_notices_go_to_the_delegate_instead(self):
        self.delegate(self.budget, self.vpaf_head)
        proposal_id = self.submitted()
        asked = Notification.objects.filter(proposal_id=proposal_id,
                                            kind=Notification.CONCURRENCE_REQUESTED,
                                            addressed_office=self.budget, severity='action')
        self.assertEqual([n.recipient for n in asked], [self.vpaf_head])
        self.assertEqual(asked[0].addressed_position_title, 'Budget Office — Head (delegated)')
        self.assertFalse(asked.filter(recipient=self.bud_head).exists())

    def test_the_forms_print_titles_never_the_delegates_name(self):
        self.vpaf_head.first_name, self.vpaf_head.last_name = 'Corazon', 'Mabini'
        self.vpaf_head.save(update_fields=['first_name', 'last_name'])
        self.delegate(self.budget, self.vpaf_head)
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.decide(proposal_id, self.vpaf_head, Concurrence.CONCUR)     # for Budget
        self.decide(proposal_id, self.cmo_head, Concurrence.CONCUR)
        proposal = Proposal.objects.get(pk=proposal_id)
        self.assertEqual(proposal.status, Proposal.AWAITING_SIGNATURE)
        for attachment in proposal.attachments.filter(superseded_at__isnull=True):
            text = all_text(attachment)
            for name in self.names + ['Corazon', 'Mabini', 'vpaf_head']:
                self.assertNotIn(name, text, (attachment.kind, name))

    def test_a_delegated_review_is_logged_as_such(self):
        self.delegate(self.budget, self.bud_enc)
        response = self.as_(self.bud_enc).post(
            f'/api/manuals/{self.manual.pk}/reviewed-no-change/', {}, format='json',
            HTTP_X_REAUTH_TOKEN=self.token(self.bud_enc))
        self.assertEqual(response.status_code, 200, response.data)
        event = SystemEvent.objects.get(kind=SystemEvent.REVIEWED_NO_CHANGE)
        self.assertEqual(event.detail['acting_for'], self.bud_head.pk)

    def test_the_heads_own_review_has_no_acting_for(self):
        self.as_(self.bud_head).post(f'/api/manuals/{self.manual.pk}/reviewed-no-change/', {},
                                     format='json', HTTP_X_REAUTH_TOKEN=self.token(self.bud_head))
        self.assertNotIn('acting_for', SystemEvent.objects.get(
            kind=SystemEvent.REVIEWED_NO_CHANGE).detail)


class MakerChecker(DelegationFixture):

    def test_a_delegate_who_drafted_it_may_not_submit_it(self):
        self.delegate(self.accounting, self.acc_enc)
        proposal_id = self.a_draft()                     # drafted by acc_enc
        response = self.as_(self.acc_enc).post(f'/api/proposals/{proposal_id}/submit/', {},
                                               format='json',
                                               HTTP_X_REAUTH_TOKEN=self.token(self.acc_enc))
        self.assertEqual((response.status_code, response.data['reason']), (403, 'maker_checker'))
        self.assertEqual(Proposal.objects.get(pk=proposal_id).status, Proposal.DRAFT)

    def test_a_delegate_who_sent_it_to_the_head_may_not_return_it(self):
        other = self.person('acc_enc2', self.accounting, Position.ENCODER)
        proposal_id = self.a_draft()                     # drafted by acc_enc
        self.send_to_head(proposal_id, self.acc_enc)
        self.delegate(self.accounting, self.acc_enc)
        response = self.as_(self.acc_enc).post(f'/api/proposals/{proposal_id}/return-to-encoder/',
                                               {'note': 'Fix it.'}, format='json')
        self.assertEqual(response.data['reason'], 'maker_checker')
        # Another post holder, as delegate, may.
        HeadDelegation.objects.update(ended_at=timezone.now())
        self.delegate(self.accounting, other, starts=0, days=3)
        HeadDelegation.objects.filter(delegate=other).update(starts_on=self.today)
        self.assertNotEqual(self.as_(other).post(f'/api/proposals/{proposal_id}/return-to-encoder/',
                                                 {'note': 'Fix it.'}, format='json').data.get('reason'),
                            'maker_checker')

    def test_a_delegate_who_drafted_it_may_not_concur_on_it(self):
        proposal_id = self.submitted()                   # drafted by acc_enc
        # The Accounting Encoder also works in Budget, and acts for its Head.
        position, _ = Position.objects.get_or_create(office=self.budget, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=self.acc_enc, position=position, starts_on=self.today)
        self.delegate(self.budget, self.acc_enc)
        response = self.decide(proposal_id, self.acc_enc, Concurrence.CONCUR)
        self.assertEqual(response.data['reason'], 'maker_checker')

    def test_the_head_themselves_is_not_bound(self):
        proposal_id = self.a_draft()
        self.assertEqual(self.submit(proposal_id).status_code, 200)


class TheScreens(DelegationFixture):

    def test_my_account_offers_delegating_only_where_one_heads_in_ones_own_post(self):
        self.delegate(self.budget, self.vpaf_head)
        me = self.as_(self.vpaf_head).get('/api/auth/me/').data
        self.assertEqual([h['office'] for h in me['heads']],
                         ['VP for Administration and Finance'])
        self.assertIn('Budget Office — Head (delegated)', me['positions'])
        self.assertEqual([h['office'] for h in self.as_(self.bud_head).get('/api/auth/me/').data['heads']],
                         ['Budget Office'])

    def test_the_admins_people_screen_shows_the_office_away(self):
        from api.models import CustomUser
        admin = CustomUser.objects.create_user(username='admin', password='pw', is_approved=True,
                                               role='admin', system_role=CustomUser.SYSTEM_ADMIN)
        self.delegate(self.budget, self.bud_enc)
        offices = {o['office']: o for o in self.as_(admin).get('/api/org/positions/').data['offices']}
        row = offices['Budget Office']['delegations'][0]
        self.assertEqual((row['delegate'], row['current']), ('bud_enc', True))
        self.assertEqual(offices['Accounting Office']['delegations'], [])

    def test_the_list_offers_who_may_be_named(self):
        data = self.as_(self.bud_head).get(f'/api/offices/{self.budget.pk}/delegations/').data
        self.assertEqual({c['name'] for c in data['candidates']}, {'bud_enc', 'vpaf_head'})
