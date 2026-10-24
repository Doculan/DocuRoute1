"""Announcements (Phase 3A): information, always a banner, never deleted.

- **Who sees one is explicit**: everyone, or chosen offices - an empty
  office list is refused rather than read as everyone. A target can reach
  every office beneath it that concurs on a document.
- **Dismissal is per person**; expiry and deactivation hide it for all.
- **No DELETE**: deactivating keeps the record of what was posted.

Tests that expect an error assert the reason.
"""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    Announcement, AnnouncementDismissal, CustomUser, Manual,
    ManualSeries, ManualSeriesOffice, Office, OfficeLink, Position, PositionAssignment,
)


class AnnouncementFixture(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        self.vp = Office.objects.create(name='VP Office', is_approving_level=True)
        self.finance = Office.objects.create(name='Finance Office', parent=self.vp)
        self.cash = Office.objects.create(name='Cash Unit', parent=self.finance)
        self.registry = Office.objects.create(name='Registry', parent=self.vp)
        series = ManualSeries.objects.create(code='FAM', title='Finance', owning_office=self.vp)
        Manual.objects.create(title='FAM 1', series=series)
        for office in (self.finance, self.cash):
            ManualSeriesOffice.objects.create(series=series, office=office,
                                              relationship=OfficeLink.CONCURRING)
        self.admin = CustomUser.objects.create_user(
            username='admin', password='pw', role='admin', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN)
        self.finance_staff = self.person('fin', self.finance)
        self.cash_staff = self.person('cash', self.cash)
        self.registry_staff = self.person('reg', self.registry)

    def person(self, username, office):
        user = CustomUser.objects.create_user(username=username, password='pw', is_approved=True)
        position, _ = Position.objects.get_or_create(office=office, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=user, position=position, starts_on=self.today)
        return user

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def post(self, **body):
        body.setdefault('title', 'Audit week')
        return self.as_(self.admin).post('/api/admin/announcements/', body, format='json')

    def banner(self, user):
        return [i['title'] for i in self.as_(user).get('/api/announcement-banner/').data['items']]


class PostingThem(AnnouncementFixture):

    def test_for_everyone_by_default(self):
        response = self.post(body='Bring your manuals.')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['audience'], 'all')
        for user in (self.finance_staff, self.registry_staff):
            self.assertEqual(self.banner(user), ['Audit week'])

    def test_an_empty_office_list_never_means_everyone(self):
        response = self.post(audience='offices', targets=[])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'no_offices')
        self.assertFalse(Announcement.objects.exists())

    def test_a_targeted_one_reaches_only_its_offices(self):
        self.post(audience='offices', targets=[{'office_id': self.finance.id}])
        self.assertEqual(self.banner(self.finance_staff), ['Audit week'])
        self.assertEqual(self.banner(self.cash_staff), [])
        self.assertEqual(self.banner(self.registry_staff), [])

    def test_everything_beneath_reaches_the_offices_below(self):
        self.post(audience='offices',
                  targets=[{'office_id': self.vp.id, 'include_descendants': True}])
        self.assertEqual(self.banner(self.finance_staff), ['Audit week'])
        self.assertEqual(self.banner(self.cash_staff), ['Audit week'])
        # The Registry concurs on no document, so "beneath" does not reach it.
        self.assertEqual(self.banner(self.registry_staff), [])

    def test_bad_input_is_refused_with_the_reason(self):
        for body, reason in (({'title': ''}, 'title_required'),
                             ({'expires_on': 'soon'}, 'invalid_date'),
                             ({'audience': 'some'}, 'invalid_audience'),
                             ({'audience': 'offices', 'targets': [{'office_id': 99999}]},
                              'invalid_office')):
            with self.subTest(reason=reason):
                response = self.post(**body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['reason'], reason)

    def test_staff_cannot_manage_announcements(self):
        response = self.as_(self.finance_staff).post(
            '/api/admin/announcements/', {'title': 'x'}, format='json')
        self.assertEqual(response.status_code, 403)


class SeeingThem(AnnouncementFixture):

    def test_expired_and_deactivated_ones_are_hidden(self):
        Announcement.objects.create(title='Expired', created_by=self.admin,
                                    expires_on=self.today - datetime.timedelta(days=1))
        Announcement.objects.create(title='Off', created_by=self.admin, active=False)
        Announcement.objects.create(title='Today', created_by=self.admin, expires_on=self.today)
        self.assertEqual(self.banner(self.finance_staff), ['Today'])

    def test_newest_first_and_dismissal_is_per_person(self):
        first = Announcement.objects.create(title='First', created_by=self.admin)
        Announcement.objects.create(title='Second', created_by=self.admin)
        self.assertEqual(self.banner(self.finance_staff), ['Second', 'First'])

        self.as_(self.finance_staff).post(f'/api/staff/announcements/{first.id}/dismiss/')

        self.assertEqual(self.banner(self.finance_staff), ['Second'])
        self.assertEqual(self.banner(self.cash_staff), ['Second', 'First'])
        self.assertEqual(AnnouncementDismissal.objects.count(), 1)

    def test_deactivating_records_who_and_keeps_the_row(self):
        announcement = Announcement.objects.create(title='Notice', created_by=self.admin)
        response = self.as_(self.admin).patch(f'/api/admin/announcements/{announcement.id}/',
                                              {'active': False}, format='json')
        self.assertEqual(response.status_code, 200)
        announcement.refresh_from_db()
        self.assertEqual((announcement.active, announcement.deactivated_by),
                         (False, self.admin))
        self.assertIsNotNone(announcement.deactivated_at)

    def test_there_is_no_delete(self):
        announcement = Announcement.objects.create(title='Notice', created_by=self.admin)
        response = self.as_(self.admin).delete(f'/api/admin/announcements/{announcement.id}/')
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Announcement.objects.filter(pk=announcement.pk).exists())

    def test_the_admin_list_counts_dismissals_and_pages(self):
        notice = Announcement.objects.create(title='Notice', created_by=self.admin)
        AnnouncementDismissal.objects.create(announcement=notice, user=self.cash_staff)
        data = self.as_(self.admin).get('/api/admin/announcements/').data
        self.assertEqual((data['count'], data['announcements'][0]['dismissals']), (1, 1))
        expired = self.as_(self.admin).get('/api/admin/announcements/', {'status': 'expired'})
        self.assertEqual(expired.data['count'], 0)
