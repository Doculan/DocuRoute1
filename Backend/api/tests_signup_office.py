"""Applying to an office at sign-up.

Choosing an office grants nothing before approval. Approval creates the
requested Encoder or Head assignment; an occupied Head post refuses approval.

"Office not listed" replaces "not sure": the applicant may type the office's
name (60 characters, optional), the admin assigns the real office by hand,
and nothing is created from the typed name.
"""

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch
from rest_framework.test import APIClient

from api.models import CustomUser, Office, Position, PositionAssignment
from api.views import issue_reauth_token

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
        self.assertEqual(set(data[0]), {'id', 'name', 'group'})

    def test_the_list_is_grouped_by_parent_branch(self):
        vp = Office.objects.create(name='Office of the VP for Finance', abbreviation='VPF')
        self.budget.parent = vp
        self.budget.save(update_fields=['parent'])
        groups = {o['name']: o['group'] for o in self.anon.get('/api/auth/offices/').data}
        self.assertEqual(groups['Budget Office'], 'Office of the VP for Finance')
        # Top-level offices have no parent branch to sit under.
        self.assertIsNone(groups['Accounting Office'])
        self.assertIsNone(groups['Office of the VP for Finance'])

    def test_office_not_listed_keeps_the_typed_name(self):
        response = self.register(requested_office_name='  Records Section  ')
        self.assertEqual(response.status_code, 201)
        user = CustomUser.objects.get(username='juan')
        self.assertIsNone(user.requested_office)
        self.assertEqual(user.requested_office_name, 'Records Section')
        # Nothing is created from what was typed.
        self.assertFalse(Office.objects.filter(name='Records Section').exists())

    def test_the_typed_name_is_limited_to_sixty_characters(self):
        response = self.register(requested_office_name='x' * 61)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'office_name_too_long')
        self.assertFalse(CustomUser.objects.filter(username='juan').exists())
        self.assertEqual(self.register(requested_office_name='x' * 60).status_code, 201)

    def test_a_typed_name_is_dropped_when_an_office_is_chosen(self):
        self.register(requested_office_id=self.budget.id, requested_office_name='Records')
        user = CustomUser.objects.get(username='juan')
        self.assertEqual(user.requested_office, self.budget)
        self.assertEqual(user.requested_office_name, '')

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

    def test_head_request_is_stored_without_granting_a_post(self):
        response = self.register(requested_office_id=self.budget.id, requested_position_kind='head')
        self.assertEqual(response.status_code, 201)
        user = CustomUser.objects.get(username='juan')
        self.assertEqual(user.requested_position_kind, Position.HEAD)
        self.assertFalse(user.is_approved)
        self.assertFalse(user.position_assignments.exists())

    def test_signup_accepts_only_encoder_or_head(self):
        for kind in ('imr', 'document_custodian', 'admin', '', None):
            response = self.register(requested_position_kind=kind)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data['reason'], 'invalid_position')
        self.assertFalse(CustomUser.objects.filter(username='juan').exists())

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

    def test_the_admin_sees_office_not_listed_and_the_typed_name(self):
        self.register(requested_office_name='Records Section')
        admin = CustomUser.objects.create_user(
            username='admin', password=PASSWORD, is_approved=True, role='admin',
            system_role=CustomUser.SYSTEM_ADMIN,
        )
        client = APIClient()
        client.force_authenticate(user=admin)
        pending = client.get('/api/admin/pending-users/').data[0]
        self.assertIsNone(pending['requested_office'])
        self.assertEqual(pending['requested_office_name'], 'Records Section')
        person = client.get('/api/org/people/?filter=pending').data['people'][0]
        self.assertIsNone(person['requested_office'])
        self.assertEqual(person['requested_office_name'], 'Records Section')


class ApprovalPlacesThemTests(TestCase):
    """Password-confirmed approval grants the chosen office and position.
    An occupied Head post leaves the whole application pending."""

    def setUp(self):
        self.office = Office.objects.create(name='Accounting Office', abbreviation='ACC')
        self.admin = CustomUser.objects.create_user(
            username='admin', password=PASSWORD, is_approved=True, role='admin',
            system_role=CustomUser.SYSTEM_ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.client.credentials(HTTP_X_REAUTH_TOKEN=issue_reauth_token(self.admin))

    def applicant(self, username='juan', office=True, kind=Position.ENCODER):
        return CustomUser.objects.create_user(
            username=username, password=PASSWORD,
            requested_office=self.office if office else None,
            requested_position_kind=kind,
        )

    def current_posts(self, user):
        from api.models import Position
        return [(a.position.office, a.position.kind)
                for a in user.position_assignments.filter(ends_on__isnull=True)]

    def test_people_screen_approval_makes_them_an_encoder_there(self):
        from api.models import Position
        user = self.applicant()
        response = self.client.post(f'/api/org/people/{user.id}/approve/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['placed'])
        user.refresh_from_db()
        self.assertTrue(user.is_approved)
        self.assertEqual(self.current_posts(user), [(self.office, Position.ENCODER)])
        self.assertEqual(user.position_assignments.get().assigned_by, self.admin)

    def test_users_screen_approval_does_the_same(self):
        from api.models import Position
        user = self.applicant()
        response = self.client.patch(f'/api/admin/approve-user/{user.id}/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Encoder at Accounting Office', response.data['message'])
        self.assertEqual(self.current_posts(user), [(self.office, Position.ENCODER)])

    def test_office_not_listed_leaves_it_to_the_admin(self):
        user = self.applicant(office=False)
        user.requested_office_name = 'Records Section'
        user.save(update_fields=['requested_office_name'])
        response = self.client.post(f'/api/org/people/{user.id}/approve/', {}, format='json')
        self.assertFalse(response.data['placed'])
        self.assertIn('Office not listed', response.data['note'])
        self.assertIn('"Records Section"', response.data['note'])
        self.assertIn('assign one by hand', response.data['note'])
        self.assertEqual(self.current_posts(user), [])

    def test_office_not_listed_reaches_no_manual_until_assigned(self):
        from api.models import Manual, ManualSeries, ManualSeriesOffice, OfficeLink
        vp = Office.objects.create(name='VP', is_approving_level=True)
        series = ManualSeries.objects.create(code='FAM', title='Finance', owning_office=vp)
        ManualSeriesOffice.objects.create(series=series, office=self.office,
                                          relationship=OfficeLink.CONCURRING)
        manual = Manual.objects.create(title='FAM 6.02', series=series)
        user = self.applicant(office=False)
        user.requested_office_name = 'Records Section'
        user.save(update_fields=['requested_office_name'])
        self.client.post(f'/api/org/people/{user.id}/approve/', {}, format='json')
        user.refresh_from_db()
        self.assertTrue(user.is_approved)

        staff = APIClient()
        staff.force_authenticate(user=user)
        for path in ('/api/staff/manuals/', '/api/staff/sections/', '/api/proposals/'):
            response = staff.get(path)
            self.assertEqual(response.status_code, 403, path)
            self.assertEqual(response.data['reason'], 'no_position', path)
        response = staff.get(f'/api/manuals/{manual.id}/sections/')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['error'], 'Access denied')

        # Assigned by hand: now the office's documents open.
        position = Position.objects.create(office=self.office, kind=Position.ENCODER)
        PositionAssignment.objects.create(user=user, position=position,
                                          starts_on=timezone.localdate())
        self.assertEqual([m['title'] for m in staff.get('/api/staff/manuals/?page=1').data['results']],
                         ['FAM 6.02'])
        self.assertEqual(staff.get(f'/api/manuals/{manual.id}/sections/').status_code, 200)

    def test_a_retired_office_is_not_assigned(self):
        user = self.applicant()
        self.office.is_active = False
        self.office.save(update_fields=['is_active'])
        response = self.client.post(f'/api/org/people/{user.id}/approve/', {}, format='json')
        self.assertFalse(response.data['placed'])
        self.assertEqual(self.current_posts(user), [])

    def test_approving_twice_does_not_add_a_second_post(self):
        user = self.applicant()
        self.client.post(f'/api/org/people/{user.id}/approve/', {}, format='json')
        self.client.post(f'/api/org/people/{user.id}/approve/', {}, format='json')
        self.assertEqual(len(self.current_posts(user)), 1)

    def test_the_approver_sees_every_detail_but_the_password(self):
        self.applicant()
        row = self.client.get('/api/admin/pending-users/').data[0]
        self.assertEqual(set(row), {'id', 'username', 'email', 'full_name',
                                    'requested_office', 'requested_office_name', 'date_joined',
                                    'requested_position_kind', 'requested_position_label', 'approval_warning'})
        person = self.client.get('/api/org/people/?filter=pending').data['people'][0]
        self.assertEqual(set(person), {
            'id', 'username', 'email', 'full_name', 'requested_office',
            'requested_office_name', 'date_joined',
            'requested_position_kind', 'requested_position_label', 'approval_warning',
            'system_role', 'is_approved', 'is_active', 'current_positions', 'past_positions',
        })

    def test_repeat_approval_does_not_restore_a_post_ended_by_admin(self):
        user = self.applicant()
        self.client.post(f'/api/org/people/{user.id}/approve/', {}, format='json')
        user.position_assignments.update(starts_on=timezone.localdate() - timedelta(days=2),
                                         ends_on=timezone.localdate() - timedelta(days=1))
        response = self.client.patch(f'/api/admin/approve-user/{user.id}/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(user.position_assignments.count(), 1)
        self.assertEqual(self.current_posts(user), [])

    def test_an_inactive_position_is_not_reactivated_by_signup_approval(self):
        position = Position.objects.create(office=self.office, kind=Position.ENCODER, is_active=False)
        user = self.applicant()
        response = self.client.post(f'/api/org/people/{user.id}/approve/', {}, format='json')
        position.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(position.is_active)
        self.assertFalse(response.data['placed'])
        self.assertEqual(self.current_posts(user), [])

    def test_an_existing_head_is_preserved_and_not_reported_as_encoder(self):
        user = self.applicant(kind=Position.HEAD)
        position = Position.objects.create(office=self.office, kind=Position.HEAD)
        PositionAssignment.objects.create(user=user, position=position, starts_on=timezone.localdate())
        response = self.client.patch(f'/api/admin/approve-user/{user.id}/', {}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Encoder', response.data['message'])
        self.assertEqual(self.current_posts(user), [(self.office, Position.HEAD)])

    def test_placement_failure_rolls_back_account_approval(self):
        from api.people_views import approve
        user = self.applicant()
        with patch('api.people_views.place_in_requested_office', side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):
                approve(user, self.admin)
        user.refresh_from_db()
        self.assertFalse(user.is_approved)
        self.assertEqual(self.current_posts(user), [])

    def test_both_approval_routes_require_the_admin_password_token(self):
        self.client.credentials()
        user = self.applicant(kind=Position.HEAD)
        for path, method in self.approval_routes(user):
            response = getattr(self.client, method)(path, {'full_name': 'Must not change'}, format='json')
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.data['reason'], 'reauth_required')
        user.refresh_from_db()
        self.assertFalse(user.is_approved)
        self.assertEqual(self.current_posts(user), [])

    def approval_routes(self, user):
        return [(f'/api/org/people/{user.id}/approve/', 'post'),
                (f'/api/admin/approve-user/{user.id}/', 'patch')]

    def test_a_vacant_head_post_is_assigned_by_either_screen(self):
        for i, method in enumerate(('post', 'patch')):
            office = Office.objects.create(name=f'Vacant {i}')
            user = self.applicant(username=f'head{i}', kind=Position.HEAD)
            user.requested_office = office
            user.save(update_fields=['requested_office'])
            path = self.approval_routes(user)[i][0]
            response = getattr(self.client, method)(path, {}, format='json')
            self.assertEqual(response.status_code, 200)
            user.refresh_from_db()
            self.assertTrue(user.is_approved)
            self.assertEqual(self.current_posts(user), [(office, Position.HEAD)])
            self.assertEqual(user.position_assignments.get().assigned_by, self.admin)

    def test_occupied_head_warns_on_both_screens_and_refuses_both_routes(self):
        incumbent = self.applicant(username='incumbent')
        position = Position.objects.create(office=self.office, kind=Position.HEAD)
        PositionAssignment.objects.create(user=incumbent, position=position, starts_on=timezone.localdate())
        user = self.applicant(kind=Position.HEAD)
        pending = self.client.get('/api/admin/pending-users/').data
        person = next(p for p in pending if p['id'] == user.id)
        self.assertIn('already has a Head', person['approval_warning'])
        people = self.client.get('/api/org/people/?filter=pending').data['people']
        self.assertIn('already has a Head', next(p for p in people if p['id'] == user.id)['approval_warning'])
        for path, method in self.approval_routes(user):
            response = getattr(self.client, method)(path, {}, format='json')
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data['reason'], 'already_held')
        user.refresh_from_db()
        self.assertFalse(user.is_approved)
        self.assertEqual(self.current_posts(user), [])
        self.assertEqual(position.assignments.count(), 1)

    def test_two_pending_head_applicants_cannot_both_be_accepted(self):
        first = self.applicant(username='first', kind=Position.HEAD)
        second = self.applicant(username='second', kind=Position.HEAD)
        self.assertEqual(self.client.post(self.approval_routes(first)[0][0], {}).status_code, 200)
        response = self.client.patch(self.approval_routes(second)[1][0], {})
        self.assertEqual(response.status_code, 409)
        second.refresh_from_db()
        self.assertFalse(second.is_approved)

    def test_database_constraint_still_refuses_a_head_if_the_precheck_is_bypassed(self):
        incumbent = self.applicant(username='incumbent', kind=Position.HEAD)
        self.client.post(self.approval_routes(incumbent)[0][0], {})
        user = self.applicant(kind=Position.HEAD)
        with patch('api.people_views._head_is_held', return_value=False):
            response = self.client.post(self.approval_routes(user)[0][0],
                                        {'full_name': 'Must not change'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'already_held')
        user.refresh_from_db()
        self.assertFalse(user.is_approved)
        self.assertEqual(user.full_name, '')
        self.assertEqual(self.current_posts(user), [])
        self.assertEqual(self.current_posts(incumbent), [(self.office, Position.HEAD)])

    def test_head_with_a_future_end_date_still_blocks_acceptance(self):
        incumbent = self.applicant(username='incumbent', kind=Position.HEAD)
        position = Position.objects.create(office=self.office, kind=Position.HEAD)
        PositionAssignment.objects.create(user=incumbent, position=position,
            starts_on=timezone.localdate(), ends_on=timezone.localdate() + timedelta(days=2))
        user = self.applicant(kind=Position.HEAD)
        response = self.client.post(self.approval_routes(user)[0][0], {})
        self.assertEqual(response.status_code, 409)
        user.refresh_from_db()
        self.assertFalse(user.is_approved)
        self.assertEqual(self.current_posts(user), [])

    def test_approval_uses_saved_choice_not_a_submitted_override(self):
        user = self.applicant()
        response = self.client.post(self.approval_routes(user)[0][0],
                                    {'requested_position_kind': 'head'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.current_posts(user), [(self.office, Position.ENCODER)])

    def test_rejecting_a_pending_head_applicant_never_assigns_them(self):
        user = self.applicant(kind=Position.HEAD)
        response = self.client.delete(f'/api/admin/reject-user/{user.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CustomUser.objects.filter(pk=user.id).exists())
        self.assertFalse(PositionAssignment.objects.filter(position__office=self.office).exists())

    def test_stale_rejection_cannot_delete_an_approved_account(self):
        user = self.applicant(kind=Position.HEAD)
        self.client.post(self.approval_routes(user)[0][0], {})
        response = self.client.delete(f'/api/admin/reject-user/{user.id}/')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'already_approved')
        self.assertTrue(CustomUser.objects.filter(pk=user.id, is_approved=True).exists())
        self.assertEqual(self.current_posts(user), [(self.office, Position.HEAD)])

    def test_staff_cannot_approve_or_read_applicant_details(self):
        user = self.applicant()
        staff = CustomUser.objects.create_user(username='staff', password=PASSWORD, is_approved=True)
        self.client.force_authenticate(user=staff)
        for path, method in (
            (f'/api/org/people/{user.id}/approve/', 'post'),
            (f'/api/admin/approve-user/{user.id}/', 'patch'),
            ('/api/admin/pending-users/', 'get'),
            ('/api/org/people/?filter=pending', 'get'),
        ):
            with self.subTest(path=path):
                self.assertEqual(getattr(self.client, method)(path).status_code, 403)
        user.refresh_from_db()
        self.assertFalse(user.is_approved)
        self.assertEqual(self.current_posts(user), [])
