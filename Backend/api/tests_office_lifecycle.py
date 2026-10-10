"""Office actions must preserve eligibility or provide an explicit recovery path."""
from django.test import TestCase
from rest_framework.test import APIClient

from api.models import CustomUser, Office, Position
from api.views import issue_reauth_token


class OfficeLifecycleTests(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username='admin', password='pw', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN, role='admin')
        self.staff = CustomUser.objects.create_user(username='staff', password='pw', is_approved=True)
        self.parent = Office.objects.create(name='Parent')
        self.office = Office.objects.create(name='Working Office', parent=self.parent)
        self.retired = Office.objects.create(name='Retired', is_active=False)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.client.credentials(HTTP_X_REAUTH_TOKEN=issue_reauth_token(self.admin))
        self.anon = APIClient()

    def action(self, office, action, data=None):
        return self.client.post(f'/api/org/offices/{office.id}/{action}/', data or {}, format='json')

    def eligible_ids(self):
        signup = {o['id'] for o in self.anon.get('/api/auth/offices/').data}
        assignment = {o['id'] for o in self.client.get('/api/org/offices/').data['offices']}
        self.assertEqual(signup, assignment)
        return signup

    def assign(self, office):
        return self.client.post(f'/api/org/people/{self.staff.id}/assign/',
                                {'office_id': office.id, 'kind': Position.ENCODER}, format='json')

    def test_reactivation_restores_signup_and_staff_assignment(self):
        self.assertNotIn(self.retired.id, self.eligible_ids())
        self.assertEqual(self.assign(self.retired).status_code, 409)
        response = self.action(self.retired, 'reactivate')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(self.retired.id, self.eligible_ids())
        self.assertEqual(self.assign(self.retired).status_code, 201)
        response = self.anon.post('/api/auth/register/', {
            'username': 'applicant', 'password': 'test-password',
            'requested_office_id': self.retired.id}, format='json')
        self.assertEqual(response.status_code, 201, response.data)

    def test_reactivation_requires_password_and_system_admin(self):
        self.client.credentials()
        self.assertEqual(self.action(self.retired, 'reactivate').status_code, 403)
        self.client.force_authenticate(self.staff)
        self.client.credentials(HTTP_X_REAUTH_TOKEN=issue_reauth_token(self.staff))
        self.assertEqual(self.action(self.retired, 'reactivate').status_code, 403)
        self.retired.refresh_from_db()
        self.assertFalse(self.retired.is_active)

    def test_moving_and_renaming_do_not_retire_an_office(self):
        response = self.client.patch(f'/api/org/offices/{self.office.id}/',
                                     {'parent_id': None, 'name': 'Renamed Office'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['is_active'])
        self.assertIn(self.office.id, self.eligible_ids())
        self.assertEqual(self.assign(self.office).status_code, 201)

    def test_merged_source_stays_retired_and_successor_remains_eligible(self):
        response = self.action(self.office, 'merge', {'into': self.parent.id})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(self.office.id, self.eligible_ids())
        self.assertIn(self.parent.id, self.eligible_ids())
        self.assertEqual(self.assign(self.office).status_code, 409)
        self.assertEqual(self.assign(self.parent).status_code, 201)
        self.assertEqual(self.action(self.office, 'reactivate').data['reason'], 'merged')
        detail = self.client.get(f'/api/org/offices/{self.office.id}/').data
        self.assertEqual(detail['merged_into_id'], self.parent.id)
        self.assertEqual(self.client.patch(f'/api/org/offices/{self.office.id}/',
                         {'name': 'Changed'}, format='json').status_code, 409)

    def test_archived_offices_cannot_be_merge_destinations(self):
        path = f'/api/org/offices/{self.office.id}/merge/'
        preview = self.client.get(path, {'into': self.retired.id})
        self.assertEqual(preview.status_code, 409)
        self.assertEqual(preview.data['reason'], 'target_inactive')
        self.assertEqual(self.action(self.office, 'merge', {'into': self.retired.id}).status_code, 409)
        self.office.refresh_from_db()
        self.assertTrue(self.office.is_active)
        self.assertIsNone(self.office.merged_into_id)

    def test_cannot_remerge_a_historical_office(self):
        self.action(self.office, 'merge', {'into': self.parent.id})
        next_office = Office.objects.create(name='Another office')
        response = self.action(self.office, 'merge', {'into': next_office.id})
        self.assertEqual(response.status_code, 409)
        self.office.refresh_from_db()
        self.assertEqual(self.office.merged_into_id, self.parent.id)

    def test_inactive_parent_blocks_creation_and_moving(self):
        response = self.client.post('/api/org/offices/',
                                    {'name': 'New child', 'parent_id': self.retired.id}, format='json')
        self.assertEqual(response.status_code, 400)
        for parent_id in (self.retired.id, 'invalid'):
            response = self.client.patch(f'/api/org/offices/{self.office.id}/',
                                         {'parent_id': parent_id}, format='json')
            self.assertEqual(response.status_code, 400)
        self.office.refresh_from_db()
        self.assertEqual(self.office.parent_id, self.parent.id)

    def test_child_can_be_moved_before_reactivation_when_parent_is_retired(self):
        self.action(self.office, 'deactivate')
        self.action(self.parent, 'deactivate')
        response = self.action(self.office, 'reactivate')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'parent_inactive')
        response = self.client.patch(f'/api/org/offices/{self.office.id}/',
                                     {'parent_id': None}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_active'])
        self.assertEqual(self.action(self.office, 'reactivate').status_code, 200)
        self.assertIn(self.office.id, self.eligible_ids())
