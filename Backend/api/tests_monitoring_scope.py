"""v4.2 Phase 4, step 2: who may monitor what, and the live counts.

The rules with teeth:

- **Scope.** A Head (or a delegate while the delegation runs) sees the
  office and everything beneath it, never a sibling, a parent or a branch
  beside it. An Encoder sees their own office only. The admin and QMS see
  everything; no post, nothing. Every endpoint refuses an office outside
  scope (`out_of_scope`) and never lists one.
- **Stalled is live**: from when a request entered its stage against the
  stall limits, whether or not `run_monitoring` has ever run.
- **Overdue** is open deadline obligations past their due date; owed,
  unmet and overdue roll up the office tree, most overdue first.
- `seed_demo_org --add-monitors` adds the four monitor-only Heads once,
  refuses a Head post already held, and those Heads cannot propose.

Tests that expect an error assert the reason.
"""

import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api import access
from api.models import (
    AuditEvent, CustomUser, Deadline, DeadlineObligation, DeadlineType, HeadDelegation, Manual,
    ManualSeries, ManualSeriesOffice, Notification, Office, OfficeLink, Position,
    PositionAssignment, Proposal,
)


class TreeFixture(TestCase):
    """OP > VPAF > {CAO-A > {HRMO, QMS}, CAO-F > {ACC, BUD, CMO}}; OP > VPSD > GUI."""

    def setUp(self):
        self.today = timezone.localdate()
        o = {}

        def office(abbr, parent=None, approving=False):
            o[abbr] = Office.objects.create(name=f'{abbr} Office', abbreviation=abbr,
                                            parent=o.get(parent), is_approving_level=approving)

        office('OP', approving=True)
        office('VPAF', 'OP', True)
        office('CAO-A', 'VPAF')
        office('HRMO', 'CAO-A')
        office('QMS', 'CAO-A')
        office('CAO-F', 'VPAF')
        for abbr in ('ACC', 'BUD', 'CMO'):
            office(abbr, 'CAO-F')
        office('VPSD', 'OP', True)
        office('GUI', 'VPSD')
        self.o = o
        self.series = ManualSeries.objects.create(code='FAM', title='Finance', owning_office=o['VPAF'])
        for abbr in ('ACC', 'BUD', 'CMO'):
            ManualSeriesOffice.objects.create(series=self.series, office=o[abbr],
                                              relationship=OfficeLink.CONCURRING)
        self.manual = Manual.objects.create(title='FAM 6.02', series=self.series)
        self.admin = CustomUser.objects.create_user(
            username='mon_admin', password='pw', role='admin', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN)
        self.imr = self.person('mon_imr', 'QMS', Position.IMR, system_role=CustomUser.QMS_STAFF)
        self.acc_head = self.person('acc_head', 'ACC', Position.HEAD)
        self.acc_enc = self.person('acc_enc', 'ACC', Position.ENCODER)
        self.caof_head = self.person('caof_head', 'CAO-F', Position.HEAD)
        self.caof_enc = self.person('caof_enc', 'CAO-F', Position.ENCODER)
        self.vpaf_head = self.person('vpaf_head', 'VPAF', Position.HEAD)
        self.op_head = self.person('op_head', 'OP', Position.HEAD)

    def person(self, username, abbr, kind, system_role=None):
        user = CustomUser.objects.create_user(username=username, password='pw', is_approved=True,
                                              system_role=system_role or CustomUser.USER)
        position, _ = Position.objects.get_or_create(office=self.o[abbr], kind=kind)
        PositionAssignment.objects.create(user=user, position=position, starts_on=self.today)
        return user

    def ids(self, *abbrs):
        return {self.o[a].pk for a in abbrs}

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client


# --- the scope ------------------------------------------------

class TheScope(TreeFixture):

    def scope(self, user):
        return access.monitoring_scope(user)

    def test_a_head_sees_the_office_and_everything_beneath_it(self):
        self.assertEqual(self.scope(self.acc_head), self.ids('ACC'))
        self.assertEqual(self.scope(self.caof_head), self.ids('CAO-F', 'ACC', 'BUD', 'CMO'))
        self.assertEqual(self.scope(self.vpaf_head),
                         self.ids('VPAF', 'CAO-A', 'HRMO', 'QMS', 'CAO-F', 'ACC', 'BUD', 'CMO'))
        self.assertEqual(self.scope(self.op_head), set(self.ids(*self.o)))

    def test_never_a_sibling_a_parent_or_a_branch_beside_it(self):
        acc = self.scope(self.acc_head)
        self.assertFalse(acc & self.ids('BUD', 'CMO', 'CAO-F', 'VPAF', 'OP', 'CAO-A', 'HRMO'))
        caof = self.scope(self.caof_head)
        self.assertFalse(caof & self.ids('CAO-A', 'HRMO', 'QMS', 'VPAF', 'OP', 'VPSD', 'GUI'))

    def test_an_encoder_sees_their_own_office_only(self):
        self.assertEqual(self.scope(self.acc_enc), self.ids('ACC'))
        self.assertEqual(self.scope(self.caof_enc), self.ids('CAO-F'))

    def test_a_concurrent_head_sees_both_branches_and_nothing_between(self):
        hrmo_head = self.person('hrmo_head', 'HRMO', Position.HEAD)
        PositionAssignment.objects.create(
            user=hrmo_head, starts_on=self.today,
            position=Position.objects.get_or_create(office=self.o['GUI'], kind=Position.HEAD)[0])
        self.assertEqual(self.scope(hrmo_head), self.ids('HRMO', 'GUI'))

    def test_a_delegate_sees_the_branch_only_while_the_delegation_runs(self):
        head_post = PositionAssignment.objects.get(user=self.caof_head)
        made = HeadDelegation.objects.create(
            office=self.o['CAO-F'], head_assignment=head_post, delegate=self.acc_enc,
            starts_on=self.today, ends_on=self.today + datetime.timedelta(days=3),
            reason='Leave', created_by=self.caof_head)
        self.assertEqual(self.scope(self.acc_enc), self.ids('ACC', 'CAO-F', 'BUD', 'CMO'))
        HeadDelegation.objects.filter(pk=made.pk).update(
            starts_on=self.today - datetime.timedelta(days=9),
            ends_on=self.today - datetime.timedelta(days=1))
        self.assertEqual(self.scope(self.acc_enc), self.ids('ACC'))

    def test_admin_and_qms_see_everything_and_no_post_sees_nothing(self):
        self.assertEqual(self.scope(self.admin), access.MONITOR_ALL)
        self.assertEqual(self.scope(self.imr), access.MONITOR_ALL)
        nobody = CustomUser.objects.create_user(username='nobody', password='pw', is_approved=True)
        self.assertEqual(self.scope(nobody), set())


class TheEndpointsKeepToScope(TreeFixture):

    def test_an_office_outside_scope_is_refused(self):
        client = self.as_(self.caof_head)
        for url in (f'/api/monitoring/offices/?parent={self.o["CAO-A"].pk}',
                    f'/api/monitoring/offices/?parent={self.o["VPAF"].pk}',
                    f'/api/monitoring/items/?office={self.o["HRMO"].pk}',
                    f'/api/monitoring/items/?office={self.o["VPAF"].pk}&subtree=1'):
            response = client.get(url)
            self.assertEqual((response.status_code, response.data.get('reason')),
                             (403, 'out_of_scope'), url)
        response = self.as_(self.acc_enc).get(f'/api/monitoring/offices/?parent={self.o["CAO-F"].pk}')
        self.assertEqual(response.data.get('reason'), 'out_of_scope')

    def test_lists_never_include_another_branch(self):
        for abbr in ('ACC', 'HRMO', 'GUI'):
            Proposal.objects.create(manual=self.manual, initiating_office=self.o[abbr],
                                    created_by=self.admin, status=Proposal.CONCURRENCE)
        rows = self.as_(self.caof_head).get('/api/monitoring/items/?bucket=open').data['rows']
        self.assertEqual({r['office'] for r in rows}, {'ACC Office'})
        top = self.as_(self.caof_head).get('/api/monitoring/offices/').data['offices']
        self.assertEqual([r['name'] for r in top], ['CAO-F Office'])
        self.assertEqual(self.as_(self.caof_head).get('/api/monitoring/overview/').data
                         ['counts']['in_concurrence'], 1)
        self.assertEqual(self.as_(self.admin).get('/api/monitoring/overview/').data
                         ['counts']['in_concurrence'], 3)


# --- the counts -----------------------------------------------

class TheCounts(TreeFixture):

    def proposal(self, abbr, status, entered_days_ago, event=AuditEvent.SENT_TO_HEAD):
        # A manual each: one open proposal per manual per office.
        manual = Manual.objects.create(title=f'FAM {Manual.objects.count() + 10}.01', series=self.series)
        p = Proposal.objects.create(manual=manual, initiating_office=self.o[abbr],
                                    created_by=self.admin, status=status)
        e = AuditEvent.objects.create(proposal=p, event=event, actor=self.admin, office=self.o[abbr])
        AuditEvent.objects.filter(pk=e.pk).update(
            at=timezone.now() - datetime.timedelta(days=entered_days_ago))
        return p

    def obligation(self, abbr, due_in, state=DeadlineObligation.OPEN):
        dtype = DeadlineType.objects.first() or DeadlineType.objects.create(
            name='Audit', created_by=self.admin)
        deadline = Deadline.objects.create(title=f'Audit {abbr} {due_in}', type=dtype,
                                           due_on=self.today + datetime.timedelta(days=due_in),
                                           created_by=self.admin)
        return DeadlineObligation.objects.create(deadline=deadline, office=self.o[abbr], state=state)

    def counts(self, user):
        return self.as_(user).get('/api/monitoring/overview/').data['counts']

    def test_stalled_is_live_without_run_monitoring(self):
        self.proposal('ACC', Proposal.WITH_HEAD, entered_days_ago=4)   # limit 3
        self.proposal('BUD', Proposal.WITH_HEAD, entered_days_ago=1)
        self.assertFalse(Notification.objects.filter(kind=Notification.STALLED).exists())
        counts = self.counts(self.caof_head)
        self.assertEqual((counts['with_head'], counts['stalled']), (2, 1))
        rows = self.as_(self.caof_head).get('/api/monitoring/items/?bucket=stalled').data['rows']
        self.assertEqual([(r['office'], r['stalled'], r['days']) for r in rows],
                         [('ACC Office', True, 4)])

    def test_returned_is_told_from_drafting(self):
        self.proposal('ACC', Proposal.DRAFT, 1, event=AuditEvent.RETURNED_TO_ENCODER)
        self.proposal('ACC', Proposal.DRAFT, 1, event=AuditEvent.CREATED)
        counts = self.counts(self.acc_head)
        self.assertEqual((counts['returned'], counts['drafting']), (1, 1))

    def test_obligations_roll_up_most_overdue_first(self):
        self.obligation('ACC', -3)                                   # overdue
        self.obligation('BUD', -3, DeadlineObligation.SUBMITTED)     # submitted
        self.obligation('BUD', 10)                                   # unmet, not yet due
        self.obligation('HRMO', -5)                                  # overdue, other branch
        self.obligation('HRMO', -6)
        top = self.as_(self.vpaf_head).get('/api/monitoring/offices/').data['offices']
        self.assertEqual(top[0]['counts']['overdue'], 3)
        level = self.as_(self.vpaf_head).get(
            f'/api/monitoring/offices/?parent={self.o["VPAF"].pk}').data['offices']
        self.assertEqual([(r['name'], r['counts']['owed'], r['counts']['unmet'],
                           r['counts']['overdue']) for r in level],
                         [('CAO-A Office', 2, 2, 2), ('CAO-F Office', 3, 2, 1)])
        offices = {r['name']: r for r in self.as_(self.caof_head).get(
            f'/api/monitoring/offices/?parent={self.o["CAO-F"].pk}').data['offices']}
        self.assertEqual((offices['BUD Office']['counts']['owed'],
                          offices['BUD Office']['counts']['unmet']), (2, 1))
        rows = self.as_(self.caof_head).get('/api/monitoring/items/?bucket=overdue').data['rows']
        self.assertEqual([(r['office'], r['days_late']) for r in rows], [('ACC Office', 3)])


# --- the monitor-only demo Heads -----------------------------

class AddMonitors(TestCase):

    def run_command(self, *args):
        out = StringIO()
        call_command('seed_demo_org', *args, stdout=out, stderr=out)
        return out.getvalue()

    def remove(self, *usernames):
        """As if seeded before the monitors existed."""
        PositionAssignment.objects.filter(user__username__in=usernames).delete()
        CustomUser.objects.filter(username__in=usernames).delete()

    def test_added_once_scoped_and_unable_to_propose(self):
        self.run_command()
        self.remove('PRES_Antonio', 'VPAF_Ramil', 'CAOF_Cynthia', 'CAOA_Dante')
        self.assertIn('Added 4 monitor-only Head(s)', self.run_command('--add-monitors'))
        self.assertIn('Nothing to add', self.run_command('--add-monitors'))
        cynthia = CustomUser.objects.get(username='CAOF_Cynthia')
        self.assertTrue(cynthia.check_password('Office123!'))
        names = set(Office.objects.filter(pk__in=access.monitoring_scope(cynthia))
                    .values_list('abbreviation', flat=True))
        self.assertEqual(names, {'CAO-F', 'ACC', 'BUD', 'CMO'})
        manual = Manual.objects.filter(series__code='FAM').first() or Manual.objects.create(
            title='FAM 1.01', series=ManualSeries.objects.get(code='FAM'))
        client = APIClient()
        client.force_authenticate(user=cynthia)
        from api.views import issue_reauth_token
        response = client.post('/api/proposals/', {'manual_id': manual.pk}, format='json',
                               HTTP_X_REAUTH_TOKEN=issue_reauth_token(cynthia))
        self.assertEqual(response.data.get('reason'), 'not_concurring')

    def test_refuses_a_head_post_already_held(self):
        self.run_command()
        self.remove('PRES_Antonio', 'VPAF_Ramil', 'CAOF_Cynthia')
        PositionAssignment.objects.filter(user__username='CAOA_Dante').update(
            user=CustomUser.objects.get(username='HRM_Liza'))
        self.remove('CAOA_Dante')
        output = self.run_command('--add-monitors')
        self.assertIn('Refusing: these Head posts are already held', output)
        self.assertFalse(CustomUser.objects.filter(username='PRES_Antonio').exists())


# --- step 3: the offices chart; step 4: advised revisions -----

class TheChartAndAdvised(TheCounts):

    def chart(self, user, **params):
        return self.as_(user).get('/api/monitoring/offices-chart/', params).data

    def test_pending_is_open_requests_by_office_highest_first(self):
        self.proposal('ACC', Proposal.WITH_HEAD, 1)
        self.proposal('ACC', Proposal.CONCURRENCE, 1)
        self.proposal('BUD', Proposal.DRAFT, 1)
        self.proposal('HRMO', Proposal.WITH_HEAD, 1)              # another branch
        data = self.chart(self.caof_head)
        self.assertEqual([(b['office'], b['value']) for b in data['bars']],
                         [('ACC Office', 2), ('BUD Office', 1)])
        self.assertEqual(data['none'], 2)                          # CAO-F and CMO have none
        self.assertEqual(self.chart(self.admin)['bars'][0]['stages']['in_concurrence'], 1)

    def test_approved_counts_what_was_made_effective_in_the_period(self):
        done = self.proposal('ACC', Proposal.EFFECTIVE, 0, event=AuditEvent.MADE_EFFECTIVE)
        old = self.proposal('BUD', Proposal.EFFECTIVE, 400, event=AuditEvent.MADE_EFFECTIVE)
        this_month = self.chart(self.admin, mode='approved', period='month')['bars']
        self.assertEqual([(b['office'], b['value']) for b in this_month], [('ACC Office', 1)])
        self.assertEqual(self.chart(self.admin, mode='pending')['bars'], [])
        self.assertTrue(done and old)
        response = self.as_(self.admin).get('/api/monitoring/offices-chart/', {'mode': 'x'})
        self.assertEqual(response.data['reason'], 'invalid_filter')

    def test_advised_revisions_say_where_each_office_has_got(self):
        advised = self.obligation('ACC', -2)
        advised.manual = self.manual
        advised.save(update_fields=['manual'])
        other = Manual.objects.create(title='FAM 7.01', series=self.series)
        waiting = self.obligation('BUD', 5)
        waiting.manual = other
        waiting.save(update_fields=['manual'])
        Proposal.objects.create(manual=other, initiating_office=self.o['BUD'],
                                created_by=self.admin, status=Proposal.CONCURRENCE)
        self.obligation('CMO', 5)                                  # office-level: not advised
        self.assertEqual(self.counts(self.caof_head)['advised'], 2)
        rows = self.as_(self.caof_head).get('/api/monitoring/items/?bucket=advised').data['rows']
        self.assertEqual([(r['office'], r['manual'], r['status'], r['days_late']) for r in rows],
                         [('ACC Office', 'FAM 6.02', 'Not started', 2),
                          ('BUD Office', 'FAM 7.01', 'In concurrence', 0)])
        self.assertEqual(self.as_(self.acc_enc).get('/api/monitoring/items/?bucket=advised')
                         .data['count'], 1)


class TheListsKeepTheirShape(TheChartAndAdvised):
    """The bug of 27 Oct 2026: every row naming a manual is given its
    deadline tag under `deadline`, and the advised and obligation rows
    also used `deadline` for the deadline's title - so the screen printed
    an object and went white. Each role opens each lens."""

    def test_every_role_opens_advised_and_the_obligation_lists(self):
        advised = self.obligation('ACC', -2)
        advised.manual = self.manual
        advised.save(update_fields=['manual'])
        self.obligation('ACC', 5)
        for user in (self.admin, self.imr, self.acc_head, self.acc_enc):
            for bucket in ('advised', 'overdue', 'owed', 'unmet'):
                rows = self.as_(user).get(f'/api/monitoring/items/?bucket={bucket}').data['rows']
                self.assertTrue(rows, (user.username, bucket))
                for row in rows:
                    self.assertIsInstance(row['deadline_title'], str, (user.username, bucket))
                    self.assertTrue(row['deadline'] is None or isinstance(row['deadline'], dict))


class TheFlatFilter(TheCounts):
    """By office, flat: Not submitted, Overdue or All, optionally for one
    deadline - and never an office outside scope."""

    def flat(self, user, **params):
        return self.as_(user).get('/api/monitoring/offices/', params).data

    def names(self, data):
        return [r['name'] for r in data['offices']]

    def test_not_submitted_overdue_and_all(self):
        self.obligation('ACC', -3)                                   # overdue
        self.obligation('BUD', 10)                                   # unmet, not due
        self.obligation('CMO', -2, DeadlineObligation.SUBMITTED)     # met
        self.assertEqual(self.names(self.flat(self.caof_head, show='not_submitted')),
                         ['ACC Office', 'BUD Office'])
        self.assertEqual(self.names(self.flat(self.caof_head, show='overdue')), ['ACC Office'])
        self.assertEqual(set(self.names(self.flat(self.caof_head, show='all'))),
                         {'CAO-F Office', 'ACC Office', 'BUD Office', 'CMO Office'})
        self.assertEqual(self.flat(self.caof_head, show='nothing')['reason'], 'invalid_show')

    def test_for_one_deadline(self):
        first = self.obligation('ACC', -3)
        self.obligation('BUD', -4)
        data = self.flat(self.caof_head, show='overdue', deadline=first.deadline_id)
        self.assertEqual(self.names(data), ['ACC Office'])
        self.assertEqual(data['offices'][0]['counts']['overdue'], 1)

    def test_never_outside_scope(self):
        self.obligation('HRMO', -3)
        self.obligation('ACC', -3)
        self.assertEqual(self.names(self.flat(self.caof_head, show='overdue')), ['ACC Office'])
        self.assertNotIn('HRMO Office', self.names(self.flat(self.caof_head, show='all')))
        self.assertEqual(self.names(self.flat(self.acc_enc, show='all')), ['ACC Office'])
        self.assertEqual(set(self.names(self.flat(self.admin, show='overdue'))),
                         {'ACC Office', 'HRMO Office'})
