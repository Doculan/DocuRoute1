"""The deadline tag (Phase 3B, spec §6.7).

The rules with teeth:

- **Wording and states**: upcoming, inside the reminder window with days
  left, today, overdue, submitted - text, not colour alone.
- **Who sees what**: the office that owes it; Heads above it, QMS staff
  and the admin with the office named; concurring and reader offices
  muted; **another branch nothing**.
- **The nearest** of several deadlines, with "+1 more".
- **Queries do not grow with the page.**
- **Coverage**: every GET route is called, and any manual in any answer
  without a `deadline` key fails the test - so a new screen cannot leave
  the tag out silently. Exemptions are named, with the reason.
"""

import datetime
import json

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, URLResolver
from django.utils import timezone

from api import deadlines, urls
from api.deadline_tags import deadline_tags_for
from api.models import (
    CustomUser, Deadline, DeadlineObligation, DeadlineTarget, Manual, ManualOffice, Office,
    OfficeLink, Position, Proposal, ProposalParticipant, ProposalVersion,
)

from .tests_concurrence import ConcurrenceFixture
from .tests_notices import DeadlineFixture


class TagFixture(DeadlineFixture):

    def setUp(self):
        super().setUp()
        self.vp_head = self.person('vp_head', self.vp, Position.HEAD)
        self.reg_head = self.person('reg_head', self.reg, Position.HEAD)
        # Another branch: its own VP and office, nothing to do with FAM.
        self.vp2 = Office.objects.create(name='VP Academic', is_approving_level=True)
        self.dept = Office.objects.create(name='Department of English', parent=self.vp2)
        self.dept_head = self.person('dept_head', self.dept, Position.HEAD)
        qms = Office.objects.create(name='Quality Management Office')
        self.imr = self.person('imr', qms, Position.IMR)
        self.imr.system_role = CustomUser.QMS_STAFF
        self.imr.save(update_fields=['system_role'])

    def on(self, manual, office, days=20, note=''):
        """A deadline naming `manual`, owed by `office` alone."""
        deadline = Deadline.objects.create(
            title='Audit', type=self.dtype, note=note, created_by=self.admin,
            due_on=self.today + datetime.timedelta(days=days))
        DeadlineTarget.objects.create(deadline=deadline, kind='manual', manual=manual)
        deadlines.materialise(deadline, self.admin)
        deadline.obligations.exclude(office=office).delete()
        return deadline

    def tag(self, user, manual=None):
        manual = manual or self.m1
        return deadline_tags_for(user, [manual.pk]).get(manual.pk)


class TheWording(TagFixture):

    def test_upcoming_names_the_date(self):
        self.on(self.m1, self.acc, days=40)
        tag = self.tag(self.acc_head)
        due = self.today + datetime.timedelta(days=40)
        self.assertEqual(tag['state'], 'upcoming')
        self.assertEqual(tag['label'], f'Deadline upcoming {due.day} {due:%b %Y}')
        self.assertEqual(tag['type'], 'Internal quality audit')
        self.assertFalse(tag['muted'])

    def test_inside_the_window_counts_the_days(self):
        self.on(self.m1, self.acc, days=5)
        tag = self.tag(self.acc_head)
        self.assertEqual(tag['state'], 'soon')
        self.assertTrue(tag['label'].endswith(' · 5 days'), tag['label'])

    def test_one_day_is_singular(self):
        self.on(self.m1, self.acc, days=1)
        self.assertTrue(self.tag(self.acc_head)['label'].endswith(' · 1 day'))

    def test_today(self):
        self.on(self.m1, self.acc, days=0)
        tag = self.tag(self.acc_head)
        self.assertEqual((tag['state'], tag['label']), ('today', 'Deadline today'))

    def test_overdue_says_when_it_was_due(self):
        self.on(self.m1, self.acc, days=-3)
        tag = self.tag(self.acc_head)
        due = self.today - datetime.timedelta(days=3)
        self.assertEqual(tag['state'], 'overdue')
        self.assertEqual(tag['label'], f'Overdue · was due {due.day} {due:%b %Y}')

    def test_submitted_is_muted_with_the_day(self):
        deadline = self.on(self.m1, self.acc)
        met = timezone.now()
        deadline.obligations.update(state=DeadlineObligation.SUBMITTED, office_met_at=met)
        tag = self.tag(self.acc_head)
        day = timezone.localtime(met)
        self.assertEqual((tag['state'], tag['label'], tag['muted']),
                         ('submitted', f'Submitted {day.day} {day:%b}', True))

    def test_a_met_obligation_goes_once_its_date_passes(self):
        deadline = self.on(self.m1, self.acc, days=-1)
        deadline.obligations.update(state=DeadlineObligation.SUBMITTED, office_met_at=timezone.now())
        self.assertIsNone(self.tag(self.acc_head))

    def test_the_owing_office_sees_the_admins_note(self):
        self.on(self.m1, self.acc, note='Bring the 2025 findings.')
        self.assertEqual(self.tag(self.acc_enc)['note'], 'Bring the 2025 findings.')

    def test_an_inactive_deadline_tags_nothing(self):
        Deadline.objects.filter(pk=self.on(self.m1, self.acc).pk).update(active=False)
        self.assertIsNone(self.tag(self.acc_head))

    def test_an_office_level_obligation_tags_no_manual(self):
        """Q-3: it shows in the banner and the Deadlines panel instead."""
        deadline = Deadline.objects.create(title='Audit', type=self.dtype, created_by=self.admin,
                                           due_on=self.today + datetime.timedelta(days=9))
        DeadlineTarget.objects.create(deadline=deadline, kind='office', office=self.acc)
        deadlines.materialise(deadline, self.admin)
        self.assertTrue(deadline.obligations.filter(office=self.acc, manual=None).exists())
        self.assertEqual(deadline_tags_for(self.acc_head, [self.m1.pk, self.m2.pk]), {})


class WhoSeesWhat(TagFixture):

    def setUp(self):
        super().setUp()
        self.on(self.m1, self.acc)

    def test_the_owing_office_sees_its_own_tag(self):
        for user in (self.acc_head, self.acc_enc):
            tag = self.tag(user)
            self.assertEqual(tag['view'], 'own')
            self.assertTrue(tag['label'].startswith('Deadline upcoming'), tag['label'])

    def test_heads_above_qms_and_admin_see_who_owes_it(self):
        for user in (self.vp_head, self.imr, self.admin):
            tag = self.tag(user)
            self.assertEqual(tag['view'], 'advised', user.username)
            self.assertTrue(tag['label'].startswith('Advised: Accounting Office · deadline upcoming'),
                            tag['label'])
            self.assertEqual(tag['advised'], ['Accounting Office'])

    def test_concurring_and_reader_offices_see_it_muted(self):
        # Budget and Cash concur on FAM; the Registry reads it.
        for user in (self.bud_head, self.cash_head, self.reg_head):
            tag = self.tag(user)
            self.assertEqual((tag['view'], tag['label'], tag['muted']),
                             ('related', 'Revision advised for Accounting Office', True),
                             user.username)

    def test_another_branch_sees_nothing(self):
        self.assertIsNone(self.tag(self.dept_head))

    def test_an_encoder_does_not_oversee_the_office_below(self):
        """Only a Head oversees; an Encoder above sees what a concurring
        office sees, if anything."""
        vp_enc = self.person('vp_enc', self.vp, Position.ENCODER)
        tag = self.tag(vp_enc)
        # The VP owns FAM, so it reaches it: muted, not "Advised:".
        self.assertEqual(tag['view'], 'related')

    def test_more_than_two_offices_are_counted(self):
        deadline = Deadline.objects.create(title='Audit', type=self.dtype, created_by=self.admin,
                                           due_on=self.today + datetime.timedelta(days=30))
        DeadlineTarget.objects.create(deadline=deadline, kind='manual', manual=self.m2)
        deadlines.materialise(deadline, self.admin)     # ACC, Cash and Budget concur on FAM 2
        tag = self.tag(self.admin, self.m2)
        self.assertEqual((tag['advised'], tag['advised_more']),
                         (['Accounting Office', 'Budget Office'], 1))
        self.assertTrue(tag['label'].startswith('Advised: Accounting Office, Budget Office +1 · '),
                        tag['label'])


class TheNearest(TagFixture):

    def test_two_deadlines_show_the_nearest_and_one_more(self):
        later = self.on(self.m1, self.acc, days=60)
        sooner = self.on(self.m1, self.acc, days=6)
        tag = self.tag(self.acc_head)
        self.assertEqual((tag['deadline_id'], tag['more']), (sooner.pk, 1))
        self.assertNotEqual(tag['deadline_id'], later.pk)

    def test_an_open_one_comes_before_a_submitted_one(self):
        met = self.on(self.m1, self.acc, days=3)
        met.obligations.update(state=DeadlineObligation.SUBMITTED, office_met_at=timezone.now())
        still_open = self.on(self.m1, self.acc, days=50)
        self.assertEqual(self.tag(self.acc_head)['deadline_id'], still_open.pk)


class TheQueryCount(TagFixture):

    def queries(self, user, manuals):
        with CaptureQueriesContext(connection) as ctx:
            deadline_tags_for(user, [m.pk for m in manuals])
        return len(ctx)

    def test_it_does_not_grow_with_the_page(self):
        few = [self.m1, self.m2]
        many = few + [Manual.objects.create(title=f'FAM {n}', series=self.fam)
                      for n in range(10, 40)]
        for manual in many:
            self.on(manual, self.acc)
        for user in (self.acc_head, self.bud_head, self.vp_head, self.admin):
            self.assertEqual(self.queries(user, few), self.queries(user, many), user.username)

    def test_one_query_when_nothing_is_owed(self):
        self.assertEqual(self.queries(self.acc_head, [self.m1, self.m2]), 1)

    # Each count includes one query for the change freezes in force (3D),
    # made only when the page carries tags.
    def test_three_for_the_owing_office(self):
        self.on(self.m1, self.acc)
        self.assertEqual(self.queries(self.acc_head, [self.m1]), 3)

    def test_four_where_the_viewer_only_concurs(self):
        self.on(self.m1, self.acc)
        self.assertEqual(self.queries(self.bud_head, [self.m1]), 4)

    def test_nor_with_a_freeze_in_force(self):
        from api.models import Freeze, FreezeTarget
        made = Freeze.objects.create(reason='Audit', expected_end_on=self.today,
                                     scope=Freeze.SERIES, started_by=self.admin)
        FreezeTarget.objects.create(freeze=made, series=self.fam)
        few = [self.m1, self.m2]
        many = few + [Manual.objects.create(title=f'FAM {n}', series=self.fam)
                      for n in range(10, 40)]
        for manual in many:
            self.on(manual, self.acc)
        self.assertEqual(self.queries(self.acc_head, few), self.queries(self.acc_head, many))
        self.assertIsNotNone(deadline_tags_for(self.acc_head, [self.m1.pk])[self.m1.pk]['frozen'])


class TheTagCostsAFixedNumberOfQueries(TagFixture):
    """Each converted endpoint, on a page of twelve manuals that all owe
    something: the tag adds at most three queries, however long the page."""

    ROWS = 12

    def setUp(self):
        super().setUp()
        from api import system_log
        from api.models import Notification, RecentlyOpened, SystemEvent
        self.manuals = [Manual.objects.create(title=f'FAM 5.{n:02}', series=self.fam)
                        for n in range(self.ROWS)]
        for manual in self.manuals:
            manual.sections.create(subtitle='1.0 PURPOSE', order=0, content='Purpose.')
            RecentlyOpened.objects.create(user=self.acc_head, manual=manual)
            self.proposal(self.acc, manual)
            ManualOffice.objects.create(manual=manual, office=self.acc,
                                        relationship=OfficeLink.CONCURRING)
            manual.offices_overridden = True
            manual.save(update_fields=['offices_overridden'])
        cause = system_log.record(SystemEvent.DEADLINE_SET)
        Notification.objects.bulk_create([Notification(
            recipient=self.acc_head, kind=Notification.DEADLINE_SET, severity='info',
            title='Deadline set', manual=m, manual_title=m.title, system_event=cause,
            dedupe_key=f'test:{m.pk}') for m in self.manuals])
        self.on_every(self.manuals)

    def on_every(self, manuals):
        deadline = Deadline.objects.create(title='Audit', type=self.dtype, created_by=self.admin,
                                           due_on=self.today + datetime.timedelta(days=9))
        DeadlineTarget.objects.bulk_create([DeadlineTarget(deadline=deadline, kind='manual',
                                                           manual=m) for m in manuals])
        deadlines.materialise(deadline, self.admin)

    def count(self, user, url, tags_on):
        from unittest import mock
        client = self.as_(user)
        client.get(url)        # warm: sessions, content types, the first-call caches
        if tags_on:
            with CaptureQueriesContext(connection) as ctx:
                response = client.get(url)
        else:
            with mock.patch('api.deadline_tags.deadline_tags_for', return_value={}), \
                    mock.patch('api.views.deadline_tags_for', return_value={}), \
                    CaptureQueriesContext(connection) as ctx:
                response = client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return len(ctx)

    def test_each_endpoint(self):
        for user, url in (
                (self.acc_head, '/api/staff/sections/'),
                (self.acc_head, '/api/staff/dashboard/'),
                (self.acc_head, '/api/proposals/'),
                (self.acc_head, '/api/notifications/'),
                (self.acc_head, '/api/needs-action/'),
                (self.acc_head, '/api/action-banner/'),
                (self.admin, '/api/admin/dashboard/'),
                (self.admin, '/api/admin/proposals/'),
                (self.admin, '/api/org/series/'),
                (self.admin, '/api/admin/manual-search/?q=FAM'),
        ):
            with self.subTest(url):
                added = self.count(user, url, True) - self.count(user, url, False)
                self.assertLessEqual(added, 3, f'{url} adds {added} queries')

    def test_and_the_page_really_holds_tagged_rows(self):
        """Otherwise the count above would prove nothing."""
        rows = self.as_(self.acc_head).get('/api/proposals/').json()['proposals']
        self.assertGreaterEqual(len(rows), self.ROWS)
        self.assertTrue(all(row['deadline'] for row in rows))


# ─── Coverage ────────────────────────────────────────────────

# Routes whose answers carry manuals but need no tag, and why.
EXEMPT = {
    'admin/deadlines/<int:deadline_id>/obligations/': 'each row is an obligation itself',
    'my-deadlines/': 'each row is a deadline itself',
}

# Parts of an answer that name a manual inside a deadline's own row,
# where a tag would only repeat the row.
EXEMPT_PARTS = {
    'action-banner/': ('.deadlines.', 'each deadline row is the deadline itself'),
    'admin/deadlines/<int:deadline_id>/': ('.targets', "the deadline's own targets"),
}

# Long lists answer with a summary by default (3B-2), so the walk also
# asks for their pages, where the manuals are.
ALSO_ASK = {
    'monitoring/items/': ['?bucket=advised', '?bucket=owed', '?bucket=unmet',
                          '?bucket=open'],
    'proposals/board/': ['?section=due', '?section=awaiting', '?section=mine',
                         '?section=involving'],
    'staff/manuals/': ['?page=1', '?q=FAM', '?picker=1'],
    'manuals/': ['?page=1', '?picker=1'],
    'qms/queue/': ['?queue=imr', '?queue=approval'],
    'org/documents/': ['?page=1'],
}

# A drop-down's options: a title to choose, not a place to read a tag.
PICKER = ('.manuals', 'drop-down options')
EXEMPT_ASKED = {'staff/manuals/?picker=1': PICKER, 'manuals/?picker=1': PICKER}

# Routes that answer with a file, or only take other methods.
NOT_JSON = {'proposals/<int:proposal_id>/attachments/<int:attachment_id>/download/',
            'proposals/<int:proposal_id>/trail-report/', 'trail-reports/<str:serial>/'}


def _routes(patterns, prefix=''):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _routes(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), entry.callback


def _answers_get(callback):
    cls = getattr(callback, 'cls', None) or getattr(callback, 'view_class', None)
    return cls is not None and hasattr(cls, 'get')


MANUAL_KEYS = {'manual', 'manuals', 'document', 'documents', 'overriding_documents',
               'did_not_reach'}

# A route that opens one manual answers with its tag at the top.
OPENS_A_MANUAL = ('<int:manual_id>', '<int:document_id>')


def _manuals_named(data, key=None):
    """How many manuals an answer names, by the same reading as `_untagged`."""
    if isinstance(data, dict):
        here = int(data.get('manual_id') is not None or data.get('manual') is not None
                   or ({'id', 'title'} <= data.keys() and ('series' in data or key in MANUAL_KEYS)))
        return here + sum(_manuals_named(v, k) for k, v in data.items())
    if isinstance(data, list):
        return sum(_manuals_named(v, key) for v in data)
    return 0


def _untagged(data, path='$', key=None, tagged=False):
    """Every manual in the answer without a `deadline` key, unless the row
    holding it has one. A manual is named by `manual_id`, by a `manual`
    beside the row's other fields, or is itself an object with an `id` and
    `title` that has a `series` or sits under a manual-ish key."""
    found = []
    if isinstance(data, dict):
        names_a_manual = (
            data.get('manual_id') is not None or data.get('manual') is not None
            or ({'id', 'title'} <= data.keys() and ('series' in data or key in MANUAL_KEYS)))
        has = 'deadline' in data
        if names_a_manual and not (has or tagged):
            found.append(path)
        for name, value in data.items():
            found += _untagged(value, f'{path}.{name}', name, tagged or has)
    elif isinstance(data, list):
        for n, value in enumerate(data):
            found += _untagged(value, f'{path}[{n}]', key, tagged)
    return found


def _not_the_tag(data, path='$'):
    """Every `deadline` in an answer that is neither null nor the tag (which
    always carries `deadline_id` and `label`). The bug of 27 Oct 2026: a
    row's own deadline title under `deadline` was overwritten by the tag,
    and the screen printed an object."""
    found = []
    if isinstance(data, dict):
        value = data.get('deadline', None)
        if 'deadline' in data and value is not None and not (
                isinstance(value, dict) and {'deadline_id', 'label'} <= value.keys()):
            found.append(f'{path}.deadline')
        for name, inner in data.items():
            found += _not_the_tag(inner, f'{path}.{name}')
    elif isinstance(data, list):
        for n, inner in enumerate(data):
            found += _not_the_tag(inner, f'{path}[{n}]')
    return found


class EveryScreenCarriesTheTag(ConcurrenceFixture):
    maxDiff = None

    def setUp(self):
        super().setUp()
        from api.models import DeadlineType
        self.vpaf_head = self.person('vpaf_head', self.vpaf, Position.HEAD)
        qms = Office.objects.create(name='Quality Management Office')
        self.imr = self.person('imr', qms, Position.IMR)
        self.imr.system_role = CustomUser.QMS_STAFF
        self.imr.save(update_fields=['system_role'])
        self.admin = CustomUser.objects.create_user(
            username='admin', password='pw', role='admin', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN)
        self.deadline = Deadline.objects.create(
            title='Audit', type=DeadlineType.objects.get(name='Internal quality audit'),
            created_by=self.admin, due_on=self.today + datetime.timedelta(days=20))
        # A document overriding its series, so the series list names one.
        own = Manual.objects.create(title='FAM 7.01', series=self.series,
                                    offices_overridden=True)
        ManualOffice.objects.create(manual=own, office=self.accounting,
                                    relationship=OfficeLink.CONCURRING)
        DeadlineTarget.objects.create(deadline=self.deadline, kind='manual', manual=self.manual)
        DeadlineTarget.objects.create(deadline=self.deadline, kind='manual', manual=own)
        deadlines.materialise(self.deadline, self.admin)
        self.proposal_id = self.a_draft()
        self.submit(self.proposal_id)
        # Something in the IMR's two queues, and a finished request Budget
        # concurred on, for its Involving tab.
        for status in (Proposal.READY_FOR_IMR, Proposal.AWAITING_APPROVAL, Proposal.EFFECTIVE):
            other = Proposal.objects.create(manual=self.manual, initiating_office=self.cash,
                                            status=status, created_by=self.cmo_head)
            ProposalVersion.objects.create(proposal=other, number=1)
            ProposalParticipant.objects.create(proposal=other, office=self.budget,
                                               office_name_at_time=self.budget.name,
                                               role=ProposalParticipant.CONCURRING)
        self.viewers = [self.acc_head, self.bud_head, self.vpaf_head, self.imr, self.admin]
        for user in self.viewers:      # so Recently opened has a row
            self.as_(user).get(f'/api/manuals/{self.manual.pk}/sections/')

    def kwargs(self):
        return {
            'proposal_id': self.proposal_id, 'manual_id': self.manual.pk,
            'section_id': self.s1.pk, 'office_id': self.accounting.pk,
            'series_id': self.series.pk, 'document_id': self.manual.pk,
            'deadline_id': self.deadline.pk, 'announcement_id': 1, 'person_id': 1,
            'assignment_id': 1, 'attachment_id': 1, 'user_id': 1, 'serial': 'x',
        }

    def test_deadline_is_always_the_tag_or_null(self):
        wrong, called = {}, 0
        for route, callback in _routes(urls.urlpatterns):
            if route in NOT_JSON or not _answers_get(callback):
                continue
            url = '/api/' + route
            for name, value in self.kwargs().items():
                url = url.replace(f'<int:{name}>', str(value)).replace(f'<str:{name}>', str(value))
            for asked in [''] + ALSO_ASK.get(route, []):
                for user in self.viewers:
                    response = self.as_(user).get(url + asked)
                    if response.status_code != 200 or 'json' not in response.get('Content-Type', ''):
                        continue
                    called += 1
                    found = _not_the_tag(json.loads(response.content))
                    if found:
                        wrong.setdefault(route + asked, set()).update(found[:3])
        self.assertGreater(called, 50)
        self.assertEqual(wrong, {})

    def test_every_manual_in_every_answer_has_a_deadline_key(self):
        missing, called, rows_seen = {}, 0, {}
        for route, callback in _routes(urls.urlpatterns):
            if route in EXEMPT or route in NOT_JSON:
                continue
            if not _answers_get(callback):
                continue
            url = '/api/' + route
            for name, value in self.kwargs().items():
                url = url.replace(f'<int:{name}>', str(value)).replace(f'<str:{name}>', str(value))
            asking = [(asked, user) for asked in [''] + ALSO_ASK.get(route, [])
                      for user in self.viewers]
            for asked, user in asking:
                response = self.as_(user).get(url + asked)
                if response.status_code != 200 or 'json' not in response.get('Content-Type', ''):
                    continue
                called += 1
                rows_seen.setdefault(route + asked, 0)
                data = json.loads(response.content)
                if (any(part in route for part in OPENS_A_MANUAL)
                        and isinstance(data, dict) and 'deadline' not in data):
                    missing.setdefault(route, set()).add(f'{user.username}: $ (opens a manual)')
                part = (EXEMPT_ASKED.get(route + asked) or EXEMPT_PARTS.get(route, (None,)))[0]
                found = _untagged(data)
                rows_seen[route + asked] += _manuals_named(data)
                for where in found:
                    if part and part in where:
                        continue
                    missing.setdefault(route + asked, set()).add(f'{user.username}: {where}')
        self.assertGreater(called, 30)
        self.assertEqual({route: sorted(paths)[:3] for route, paths in missing.items()}, {})
        # The long lists' pages really held manuals, or the walk proved nothing.
        empty = [asked for asked, n in rows_seen.items()
                 if n == 0 and any(asked == r + a for r, extra in ALSO_ASK.items() for a in extra)]
        self.assertEqual(empty, [])

    def test_the_tag_reaches_the_screen_with_its_label(self):
        """Not only a key: the owing office's Head sees the words."""
        data = self.as_(self.acc_head).get(f'/api/manuals/{self.manual.pk}/sections/').json()
        self.assertTrue(data['deadline']['label'].startswith('Submitted'), data['deadline'])

    def test_returned_work_in_the_banner_is_tagged(self):
        """Not reached by the walk above, which has nothing returned."""
        self.decide(self.proposal_id, self.bud_head, 'return', feedback='Not yet.')
        item = self.as_(self.acc_enc).get('/api/action-banner/').json()['items'][0]
        self.assertEqual(item['manual_id'], self.manual.pk)
        self.assertTrue(item['deadline']['label'].startswith('Submitted'), item['deadline'])

    def test_the_exemptions_still_exist(self):
        """A renamed route must not leave a stale exemption behind."""
        routes = {route for route, _ in _routes(urls.urlpatterns)}
        self.assertEqual((set(EXEMPT) | set(EXEMPT_PARTS) | set(ALSO_ASK) | NOT_JSON) - routes,
                         set())
