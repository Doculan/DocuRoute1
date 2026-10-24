"""Phase 3C-1: the deadline ladder, priority manuals, Reviewed no change,
and the periodic-review step.

The rules with teeth:

- **Each rung once, on its day, to the right posts**: reminders and the
  due day to the office's Head and Encoders; overdue adds the Head above;
  at +7 days the nearest approving office and the QMS; weekly after that.
  A second run sends nothing; a reminder from before the obligation
  existed is skipped; a missed day is caught up.
- **Fallbacks**: no approving office above, the President's; an approving
  office with no Head, the system admin.
- **Met clears** every open notice of the office's unit.
- **Reviewed, no change**: a Head of a concurring office only, with the
  password, never over an open proposal; meets only that office's
  obligations; sets the review dates.
- **Periodic review** is off unless switched on, and sets one deadline a
  month.

Tests that expect an error assert the reason.
"""

import datetime

from django.utils import timezone
from rest_framework.test import APIClient

from api import deadline_ladder, deadlines, monitoring, reviews
from api.models import (
    CustomUser, Deadline, DeadlineObligation, DeadlineTarget, DeadlineType, Manual,
    ManualReview, MonitoringSetting, Notification, Office, OfficeLink, Position, Proposal,
    SystemEvent,
)
from api.views import issue_reauth_token

from .tests_notices import DeadlineFixture


class LadderFixture(DeadlineFixture):

    def setUp(self):
        super().setUp()
        # The President above the VP: the VP is the approving office above
        # Accounting, the President the root.
        self.president = Office.objects.create(name='Office of the President',
                                               is_approving_level=True)
        Office.objects.filter(pk=self.vp.pk).update(parent=self.president)
        self.vp.refresh_from_db()
        self.vp_head = self.person('vp_head', self.vp, Position.HEAD)
        self.president_head = self.person('president_head', self.president, Position.HEAD)
        qms = Office.objects.create(name='Quality Management Office')
        self.imr = self.person('imr', qms, Position.IMR)
        self.custodian = self.person('custodian', qms, Position.DOCUMENT_CUSTODIAN)
        self.start = timezone.now()

    def owed(self, office=None, manuals=None, days=30, reminders=None):
        """A deadline owed by `office` alone: office-level, or on `manuals`."""
        office = office or self.acc
        deadline = Deadline.objects.create(
            title='Audit', type=self.dtype, created_by=self.admin,
            due_on=timezone.localdate(self.start) + datetime.timedelta(days=days),
            reminder_days=reminders if reminders is not None else [30, 14, 7, 3, 1])
        if manuals:
            for manual in manuals:
                DeadlineTarget.objects.create(deadline=deadline, kind='manual', manual=manual)
        else:
            DeadlineTarget.objects.create(deadline=deadline, kind='office', office=office)
        deadlines.materialise(deadline, self.admin, now=self.start)
        deadline.obligations.exclude(office=office).delete()
        deadlines.refresh_counts([deadline.pk])
        return deadline

    def run_on(self, days_later):
        return deadline_ladder.send(lambda: None, now=self.start + datetime.timedelta(days=days_later))

    def told(self, kind, user=None):
        notices = Notification.objects.filter(kind=kind)
        if user is not None:
            notices = notices.filter(recipient=user)
        return notices


class EachRungOnceOnItsDay(LadderFixture):

    def test_a_reminder_on_each_day_to_head_and_encoder(self):
        deadline = self.owed(days=20)
        self.assertEqual(self.run_on(0), 0)              # 20 days out: no rung
        self.assertEqual(self.run_on(6), 1)              # 14 days out
        notice = self.told(Notification.DEADLINE_REMINDER, self.acc_head).get()
        self.assertEqual(notice.severity, 'action')
        self.assertEqual(notice.title, f'Audit — due in 14 days ({deadline.due_on.day} '
                                       f'{deadline.due_on:%b %Y})')
        self.assertTrue(self.told(Notification.DEADLINE_REMINDER, self.acc_enc).exists())
        self.assertFalse(self.told(Notification.DEADLINE_REMINDER, self.vp_head).exists())
        self.assertEqual(self.run_on(6), 0)              # the second run tells nobody
        self.assertEqual(self.run_on(7), 0)              # 13 days out: still the 14-day rung
        for day, rung in ((13, 'remind7'), (17, 'remind3'), (19, 'remind1')):
            self.assertEqual(self.run_on(day), 1, rung)
            self.assertTrue(Notification.objects.filter(dedupe_key__endswith=rung).exists())
        self.assertEqual(self.told(Notification.DEADLINE_REMINDER, self.acc_head).count(), 4)
        self.assertEqual(SystemEvent.objects.filter(kind=SystemEvent.DEADLINE_REMINDER).count(), 4)

    def test_a_reminder_from_before_the_obligation_is_skipped(self):
        """Given nine days, it is not reminded "14 days" the same day."""
        self.owed(days=9)
        self.assertEqual(self.run_on(0), 0)
        self.assertEqual(self.run_on(2), 1)              # 7 days out
        self.assertTrue(Notification.objects.filter(dedupe_key__endswith='remind7').exists())

    def test_a_missed_day_is_caught_up_once(self):
        self.owed(days=20)
        self.assertEqual(self.run_on(15), 1)             # 5 days out: the 7-day rung, late
        self.assertTrue(Notification.objects.filter(dedupe_key__endswith='remind7').exists())
        self.assertFalse(Notification.objects.filter(dedupe_key__endswith='remind14').exists())

    def test_the_due_day(self):
        self.owed(days=3, reminders=[])
        self.assertEqual(self.run_on(3), 1)
        notice = self.told(Notification.DEADLINE_DUE, self.acc_head).get()
        self.assertEqual(notice.title, 'Audit — due today')
        self.assertTrue(self.told(Notification.DEADLINE_DUE, self.acc_enc).exists())

    def test_overdue_also_tells_the_head_above(self):
        self.owed(office=self.cash, days=1, reminders=[])
        self.assertEqual(self.run_on(2), 1)
        self.assertEqual(self.told(Notification.DEADLINE_OVERDUE, self.cash_head).get().severity,
                         'action')
        # Cash sits under Accounting: its Head hears, for information.
        self.assertEqual(self.told(Notification.DEADLINE_OVERDUE, self.acc_head).get().severity,
                         'info')
        self.assertFalse(self.told(Notification.DEADLINE_OVERDUE, self.vp_head).exists())

    def test_a_week_late_the_approving_office_and_the_qms_are_told(self):
        self.owed(days=1, reminders=[])
        self.assertEqual(self.run_on(8), 2)              # overdue and escalated, caught up
        for user in (self.vp_head, self.imr, self.custodian):
            notice = self.told(Notification.DEADLINE_ESCALATED, user).get()
            self.assertEqual(notice.severity, 'info')
            self.assertTrue(notice.title.startswith('Accounting Office: Audit is 7 days overdue'),
                            notice.title)
        self.assertFalse(self.told(Notification.DEADLINE_ESCALATED, self.acc_head).exists())
        self.assertFalse(self.told(Notification.DEADLINE_ESCALATED, self.president_head).exists())

    def test_weekly_once_each_iso_week(self):
        self.owed(days=1, reminders=[])
        self.run_on(8)
        weekly = lambda: Notification.objects.filter(dedupe_key__contains=':weekly:',
                                                     recipient=self.vp_head).count()
        self.assertEqual(weekly(), 0)                    # not in the escalation's own week
        # A Monday at least 14 days late, then every day of that ISO week -
        # in the project's time zone, as the ladder counts days.
        monday = next(d for d in range(15, 22) if timezone.localtime(
            self.start + datetime.timedelta(days=d)).weekday() == 0)
        for day in range(monday, monday + 7):
            self.run_on(day)
        self.assertEqual(weekly(), 1)                    # once in the week
        self.run_on(monday + 7)
        self.assertEqual(weekly(), 2)                    # and again the next

    def test_several_manuals_one_notice_priority_first(self):
        deadline = self.owed(manuals=[self.m1, self.m2], days=7)
        deadline.obligations.filter(manual=self.m2).update(priority=True)
        self.run_on(0)
        notice = self.told(Notification.DEADLINE_REMINDER, self.acc_head).get()
        self.assertEqual(notice.body, 'Owed: Priority: FAM 2, FAM 1')
        self.assertTrue(notice.office_level)


class WhereThereIsNobody(LadderFixture):

    def test_no_approving_office_above_the_presidents_is_told(self):
        lone = Office.objects.create(name='Standalone Unit')
        self.person('lone_head', lone, Position.HEAD)
        self.owed(office=lone, days=1, reminders=[])
        self.run_on(8)
        self.assertTrue(self.told(Notification.DEADLINE_ESCALATED, self.president_head).exists())

    def test_an_approving_office_with_no_head_the_system_admin_is_told(self):
        Position.objects.filter(office=self.vp, kind=Position.HEAD).update(is_active=False)
        self.owed(days=1, reminders=[])
        self.run_on(8)
        self.assertTrue(self.told(Notification.DEADLINE_ESCALATED, self.admin).exists())
        self.assertFalse(self.told(Notification.DEADLINE_ESCALATED, self.vp_head).exists())


class MetClears(LadderFixture):

    def test_submitting_clears_every_open_notice_of_the_unit(self):
        deadline = self.owed(manuals=[self.m1], days=1, reminders=[])
        self.run_on(1)
        self.run_on(3)
        open_ones = Notification.objects.filter(recipient=self.acc_head, severity='action',
                                                acted_at__isnull=True)
        self.assertEqual(open_ones.count(), 3)           # set, due, overdue
        proposal = self.proposal(self.acc, self.m1)
        deadlines.on_submitted(proposal, self.acc_head)
        self.assertEqual(open_ones.count(), 0)
        self.assertFalse(DeadlineObligation.objects.filter(deadline=deadline, state='open').exists())

    def test_a_deadline_set_inactive_is_cleared_by_the_run(self):
        deadline = self.owed(days=1, reminders=[])
        self.run_on(1)
        Deadline.objects.filter(pk=deadline.pk).update(active=False)
        self.assertEqual(deadline_ladder.clear_met(), 2)    # the Head's and the Encoder's
        self.assertFalse(self.told(Notification.DEADLINE_DUE, self.acc_head)
                         .filter(acted_at__isnull=True).exists())

    def test_run_monitoring_runs_the_ladder(self):
        from api.models import JobRun
        self.owed(days=0, reminders=[])
        counts = monitoring.run(trigger=JobRun.SCHEDULED, only=('deadlines',))
        self.assertEqual(counts['deadline_notices_sent'], 1)


class PriorityManuals(LadderFixture):

    def post(self, deadline, body):
        return self.as_(self.admin).post(f'/api/admin/deadlines/{deadline.pk}/priority/', body,
                                         format='json')

    def test_a_pair_is_made_flagged_and_the_office_told(self):
        deadline = self.owed(days=20)                    # office-level for Accounting
        response = self.post(deadline, {'office_id': self.acc.pk, 'manual_ids': [self.m2.pk]})
        self.assertEqual(response.status_code, 200, response.data)
        pair = DeadlineObligation.objects.get(deadline=deadline, office=self.acc, manual=self.m2)
        self.assertTrue(pair.priority)
        notice = Notification.objects.get(recipient=self.acc_head, dedupe_key__contains=':priority:')
        self.assertEqual(notice.title, f'Priority for Audit — due {deadline.due_on:%d %b %Y}')
        self.assertEqual(notice.manual, self.m2)
        deadline.refresh_from_db()
        self.assertEqual(deadline.obligations_total, 2)

    def test_it_ranks_first_on_the_offices_deadlines(self):
        deadline = self.owed(manuals=[self.m1, self.m2], days=20)
        self.post(deadline, {'office_id': self.acc.pk, 'manual_ids': [self.m2.pk]})
        group = self.as_(self.acc_head).get('/api/my-deadlines/').data['deadlines'][0]
        self.assertEqual([m['title'] for m in group['manuals']], ['FAM 2', 'FAM 1'])
        self.assertTrue(group['manuals'][0]['priority'])

    def test_the_admins_list_is_unmet_first_priority_first(self):
        """Found building 3C: ordering by `state` put "effective" before
        "open", against the list's own promise of unmet first."""
        deadline = Deadline.objects.create(title='Audit', type=self.dtype, created_by=self.admin,
                                           due_on=timezone.localdate() + datetime.timedelta(days=9))
        DeadlineTarget.objects.create(deadline=deadline, kind='series', series=self.fam)
        deadlines.materialise(deadline, self.admin)
        deadline.obligations.filter(office=self.acc, manual=self.m1).update(
            state=DeadlineObligation.EFFECTIVE)
        deadline.obligations.filter(office=self.bud, manual=self.m9).update(priority=True)
        rows = self.as_(self.admin).get(
            f'/api/admin/deadlines/{deadline.pk}/obligations/').data['obligations']
        self.assertEqual((rows[0]['office'], rows[0]['manual'], rows[0]['priority']),
                         ('Budget Office', 'FAM 9', True))
        states = [r['state'] for r in rows]
        self.assertEqual(states, sorted(states, key=lambda s: s != 'open'))
        self.assertEqual(states[-1], 'effective')

    def test_refusals_name_the_reason(self):
        deadline = self.owed(days=20)
        for body, reason in (({'office_id': 'x', 'manual_ids': [self.m1.pk]}, 'invalid_office'),
                             ({'office_id': self.acc.pk, 'manual_ids': []}, 'invalid_manuals'),
                             ({'office_id': self.acc.pk, 'manual_ids': [999999]}, 'invalid_manuals'),
                             # FAM 9 overrides: only Budget concurs on it.
                             ({'office_id': self.acc.pk, 'manual_ids': [self.m9.pk]}, 'not_concurring')):
            response = self.post(deadline, body)
            self.assertEqual(response.status_code, 400, body)
            self.assertEqual(response.data['reason'], reason, body)
        self.assertIn('FAM 9', self.post(deadline, {'office_id': self.acc.pk,
                                                    'manual_ids': [self.m9.pk]}).data['error'])


class ReviewedNoChange(LadderFixture):

    def review(self, user, manual=None, token=True, **body):
        manual = manual or self.m1
        extra = {'HTTP_X_REAUTH_TOKEN': issue_reauth_token(user)} if token else {}
        return self.as_(user).post(f'/api/manuals/{manual.pk}/reviewed-no-change/', body,
                                   format='json', **extra)

    def test_it_meets_only_that_offices_obligations_and_sets_the_dates(self):
        on_manual = self.owed(manuals=[self.m1], days=20)
        office_wide = self.owed(days=20)
        theirs = self.owed(office=self.bud, manuals=[self.m1], days=20)
        response = self.review(self.acc_head, note='Checked against the 2026 audit.')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['obligations_met'], 2)
        for deadline in (on_manual, office_wide):
            self.assertEqual(deadline.obligations.get().state, DeadlineObligation.REVIEWED)
        self.assertEqual(theirs.obligations.get().state, DeadlineObligation.OPEN)
        self.m1.refresh_from_db()
        today = timezone.localdate()
        self.assertEqual(self.m1.last_reviewed_on, today)
        self.assertEqual(self.m1.next_review_due, reviews.add_months(today, 12))
        review = ManualReview.objects.get()
        self.assertEqual((review.office, review.note, len(review.obligations)),
                         (self.acc, 'Checked against the 2026 audit.', 2))
        self.assertTrue(SystemEvent.objects.filter(kind=SystemEvent.REVIEWED_NO_CHANGE,
                                                   manual=self.m1).exists())

    def test_it_clears_the_deadline_notices(self):
        self.owed(manuals=[self.m1], days=20)
        self.review(self.acc_head)
        self.assertFalse(Notification.objects.filter(recipient=self.acc_head, severity='action',
                                                     acted_at__isnull=True).exists())

    def test_the_tag_says_reviewed_not_submitted(self):
        """Found driving the screen: the tag called a review a submission."""
        from api.deadline_tags import deadline_tags_for
        self.owed(manuals=[self.m1], days=20)
        self.review(self.acc_head)
        tag = deadline_tags_for(self.acc_head, [self.m1.pk])[self.m1.pk]
        self.assertEqual(tag['state'], 'reviewed')
        self.assertTrue(tag['label'].startswith('Reviewed, no change '), tag['label'])
        self.assertTrue(tag['muted'])

    def test_the_interval_is_the_setting(self):
        MonitoringSetting.objects.filter(stage='review_interval_months').update(days=6)
        self.review(self.acc_head)
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.next_review_due, reviews.add_months(timezone.localdate(), 6))

    def test_refusals_name_the_reason(self):
        self.assertEqual(self.review(self.acc_enc).data['reason'], 'not_head')
        reg_head = self.person('reg_head', self.reg, Position.HEAD)    # reads FAM only
        self.assertEqual(self.review(reg_head).data['reason'], 'not_concurring')
        self.assertEqual(self.review(self.acc_head, token=False).data['reason'], 'reauth_required')
        self.assertEqual(self.review(self.acc_head, note='x' * 1001).data['reason'], 'note_too_long')
        self.proposal(self.acc, self.m1, status=Proposal.DRAFT)
        response = self.review(self.acc_head)
        self.assertEqual((response.status_code, response.data['reason']), (409, 'proposal_open'))
        self.assertFalse(ManualReview.objects.exists())

    def test_a_head_of_two_concurring_offices_chooses(self):
        from api.models import ManualSeriesOffice, PositionAssignment
        treasury = Office.objects.create(name='Treasury', parent=self.vp)
        ManualSeriesOffice.objects.create(series=self.fam, office=treasury,
                                          relationship=OfficeLink.CONCURRING)
        position = Position.objects.create(office=treasury, kind=Position.HEAD)
        PositionAssignment.objects.create(user=self.acc_head, position=position,
                                          starts_on=timezone.localdate())
        self.assertEqual(self.review(self.acc_head).data['reason'], 'office_required')
        response = self.review(self.acc_head, office_id=treasury.pk)
        self.assertEqual((response.status_code, response.data['office']), (200, 'Treasury'))

    def test_the_manual_view_says_who_may(self):
        data = self.as_(self.acc_head).get(f'/api/manuals/{self.m1.pk}/sections/').data['review']
        self.assertTrue(data['can_record'])
        self.assertFalse(self.as_(self.acc_enc).get(
            f'/api/manuals/{self.m1.pk}/sections/').data['review']['can_record'])


class PeriodicReview(LadderFixture):

    def setUp(self):
        super().setUp()
        Manual.objects.filter(pk=self.m1.pk).update(
            next_review_due=timezone.localdate() - datetime.timedelta(days=1))

    def test_off_by_default(self):
        self.assertEqual(reviews.gather_due_reviews(), 0)
        self.assertFalse(Deadline.objects.filter(title__startswith='Periodic').exists())

    def test_on_one_deadline_a_month_for_the_documents_past_review(self):
        MonitoringSetting.objects.filter(stage='periodic_review').update(days=1)
        self.assertEqual(reviews.gather_due_reviews(), 1)
        deadline = Deadline.objects.get(title__startswith='Periodic document review — ')
        self.assertEqual({ob.manual_id for ob in deadline.obligations.all()}, {self.m1.pk})
        self.assertEqual({ob.office_id for ob in deadline.obligations.all()},
                         {self.acc.pk, self.cash.pk, self.bud.pk})
        self.assertEqual(reviews.gather_due_reviews(), 0)        # once this month


class MissedRunsAndTheDryRun(LadderFixture):
    """The dashboard's own batch covers the ladder (a stopped scheduler
    never leaves a deadline silently overdue), and the dry run with a
    date override writes nothing."""

    def notices(self):
        return Notification.objects.filter(kind__in=deadline_ladder.LADDER_NOTICES)

    def test_a_dashboard_load_sends_its_offices_due_steps(self):
        self.owed(days=0, reminders=[])                          # Accounting, due today
        self.owed(office=self.bud, days=0, reminders=[])         # Budget, due today
        self.as_(self.acc_head).get('/api/staff/dashboard/')
        self.assertEqual(set(self.notices().values_list('addressed_office__name', flat=True)),
                         {'Accounting Office'})

    def test_capped_at_one_batch(self):
        from unittest import mock
        self.owed(days=0, reminders=[])
        self.owed(days=0, reminders=[])
        with mock.patch.object(deadline_ladder, 'BATCH', 1):
            self.as_(self.acc_head).get('/api/staff/dashboard/')
        self.assertEqual(self.notices().values('dedupe_key').distinct().count(), 1)

    def test_not_while_the_scheduler_is_running(self):
        from api.models import JobRun
        JobRun.objects.create(started_at=timezone.now(), finished_at=timezone.now())
        self.owed(days=0, reminders=[])
        self.as_(self.acc_head).get('/api/staff/dashboard/')
        self.assertFalse(self.notices().exists())

    def command(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('run_monitoring', *args, stdout=out)
        return out.getvalue()

    def test_the_dry_run_lists_and_writes_nothing(self):
        from api.models import JobRun
        deadline = self.owed(days=1, reminders=[])
        before = (Notification.objects.count(), SystemEvent.objects.count(), JobRun.objects.count())
        as_of = (deadline.due_on + datetime.timedelta(days=8)).isoformat()
        out = self.command('--dry-run', '--as-of', as_of)
        self.assertIn(f'Dry run, as of {as_of}. Nothing is written.', out)
        self.assertIn('overdue      Audit | Accounting Office |', out)
        self.assertIn('escalated    Audit | Accounting Office |', out)
        self.assertIn('VP Office — Head (info)', out)
        self.assertEqual((Notification.objects.count(), SystemEvent.objects.count(),
                          JobRun.objects.count()), before)

    def test_as_of_without_the_dry_run_is_refused_on_live_data(self):
        from django.core.management.base import CommandError
        deadline = self.owed(days=1, reminders=[])
        as_of = (deadline.due_on + datetime.timedelta(days=8)).isoformat()
        with self.assertRaisesMessage(CommandError, 'Refused: --as-of without --dry-run'):
            self.command('--as-of', as_of)
        self.assertFalse(self.notices().exists())
        with self.assertRaisesMessage(CommandError, '--as-of takes a date as YYYY-MM-DD.'):
            self.command('--dry-run', '--as-of', '8 Dec 2026')

    def test_as_of_sends_on_a_demo_database(self):
        from django.test import override_settings
        deadline = self.owed(days=1, reminders=[])
        as_of = (deadline.due_on + datetime.timedelta(days=8)).isoformat()
        with override_settings(MONITORING_ALLOW_AS_OF=True):
            out = self.command('--as-of', as_of, '--only', 'deadlines')
        self.assertIn('deadline notices sent 2', out)
        self.assertTrue(self.told(Notification.DEADLINE_ESCALATED, self.vp_head).exists())
