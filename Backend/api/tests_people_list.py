"""The admin's People list, paged (after Checkpoint 3C-2).

The rules with teeth:

- **50 a page, counts first, sign-ups on top**, whatever the filter.
- **Every filter on the server**: name or username, office, branch (the
  office and everything beneath it), status, position (or none).
- **The same warnings**: the Head-conflict check, made for a page at
  once, says what the per-applicant check said.
- **Queries do not grow with the page.**

Tests that expect an error assert the reason.
"""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import CustomUser, Office, Position, PositionAssignment
from api.people_views import application_details


class PeopleFixture(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        self.admin = CustomUser.objects.create_user(
            username='admin', password='pw', is_approved=True, role='admin',
            system_role=CustomUser.SYSTEM_ADMIN)
        self.vp = Office.objects.create(name='VP Office', is_approving_level=True)
        self.acc = Office.objects.create(name='Accounting Office', parent=self.vp)
        self.cash = Office.objects.create(name='Cash Unit', parent=self.acc)
        self.reg = Office.objects.create(name='Registry')
        self.acc_head = self.person('acc_head', self.acc, Position.HEAD, full_name='Teodoro Balangiga')
        self.cash_enc = self.person('cash_enc', self.cash, Position.ENCODER)
        self.reg_enc = self.person('reg_enc', self.reg, Position.ENCODER)
        self.idle = CustomUser.objects.create_user(username='idle', password='pw', is_approved=True)
        self.gone = CustomUser.objects.create_user(username='gone', password='pw', is_approved=True,
                                                   is_active=False)
        self.applicant = CustomUser.objects.create_user(
            username='applicant', password='pw', is_approved=False, requested_office=self.acc,
            requested_position_kind=Position.HEAD)

    def person(self, username, office, kind, **extra):
        user = CustomUser.objects.create_user(username=username, password='pw', is_approved=True,
                                              **extra)
        position, _ = Position.objects.get_or_create(office=office, kind=kind)
        PositionAssignment.objects.create(user=user, position=position, starts_on=self.today)
        return user

    def get(self, query=''):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client.get(f'/api/org/people/{query}')

    def names(self, query):
        response = self.get(query)
        self.assertEqual(response.status_code, 200, response.data)
        return sorted(p['username'] for p in response.data['people'])


class CountsFirst(PeopleFixture):

    def test_the_counts(self):
        counts = self.get().data['counts']
        self.assertEqual(counts, {'all': 7, 'active': 5, 'pending': 1,
                                  'awaiting_position': 2, 'inactive': 1})

    def test_sign_ups_on_top_of_any_list(self):
        data = self.get('?status=active&q=reg')
        self.assertEqual([p['username'] for p in data.data['pending_signups']], ['applicant'])
        self.assertEqual(self.names('?status=active&q=reg'), ['reg_enc'])


class FilteredOnTheServer(PeopleFixture):

    def test_status(self):
        self.assertEqual(self.names('?status=pending'), ['applicant'])
        self.assertEqual(self.names('?status=inactive'), ['gone'])
        self.assertEqual(self.names('?status=awaiting_position'), ['admin', 'idle'])
        self.assertEqual(self.names('?filter=pending'), ['applicant'])    # the older name

    def test_name_or_username(self):
        self.assertEqual(self.names('?q=balang'), ['acc_head'])
        self.assertEqual(self.names('?q=CASH'), ['cash_enc'])

    def test_office_and_branch(self):
        self.assertEqual(self.names(f'?office={self.acc.pk}'), ['acc_head'])
        self.assertEqual(self.names(f'?branch={self.acc.pk}'), ['acc_head', 'cash_enc'])
        self.assertEqual(self.names(f'?branch={self.vp.pk}'), ['acc_head', 'cash_enc'])

    def test_position(self):
        self.assertEqual(self.names('?position=encoder'), ['cash_enc', 'reg_enc'])
        self.assertEqual(self.names('?position=head'), ['acc_head'])
        self.assertEqual(self.names('?position=none&status=active'), ['admin', 'idle'])

    def test_refusals_name_the_reason(self):
        for query, reason in (('?status=gone', 'invalid_status'),
                              ('?office=x', 'invalid_office'),
                              ('?branch=x', 'invalid_branch'),
                              ('?position=boss', 'invalid_position'),
                              ('?page=0', 'invalid_page')):
            response = self.get(query)
            self.assertEqual((response.status_code, response.data['reason']), (400, reason), query)


class PagedAndFixed(PeopleFixture):

    def more(self, n, start=0):
        CustomUser.objects.bulk_create([
            CustomUser(username=f'user{i:04}', is_approved=True) for i in range(start, start + n)])
        for user in CustomUser.objects.filter(username__startswith='user'):
            if not user.position_assignments.exists():
                position, _ = Position.objects.get_or_create(office=self.reg, kind=Position.ENCODER)
                PositionAssignment.objects.create(user=user, position=position, starts_on=self.today)

    def test_fifty_a_page(self):
        self.more(60)
        first = self.get('?status=active').data
        self.assertEqual((first['count'], first['pages'], len(first['people'])), (65, 2, 50))
        second = self.get('?status=active&page=2').data
        self.assertEqual(len(second['people']), 15)

    def test_queries_do_not_grow_with_the_page(self):
        def queries(query):
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.get(query).status_code, 200)
            return len(ctx)
        self.more(5)
        few = [queries(q) for q in ('', '?status=active', f'?branch={self.vp.pk}')]
        self.more(40, start=5)
        many = [queries(q) for q in ('', '?status=active', f'?branch={self.vp.pk}')]
        self.assertEqual(many, few)


class TheSameWarnings(PeopleFixture):

    def test_the_head_conflict_reads_as_before(self):
        row = [p for p in self.get('?status=pending').data['people']][0]
        self.assertEqual(row['approval_warning'], application_details(self.applicant)['approval_warning'])
        self.assertIn('already has a Head', row['approval_warning'])
