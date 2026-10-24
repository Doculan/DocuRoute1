"""Deadlines (Phase 3A): targets, obligations, meeting them, the banner.

The rules with teeth:

- **Targets become obligations** exactly as the design says: an office
  (and, if asked, every concurring office beneath it), a series or a manual
  (its concurring offices, by the series/override rule), or everyone.
- **Met** by a submission - any for an office-level obligation, the
  manual's own for a manual-level one - including a proposal already in
  flight when the deadline is set; **withdrawing** the proposal that met
  it reopens it, a **denial** does not.
- **The counts** on the deadline always equal its rows.
- **The action row** sits above the announcement row and has no dismiss
  route.

Tests that expect an error assert the reason.
"""

import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import Resolver404, resolve
from django.utils import timezone
from rest_framework.test import APIClient

from api import deadlines
from api.models import (
    CustomUser, Deadline, DeadlineObligation, DeadlineTarget, DeadlineType,
    Manual, ManualOffice, ManualSeries, ManualSeriesOffice, Notification, Office,
    OfficeLink, Position, PositionAssignment, Proposal, ProposalVersion, SystemEvent,
)

from .tests_concurrence import ConcurrenceFixture


class DeadlineFixture(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        self.vp = Office.objects.create(name='VP Office', abbreviation='VP',
                                        is_approving_level=True)
        self.acc = Office.objects.create(name='Accounting Office', abbreviation='ACC', parent=self.vp)
        self.cash = Office.objects.create(name='Cash Unit', abbreviation='CU', parent=self.acc)
        self.bud = Office.objects.create(name='Budget Office', abbreviation='BUD', parent=self.vp)
        self.reg = Office.objects.create(name='Registry', abbreviation='REG', parent=self.vp)
        self.fam = ManualSeries.objects.create(code='FAM', title='Finance', owning_office=self.vp)
        for office in (self.acc, self.cash, self.bud):
            ManualSeriesOffice.objects.create(series=self.fam, office=office,
                                              relationship=OfficeLink.CONCURRING)
        ManualSeriesOffice.objects.create(series=self.fam, office=self.reg,
                                          relationship=OfficeLink.READER)
        self.m1 = Manual.objects.create(title='FAM 1', series=self.fam)
        self.m2 = Manual.objects.create(title='FAM 2', series=self.fam)
        # Overrides its series: only Budget concurs on it.
        self.m9 = Manual.objects.create(title='FAM 9', series=self.fam, offices_overridden=True)
        ManualOffice.objects.create(manual=self.m9, office=self.bud,
                                    relationship=OfficeLink.CONCURRING)
        self.admin = CustomUser.objects.create_user(
            username='admin', password='pw', role='admin', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN)
        self.acc_head = self.person('acc_head', self.acc, Position.HEAD)
        self.acc_enc = self.person('acc_enc', self.acc, Position.ENCODER)
        self.bud_head = self.person('bud_head', self.bud, Position.HEAD)
        self.cash_head = self.person('cash_head', self.cash, Position.HEAD)
        self.dtype = DeadlineType.objects.get(name='Internal quality audit')

    def person(self, username, office, kind):
        user = CustomUser.objects.create_user(username=username, password='pw', is_approved=True)
        position, _ = Position.objects.get_or_create(office=office, kind=kind)
        PositionAssignment.objects.create(user=user, position=position, starts_on=self.today)
        return user

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def deadline(self, *targets, days=20, active=True):
        deadline = Deadline.objects.create(
            title='ISO surveillance audit', type=self.dtype, active=active,
            due_on=self.today + datetime.timedelta(days=days), created_by=self.admin)
        for target in targets:
            target.deadline = deadline
            target.save()
        deadlines.materialise(deadline, self.admin)
        deadline.refresh_from_db()
        return deadline

    def pairs(self, deadline):
        return {(ob.office.abbreviation, ob.manual.title if ob.manual_id else None)
                for ob in deadline.obligations.select_related('office', 'manual')}

    def proposal(self, office, manual, status=Proposal.CONCURRENCE):
        proposal = Proposal.objects.create(manual=manual, initiating_office=office,
                                           status=status, created_by=self.acc_enc)
        ProposalVersion.objects.create(proposal=proposal, number=1)
        return proposal


class TargetsBecomeObligations(DeadlineFixture):

    def test_an_office_is_one_office_level_obligation(self):
        deadline = self.deadline(DeadlineTarget(kind='office', office=self.acc))
        self.assertEqual(self.pairs(deadline), {('ACC', None)})

    def test_everything_beneath_adds_the_concurring_offices_below(self):
        deadline = self.deadline(DeadlineTarget(kind='office', office=self.vp,
                                                include_descendants=True))
        # The VP itself (targeted by name), and below it every office that
        # concurs on a document - not the Registry, a reader only.
        self.assertEqual(self.pairs(deadline),
                         {('VP', None), ('ACC', None), ('CU', None), ('BUD', None)})

    def test_a_series_is_each_document_by_its_own_concurring_offices(self):
        deadline = self.deadline(DeadlineTarget(kind='series', series=self.fam))
        self.assertEqual(self.pairs(deadline), {
            ('ACC', 'FAM 1'), ('CU', 'FAM 1'), ('BUD', 'FAM 1'),
            ('ACC', 'FAM 2'), ('CU', 'FAM 2'), ('BUD', 'FAM 2'),
            ('BUD', 'FAM 9'),                       # its override, not the series
        })

    def test_a_manual_is_its_concurring_offices(self):
        deadline = self.deadline(DeadlineTarget(kind='manual', manual=self.m9))
        self.assertEqual(self.pairs(deadline), {('BUD', 'FAM 9')})

    def test_all_is_every_office_that_concurs_on_a_document(self):
        deadline = self.deadline(DeadlineTarget(kind='all'))
        self.assertEqual(self.pairs(deadline), {('ACC', None), ('CU', None), ('BUD', None)})

    def test_the_counts_are_the_rows(self):
        deadline = self.deadline(DeadlineTarget(kind='series', series=self.fam))
        self.assertEqual((deadline.obligations_total, deadline.obligations_open,
                          deadline.obligations_met), (7, 7, 0))

    def test_a_proposal_in_flight_meets_it_at_creation(self):
        in_flight = self.proposal(self.acc, self.m1)
        deadline = self.deadline(DeadlineTarget(kind='manual', manual=self.m1),
                                 DeadlineTarget(kind='office', office=self.bud))
        self.proposal(self.bud, self.m2, status=Proposal.AWAITING_SIGNATURE)
        met = deadline.obligations.get(office=self.acc, manual=self.m1)
        self.assertEqual((met.state, met.met_by_proposal), (DeadlineObligation.SUBMITTED, in_flight))
        # A draft is not in flight; and Budget's own proposal came after.
        self.assertEqual(deadline.obligations.get(office=self.bud, manual__isnull=True).state,
                         DeadlineObligation.OPEN)

    def test_changing_targets_drops_open_rows_and_keeps_met_ones(self):
        self.proposal(self.acc, self.m1)
        deadline = self.deadline(DeadlineTarget(kind='series', series=self.fam))
        deadline.targets.all().delete()
        DeadlineTarget.objects.create(deadline=deadline, kind='manual', manual=self.m2)
        deadlines.materialise(deadline, self.admin)
        self.assertEqual(self.pairs(deadline), {('ACC', 'FAM 1'),       # met, kept
                                                ('ACC', 'FAM 2'), ('CU', 'FAM 2'),
                                                ('BUD', 'FAM 2')})


class MeetingThem(DeadlineFixture):

    def test_submitting_meets_the_manuals_and_the_office_level_obligation(self):
        deadline = self.deadline(DeadlineTarget(kind='series', series=self.fam),
                                 DeadlineTarget(kind='office', office=self.acc))
        proposal = self.proposal(self.acc, self.m1)

        deadlines.on_submitted(proposal, self.acc_head)

        met = set(deadline.obligations.exclude(state='open')
                  .values_list('office__abbreviation', 'manual__title'))
        self.assertEqual(met, {('ACC', 'FAM 1'), ('ACC', None)})
        deadline.refresh_from_db()
        self.assertEqual((deadline.obligations_open, deadline.obligations_met), (6, 2))
        logged = SystemEvent.objects.get(kind=SystemEvent.OBLIGATION_MET)
        self.assertEqual(logged.proposal, proposal)

    def test_an_inactive_deadline_is_not_met(self):
        deadline = self.deadline(DeadlineTarget(kind='office', office=self.acc), active=False)
        deadlines.on_submitted(self.proposal(self.acc, self.m1), self.acc_head)
        self.assertEqual(deadline.obligations.get().state, DeadlineObligation.OPEN)

    def test_withdrawing_passes_it_to_another_proposal_in_flight(self):
        deadline = self.deadline(DeadlineTarget(kind='office', office=self.acc))
        first = self.proposal(self.acc, self.m1)
        deadlines.on_submitted(first, self.acc_head)
        second = self.proposal(self.acc, self.m2)
        Proposal.objects.filter(pk=first.pk).update(status=Proposal.WITHDRAWN)

        self.assertEqual(deadlines.on_withdrawn(first, self.acc_head), [])

        self.assertEqual(deadline.obligations.get().met_by_proposal, second)

    def test_made_effective_is_the_document_milestone(self):
        deadline = self.deadline(DeadlineTarget(kind='manual', manual=self.m1))
        proposal = self.proposal(self.acc, self.m1)
        deadlines.on_submitted(proposal, self.acc_head)
        deadlines.on_effective(proposal)
        row = deadline.obligations.get(office=self.acc)
        self.assertEqual(row.state, DeadlineObligation.EFFECTIVE)
        self.assertIsNotNone(row.effective_at)

    def test_meeting_it_clears_the_offices_notice_and_only_theirs(self):
        self.deadline(DeadlineTarget(kind='office', office=self.acc),
                      DeadlineTarget(kind='office', office=self.bud))
        deadlines.on_submitted(self.proposal(self.acc, self.m1), self.acc_head)
        acc = Notification.objects.get(recipient=self.acc_enc, kind=Notification.DEADLINE_SET)
        bud = Notification.objects.get(recipient=self.bud_head, kind=Notification.DEADLINE_SET)
        self.assertEqual(acc.acted_by, self.acc_head)
        self.assertIsNone(bud.acted_at)


class TheDeadlineNotice(DeadlineFixture):

    def test_each_owing_office_is_told_in_one_batch(self):
        deadline = self.deadline(DeadlineTarget(kind='series', series=self.fam),
                                 DeadlineTarget(kind='office', office=self.cash))
        acc = Notification.objects.get(recipient=self.acc_head, kind=Notification.DEADLINE_SET)
        self.assertEqual(acc.severity, 'action')
        self.assertEqual(acc.title, f'ISO surveillance audit — due {deadline.due_on:%d %b %Y}')
        self.assertEqual(acc.body, 'Owed: FAM 1, FAM 2')
        self.assertTrue(acc.office_level)                # two manuals: about the office
        self.assertEqual((acc.target_type, acc.target_id), ('deadline', deadline.pk))
        bud = Notification.objects.get(recipient=self.bud_head)
        self.assertEqual(bud.body, 'Owed: FAM 1, FAM 2, FAM 9')
        cash = Notification.objects.get(recipient=self.cash_head)
        self.assertEqual(cash.body, 'Owed: FAM 1, FAM 2')  # the series, and its own office row
        self.assertEqual(SystemEvent.objects.filter(kind=SystemEvent.NOTIFIED).count(), 1)

    def test_one_manual_owed_names_its_manual(self):
        self.deadline(DeadlineTarget(kind='manual', manual=self.m9))
        notice = Notification.objects.get(recipient=self.bud_head)
        self.assertEqual((notice.manual, notice.office_level), (self.m9, False))

    def test_an_office_level_one_says_any_proposal_counts(self):
        self.deadline(DeadlineTarget(kind='office', office=self.bud))
        self.assertEqual(Notification.objects.get(recipient=self.bud_head).body,
                         'Any proposal your office submits will count.')


class TheAdminScreens(DeadlineFixture):

    def post(self, **body):
        body.setdefault('title', 'ISO surveillance audit')
        body.setdefault('type_id', self.dtype.pk)
        body.setdefault('due_on', (self.today + datetime.timedelta(days=20)).isoformat())
        body.setdefault('targets', [{'kind': 'office', 'office_id': self.acc.pk}])
        return self.as_(self.admin).post('/api/admin/deadlines/', body, format='json')

    def test_a_preview_saves_nothing_and_says_who_will_be_told(self):
        response = self.post(preview=True, targets=[{'kind': 'office', 'office_id': self.vp.pk,
                                                     'include_descendants': True}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data['offices'], response.data['people']), (4, 4))
        self.assertIn('No manuals named: any proposal this office submits will count.',
                      response.data['warnings'])
        self.assertFalse(Deadline.objects.exists())

    def test_saving_materialises_and_reports_the_counts(self):
        response = self.post(targets=[{'kind': 'series', 'series_id': self.fam.pk}])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['unmet'], '7 of 7 not yet met')

    def test_a_new_type_is_saved_and_offered_next_time(self):
        response = self.post(new_type='Board of Regents review')
        self.assertEqual(response.status_code, 201, response.data)
        names = [t['name'] for t in self.as_(self.acc_head).get('/api/deadline-types/').data['types']]
        self.assertIn('Board of Regents review', names)
        again = self.post(new_type='board of regents REVIEW')
        self.assertEqual((again.status_code, again.data['reason']), (400, 'type_exists'))

    def test_bad_input_is_refused_with_the_reason(self):
        yesterday = (self.today - datetime.timedelta(days=1)).isoformat()
        for body, reason in (({'targets': []}, 'no_targets'),
                             ({'targets': [{'kind': 'office', 'office_id': 999}]}, 'invalid_target'),
                             ({'targets': [{'kind': 'wing'}]}, 'invalid_target'),
                             ({'due_on': yesterday}, 'due_in_past'),
                             ({'type_id': 99999}, 'invalid_type'),
                             ({'reminder_days': [7, 0]}, 'invalid_reminders'),
                             ({'title': ' '}, 'title_required')):
            with self.subTest(reason=reason):
                response = self.post(**body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['reason'], reason)
        self.assertFalse(Deadline.objects.exists())

    def test_the_list_opens_on_counts(self):
        self.deadline(DeadlineTarget(kind='office', office=self.acc), days=5)
        self.deadline(DeadlineTarget(kind='office', office=self.bud), days=60)
        overdue = self.deadline(DeadlineTarget(kind='office', office=self.cash), days=10)
        Deadline.objects.filter(pk=overdue.pk).update(due_on=self.today - datetime.timedelta(days=2))
        summary = self.as_(self.admin).get('/api/admin/deadlines/').data['summary']
        self.assertEqual(summary, {'open': 2, 'due_soon': 1, 'overdue': 1})

    def test_obligations_page_by_branch_and_show_what_met_them(self):
        proposal = self.proposal(self.acc, self.m1)
        deadline = self.deadline(DeadlineTarget(kind='series', series=self.fam))
        data = self.as_(self.admin).get(f'/api/admin/deadlines/{deadline.pk}/obligations/',
                                        {'state': 'met'}).data
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['obligations'][0]['met_by']['proposal_id'], proposal.pk)
        branch = self.as_(self.admin).get(f'/api/admin/deadlines/{deadline.pk}/obligations/',
                                          {'branch': self.acc.pk}).data
        self.assertEqual({o['office'] for o in branch['obligations']},
                         {'Accounting Office', 'Cash Unit'})

    def test_staff_cannot_set_deadlines(self):
        response = self.as_(self.acc_head).post('/api/admin/deadlines/', {}, format='json')
        self.assertEqual(response.status_code, 403)


class TheActionRow(DeadlineFixture):

    def banner(self, user):
        return self.as_(user).get('/api/action-banner/').data

    def test_most_urgent_first_and_the_row_takes_its_colour(self):
        later = self.deadline(DeadlineTarget(kind='office', office=self.acc), days=60)
        soon = self.deadline(DeadlineTarget(kind='office', office=self.acc), days=3)
        overdue = self.deadline(DeadlineTarget(kind='office', office=self.acc), days=9)
        Deadline.objects.filter(pk=overdue.pk).update(due_on=self.today - datetime.timedelta(days=1))
        today = self.deadline(DeadlineTarget(kind='office', office=self.acc), days=9)
        Deadline.objects.filter(pk=today.pk).update(due_on=self.today)

        data = self.banner(self.acc_enc)

        self.assertEqual([i['deadline_id'] for i in data['deadlines']['items']],
                         [overdue.pk, today.pk, soon.pk, later.pk])
        self.assertEqual([i['urgency'] for i in data['deadlines']['items']],
                         ['overdue', 'today', 'soon', 'later'])
        self.assertEqual(data['urgency'], 'overdue')

    def test_it_clears_for_the_office_that_meets_it_and_no_other(self):
        self.deadline(DeadlineTarget(kind='office', office=self.acc),
                      DeadlineTarget(kind='office', office=self.bud), days=5)
        deadlines.on_submitted(self.proposal(self.acc, self.m1), self.acc_head)
        self.assertEqual(self.banner(self.acc_head)['deadlines']['total'], 0)
        self.assertEqual(self.banner(self.bud_head)['deadlines']['total'], 1)

    def test_the_action_row_has_no_dismiss_route(self):
        with self.assertRaises(Resolver404):
            resolve('/api/action-banner/dismiss/')
        self.assertEqual(self.as_(self.acc_head).post('/api/action-banner/').status_code, 405)

    def test_the_action_row_renders_above_the_announcement_row(self):
        """In every portal shell the pinned action row comes first."""
        shells = Path(settings.BASE_DIR).parent / 'frontend' / 'src' / 'components'
        for shell in ('staff/StaffDashboard.jsx', 'admin/AdminDashboard.jsx',
                      'qms/QmsDashboard.jsx'):
            with self.subTest(shell=shell):
                source = (shells / shell).read_text(encoding='utf-8')
                self.assertIn('<ActionBanner', source)
                self.assertIn('<AnnouncementBanner', source)
                self.assertLess(source.index('<ActionBanner'), source.index('<AnnouncementBanner'))

    def test_my_deadlines_lists_what_the_office_owes(self):
        self.deadline(DeadlineTarget(kind='series', series=self.fam))
        rows = self.as_(self.acc_enc).get('/api/my-deadlines/').data['deadlines']
        self.assertEqual(len(rows), 1)
        self.assertEqual([m['title'] for m in rows[0]['manuals']], ['FAM 1', 'FAM 2'])


class WithdrawingAndDenying(ConcurrenceFixture):
    """Through the real screens: submit, withdraw, deny."""

    def setUp(self):
        super().setUp()
        self.deadline = Deadline.objects.create(
            title='Audit', type=DeadlineType.objects.get(name='Internal quality audit'),
            due_on=timezone.localdate() + datetime.timedelta(days=20), created_by=self.acc_head)
        DeadlineTarget.objects.create(deadline=self.deadline, kind='manual', manual=self.manual)
        deadlines.materialise(self.deadline, self.acc_head)
        self.row = self.deadline.obligations.get(office=self.accounting)

    def test_submitting_meets_it_and_withdrawing_reopens_it(self):
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        self.row.refresh_from_db()
        self.assertEqual((self.row.state, self.row.met_by_proposal_id),
                         (DeadlineObligation.SUBMITTED, proposal_id))

        self.as_(self.acc_head).post(f'/api/proposals/{proposal_id}/withdraw/',
                                     {'reason': 'Superseded.'}, format='json',
                                     HTTP_X_REAUTH_TOKEN=self.token(self.acc_head))

        self.row.refresh_from_db()
        self.assertEqual((self.row.state, self.row.met_by_proposal), (DeadlineObligation.OPEN, None))
        self.assertTrue(SystemEvent.objects.filter(kind=SystemEvent.OBLIGATION_REOPENED).exists())

    def test_a_denial_does_not_reopen_it(self):
        qms = Office.objects.create(name='Quality Management Office')
        imr = self.person('imr', qms, Position.IMR)
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        Proposal.objects.filter(pk=proposal_id).update(status=Proposal.READY_FOR_IMR)

        response = self.as_(imr).post(f'/api/proposals/{proposal_id}/imr/',
                                      {'decision': 'deny', 'comments': 'Out of scope.'},
                                      format='json', HTTP_X_REAUTH_TOKEN=self.token(imr))

        self.assertEqual(response.status_code, 200, response.data)
        self.row.refresh_from_db()
        self.assertEqual(self.row.state, DeadlineObligation.SUBMITTED)


class Migration0046(TransactionTestCase):
    """The three live announcements, and one aimed at an office."""

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(target)
        return executor.loader.project_state(target).apps

    def tearDown(self):
        self.migrate([('api', '0046_announcements_and_deadlines')])

    def test_dated_items_expire_undated_stay_the_banner_targets_are_kept(self):
        old = self.migrate([('api', '0045_encoder_to_head_step')])
        Office = old.get_model('api', 'Office')
        Announcement = old.get_model('api', 'Announcement')
        finance = Office.objects.create(name='Finance')
        Announcement.objects.create(title='Internal quality audit', date=datetime.date(2026, 9, 26))
        Announcement.objects.create(title='New revision workflow is live')
        Announcement.objects.create(title='Finance only', office=finance)

        new = self.migrate([('api', '0046_announcements_and_deadlines')])

        rows = {a.title: a for a in new.get_model('api', 'Announcement').objects.all()}
        self.assertEqual((rows['Internal quality audit'].audience,
                          rows['Internal quality audit'].expires_on),
                         ('all', datetime.date(2026, 9, 26)))
        self.assertEqual((rows['New revision workflow is live'].audience,
                          rows['New revision workflow is live'].expires_on), ('all', None))
        self.assertEqual(rows['Finance only'].audience, 'offices')
        target = new.get_model('api', 'AnnouncementOffice').objects.get()
        self.assertEqual(target.office_id, finance.pk)
        self.assertEqual(new.get_model('api', 'DeadlineType').objects.filter(is_preset=True).count(), 11)
        self.assertEqual(new.get_model('api', 'Deadline').objects.count(), 0)


class ApprovingOfficesAreTold(ConcurrenceFixture):
    """Q-B: a denial and made effective reach the approving route too."""

    def test_the_owner_vp_hears_of_a_denial(self):
        vp_head = self.person('vp_head', self.vpaf, Position.HEAD)
        qms = Office.objects.create(name='Quality Management Office')
        imr = self.person('imr', qms, Position.IMR)
        proposal_id = self.a_draft()
        self.submit(proposal_id)
        Proposal.objects.filter(pk=proposal_id).update(status=Proposal.READY_FOR_IMR)
        self.as_(imr).post(f'/api/proposals/{proposal_id}/imr/',
                           {'decision': 'deny', 'comments': 'Out of scope.'},
                           format='json', HTTP_X_REAUTH_TOKEN=self.token(imr))
        notice = Notification.objects.get(recipient=vp_head, kind=Notification.IMR_DENIED)
        self.assertEqual(notice.severity, 'info')
