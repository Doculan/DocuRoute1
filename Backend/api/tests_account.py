"""A person's own account: name, email, password.

Also the name fix: `get_full_name()` read Django's empty first/last name
fields, so every name the screens showed was blank.
"""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import CustomUser, Office, Position, PositionAssignment

PASSWORD = "correct-horse-battery"


class AccountTests(TestCase):

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="acc_juan", password=PASSWORD, is_approved=True,
            full_name="Juan Dela Cruz", email="juan@example.edu",
        )
        office = Office.objects.create(name="Accounting Office", abbreviation="ACC")
        position = Position.objects.create(office=office, kind=Position.ENCODER)
        PositionAssignment.objects.create(
            user=self.user, position=position, starts_on=timezone.localdate(),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def patch(self, body):
        return self.client.patch('/api/auth/profile/', body, format='json')

    # -- the name fix ---------------------------------------------

    def test_get_full_name_reads_full_name(self):
        self.assertEqual(self.user.get_full_name(), "Juan Dela Cruz")

    def test_get_full_name_falls_back_to_first_and_last(self):
        other = CustomUser.objects.create_user(
            username="x", password=PASSWORD, first_name="Rosa", last_name="Tan",
        )
        self.assertEqual(other.get_full_name(), "Rosa Tan")

    def test_auth_me_now_shows_the_name(self):
        self.assertEqual(self.client.get('/api/auth/me/').data['name'],
                         "Juan Dela Cruz")

    # -- reading ----------------------------------------------------

    def test_profile_shows_name_email_and_positions(self):
        data = self.client.get('/api/auth/profile/').data
        self.assertEqual(data['username'], "acc_juan")
        self.assertEqual(data['full_name'], "Juan Dela Cruz")
        self.assertEqual(data['email'], "juan@example.edu")
        self.assertEqual(len(data['positions']), 1)
        self.assertIn("Accounting Office", data['positions'][0]['title'])

    def test_profile_needs_a_login(self):
        self.assertEqual(APIClient().get('/api/auth/profile/').status_code, 401)

    # -- changing the name and email -------------------------------

    def test_changing_the_name(self):
        response = self.patch({'full_name': '  Juan   P.  Dela Cruz '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['full_name'], "Juan P. Dela Cruz")
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Juan P. Dela Cruz")

    def test_a_blank_name_is_refused(self):
        response = self.patch({'full_name': '   '})
        self.assertEqual(response.status_code, 400)
        self.assertIn('full_name', response.data['fields'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Juan Dela Cruz")

    def test_changing_the_email(self):
        self.assertEqual(self.patch({'email': 'jdc@example.edu'}).status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'jdc@example.edu')

    def test_the_email_may_be_cleared(self):
        self.assertEqual(self.patch({'email': ''}).status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

    def test_a_bad_email_is_refused_and_nothing_is_saved(self):
        response = self.patch({'full_name': 'New Name', 'email': 'not-an-email'})
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Juan Dela Cruz")
        self.assertEqual(self.user.email, "juan@example.edu")

    def test_username_and_role_cannot_be_changed_here(self):
        self.patch({'username': 'boss', 'system_role': CustomUser.SYSTEM_ADMIN,
                    'is_approved': False})
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'acc_juan')
        self.assertEqual(self.user.system_role, CustomUser.USER)
        self.assertTrue(self.user.is_approved)

    # -- the password ------------------------------------------------

    def change(self, current, new):
        return self.client.post('/api/auth/password/', {
            'current_password': current, 'new_password': new,
        }, format='json')

    def test_changing_the_password(self):
        response = self.change(PASSWORD, 'a-much-longer-passphrase-26')
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('a-much-longer-passphrase-26'))

    def test_the_current_password_must_be_right(self):
        response = self.change('wrong', 'a-much-longer-passphrase-26')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'wrong_password')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_a_weak_password_is_refused(self):
        response = self.change(PASSWORD, '12345678')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'weak_password')

    def test_the_same_password_is_refused(self):
        self.assertEqual(self.change(PASSWORD, PASSWORD).status_code, 400)

    def test_login_returns_the_name(self):
        data = APIClient().post('/api/auth/login/', {
            'username': 'acc_juan', 'password': PASSWORD,
        }, format='json').data
        self.assertEqual(data['full_name'], "Juan Dela Cruz")
