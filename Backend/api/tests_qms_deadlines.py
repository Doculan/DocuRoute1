"""The QMS portal's Deadlines tab: read-only.

QMS staff read every deadline, its detail and the offices behind each
number; only the system admin sets, changes or deactivates one. Anyone
else is refused.
"""

from api.models import CustomUser, DeadlineTarget, Office, Position

from .tests_notices import DeadlineFixture


class QmsReadsDeadlines(DeadlineFixture):

    def setUp(self):
        super().setUp()
        qms = Office.objects.create(name='Quality Management Office')
        self.imr = self.person('dl_imr', qms, Position.IMR)
        self.imr.system_role = CustomUser.QMS_STAFF
        self.imr.save(update_fields=['system_role'])
        self.made = self.deadline(DeadlineTarget(kind='office', office=self.acc), days=10)

    def test_qms_reads_the_list_the_detail_and_the_offices(self):
        client = self.as_(self.imr)
        listed = client.get('/api/admin/deadlines/')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([d['id'] for d in listed.data['deadlines']], [self.made.pk])
        detail = client.get(f'/api/admin/deadlines/{self.made.pk}/')
        self.assertEqual(detail.status_code, 200)
        branch = detail.data['by_branch'][0]['branch_id']
        offices = client.get(f'/api/admin/deadlines/{self.made.pk}/obligations/', {'branch': branch})
        self.assertEqual(offices.status_code, 200)

    def test_qms_changes_nothing(self):
        client = self.as_(self.imr)
        self.assertEqual(client.patch(f'/api/admin/deadlines/{self.made.pk}/', {'active': False},
                                      format='json').status_code, 403)
        self.assertEqual(client.post('/api/admin/deadlines/', {}, format='json').status_code, 403)
        self.assertEqual(client.post(f'/api/admin/deadlines/{self.made.pk}/priority/', {},
                                     format='json').status_code, 403)
        self.made.refresh_from_db()
        self.assertTrue(self.made.active)

    def test_office_staff_read_nothing_here(self):
        response = self.as_(self.acc_head).get('/api/admin/deadlines/')
        self.assertEqual(response.status_code, 403)
