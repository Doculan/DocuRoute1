"""Merging and splitting sections to correct extraction.

Allowed only before the document is under control: no recorded status,
and no request has touched the sections. Admin only, password again,
recorded in history, never a revision.
"""

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    CustomUser, DocumentStatus, Manual, ManualSection, Office, Proposal,
    ProposalVersion, SectionChange, SectionHistory,
)
from api.views import issue_reauth_token

PASSWORD = "correct-horse-battery"


class StructureTests(TestCase):

    def setUp(self):
        self.admin = CustomUser.objects.create_user(
            username='admin', password=PASSWORD, is_approved=True, role='admin',
            system_role=CustomUser.SYSTEM_ADMIN,
        )
        self.manual = Manual.objects.create(title='FAM 6.02')
        self.revision_before = self.manual.revision
        make = lambda order, subtitle, content, parent=None: ManualSection.objects.create(
            manual=self.manual, order=order, subtitle=subtitle, content=content,
            parent=parent, tag='POLICY',
        )
        self.a = make(0, '3.0 POLICIES', 'The Cashier shall release the cheque.')
        self.b = make(1, '3.1 Release', 'Within five days of approval.')
        self.c = make(2, '4.0 PROCEDURES',
                      'The staff verifies the request.\n4.1 Filing\nThe clerk files it.')
        self.c_child = make(3, '4.0.1 Note', 'A note under procedures.', parent=self.b)

        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def post(self, path, body=None, user=None, token=True):
        user = user or self.admin
        client = APIClient()
        client.force_authenticate(user=user)
        headers = {'HTTP_X_REAUTH_TOKEN': issue_reauth_token(user)} if token else {}
        return client.post(path, body or {}, format='json', **headers)

    # -- merge ------------------------------------------------------

    def test_merging_joins_the_next_section_and_keeps_its_heading(self):
        response = self.post(f'/api/sections/{self.a.id}/merge-next/',
                             {'reason': 'Split by extraction.'})
        self.assertEqual(response.status_code, 200, response.data)
        self.a.refresh_from_db()
        self.assertEqual(
            self.a.content,
            'The Cashier shall release the cheque.\n\n3.1 Release\n\n'
            'Within five days of approval.',
        )
        self.assertFalse(ManualSection.objects.filter(pk=self.b.pk).exists())
        self.assertEqual(self.a.version, 2)

    def test_the_next_sections_children_move_up_not_away(self):
        self.post(f'/api/sections/{self.a.id}/merge-next/')
        self.c_child.refresh_from_db()
        self.assertEqual(self.c_child.parent_id, self.a.id)

    def test_order_is_renumbered(self):
        self.post(f'/api/sections/{self.a.id}/merge-next/')
        orders = list(self.manual.sections.order_by('order').values_list('order', flat=True))
        self.assertEqual(orders, [0, 1, 2])

    def test_merging_is_recorded_and_is_not_a_revision(self):
        self.post(f'/api/sections/{self.a.id}/merge-next/', {'reason': 'Split by extraction.'})
        entry = SectionHistory.objects.get(section=self.a)
        self.assertEqual(entry.source, 'structure')
        self.assertEqual(entry.edited_by, self.admin)
        self.assertEqual(entry.content, 'The Cashier shall release the cheque.')
        self.assertIn('3.1 Release', entry.change_reason)
        self.assertIn('Split by extraction.', entry.change_reason)
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.revision, self.revision_before)
        self.assertFalse(self.manual.statuses.exists())

    def test_the_last_section_has_nothing_to_merge(self):
        response = self.post(f'/api/sections/{self.c_child.id}/merge-next/')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'no_next')

    # -- split --------------------------------------------------------

    def test_splitting_at_a_missed_heading(self):
        at = self.c.content.index('4.1 Filing')
        response = self.post(f'/api/sections/{self.c.id}/split/',
                             {'at': at, 'title_from_first_line': True})
        self.assertEqual(response.status_code, 200, response.data)
        self.c.refresh_from_db()
        new = ManualSection.objects.get(pk=response.data['new_section']['id'])
        self.assertEqual(self.c.content, 'The staff verifies the request.')
        self.assertEqual(new.subtitle, '4.1 Filing')
        self.assertEqual(new.content, 'The clerk files it.')
        self.assertEqual(new.order, self.c.order + 1)
        self.assertEqual(
            list(self.manual.sections.order_by('order').values_list('id', flat=True)),
            [self.a.id, self.b.id, self.c.id, new.id, self.c_child.id],
        )
        self.assertEqual(SectionHistory.objects.get(section=self.c).source, 'structure')

    def test_splitting_with_a_typed_title(self):
        at = self.c.content.index('The clerk')
        response = self.post(f'/api/sections/{self.c.id}/split/',
                             {'at': at, 'subtitle': '4.2 Records'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['new_section']['subtitle'], '4.2 Records')

    def test_both_parts_need_text(self):
        for at in (0, len(self.c.content), -3):
            response = self.post(f'/api/sections/{self.c.id}/split/',
                                 {'at': at, 'subtitle': 'X'})
            self.assertEqual(response.status_code, 400, at)
        self.assertEqual(self.manual.sections.count(), 4)

    def test_a_title_is_required(self):
        response = self.post(f'/api/sections/{self.c.id}/split/', {'at': 5})
        self.assertEqual(response.status_code, 400)

    # -- who, and when -------------------------------------------------

    def test_the_password_is_required(self):
        response = self.post(f'/api/sections/{self.a.id}/merge-next/', token=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'reauth_required')
        self.assertTrue(ManualSection.objects.filter(pk=self.b.pk).exists())

    def test_staff_may_not(self):
        staff = CustomUser.objects.create_user(
            username='staff', password=PASSWORD, is_approved=True)
        response = self.post(f'/api/sections/{self.a.id}/merge-next/', user=staff)
        self.assertEqual(response.status_code, 403)

    def test_refused_once_the_document_has_a_status(self):
        DocumentStatus.objects.create(
            manual=self.manual, document_number='FAM 6.02', version='1',
            revision='0', effective_on=datetime.date(2026, 1, 5),
            recorded_by=self.admin, recorded_as='QMS Office — Document Custodian',
        )
        for path, body in ((f'/api/sections/{self.a.id}/merge-next/', {}),
                           (f'/api/sections/{self.c.id}/split/', {'at': 5, 'subtitle': 'X'})):
            response = self.post(path, body)
            self.assertEqual(response.status_code, 409, path)
            self.assertEqual(response.data['reason'], 'controlled')
        self.assertEqual(self.manual.sections.count(), 4)

    def test_refused_when_a_request_has_touched_either_section(self):
        office = Office.objects.create(name='Accounting Office', abbreviation='ACC')
        proposal = Proposal.objects.create(
            manual=self.manual, initiating_office=office, created_by=self.admin,
            status=Proposal.WITHDRAWN,
        )
        version = ProposalVersion.objects.create(proposal=proposal, number=1)
        SectionChange.objects.create(version=version, section=self.b,
                                     old_text=self.b.content, new_text='Changed.')
        response = self.post(f'/api/sections/{self.a.id}/merge-next/')
        self.assertEqual(response.status_code, 409)
        # A section the request never touched can still be split.
        response = self.post(f'/api/sections/{self.c.id}/split/',
                             {'at': 5, 'subtitle': 'X'})
        self.assertEqual(response.status_code, 200)

    def test_the_list_says_which_sections_may_be_restructured(self):
        data = self.client.get(f'/api/manuals/{self.manual.id}/sections/').data
        self.assertEqual(set(data['restructurable_ids']),
                         {self.a.id, self.b.id, self.c.id, self.c_child.id})

    def test_a_long_merged_section_carries_a_warning(self):
        self.b.content = 'x' * 1300
        self.b.save(update_fields=['content'])
        response = self.post(f'/api/sections/{self.a.id}/merge-next/')
        self.assertEqual(len(response.data['warnings']), 1)
