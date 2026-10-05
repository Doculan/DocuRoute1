"""Applying to an office at sign-up.

An application, not a post: the requested office grants nothing, and the
system admin assigns the actual position on approval.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import CustomUser, Office

PASSWORD = "correct-horse-battery"


class SignupOfficeTests(TestCase):

    def setUp(self):
        self.accounting = Office.objects.create(name='Accounting Office', abbreviation='ACC')
        self.budget = Office.objects.create(name='Budget Office', abbreviation='BUD')
        self.closed = Office.objects.create(name='Old Office', abbreviation='OLD',
                                            is_active=False)
        self.anon = APIClient()

    def register(self, **extra):
        body = {'username': 'juan', 'password': PASSWORD, 'full_name': 'Juan Cruz'}
        body.update(extra)
        return self.anon.post('/api/auth/register/', body, format='json')

    def test_the_list_is_open_and_shows_active_offices_only(self):
        data = self.anon.get('/api/auth/offices/').data
        self.assertEqual([o['name'] for o in data], ['Accounting Office', 'Budget Office'])
        self.assertEqual(set(data[0]), {'id', 'name'})

    def test_applying_to_an_office(self):
        self.assertEqual(self.register(requested_office_id=self.budget.id).status_code, 201)
        user = CustomUser.objects.get(username='juan')
        self.assertEqual(user.requested_office, self.budget)
        self.assertFalse(user.is_approved)
        # An application grants nothing.
        self.assertFalse(user.position_assignments.exists())

    def test_it_is_optional(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertIsNone(CustomUser.objects.get(username='juan').requested_office)

    def test_an_inactive_or_unknown_office_is_refused(self):
        for office_id in (self.closed.id, 99999, 'abc'):
            response = self.register(requested_office_id=office_id)
            self.assertEqual(response.status_code, 400, office_id)
        self.assertFalse(CustomUser.objects.filter(username='juan').exists())

    def test_the_admin_sees_it_on_both_approval_screens(self):
        self.register(requested_office_id=self.accounting.id)
        admin = CustomUser.objects.create_user(
            username='admin', password=PASSWORD, is_approved=True, role='admin',
            system_role=CustomUser.SYSTEM_ADMIN,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        pending = client.get('/api/admin/pending-users/').data
        self.assertEqual(pending[0]['requested_office'], 'Accounting Office')
        people = client.get('/api/org/people/?filter=pending').data['people']
        self.assertEqual(people[0]['requested_office']['name'], 'Accounting Office')
