"""The expanded audit block (spec §10, no hash chain).

- **The summary** says who started it (position, name, office) and when,
  days open, the stage and who holds it, versions, and times returned and
  by whom.
- **The timeline**, grouped by version: every step, position first with
  the person's full name, the stage moved from and to and the time in the
  one before; notes, feedback and reasons verbatim; the AI checks from
  their stored results.
- **Exports** (CSV, PDF) follow the trail report's access rules and are
  logged as trail reports with a serial and a hash. CSV carries a UTF-8
  marker and formula-safe cells.

Tests that expect an error assert the reason.
"""

from api.models import Concurrence, CustomUser, Office, Position, TrailReport

from .tests_concurrence import ConcurrenceFixture

NOTE = '=Say which day. "Five" is vague.'


class TrailFixture(ConcurrenceFixture):

    def setUp(self):
        super().setUp()
        for user, name in ((self.acc_enc, 'Juan Dela Cruz'), (self.acc_head, 'Maria Santos'),
                           (self.bud_head, 'Jose Ramos')):
            user.full_name = name
            user.save(update_fields=['full_name'])
        self.pid = self.a_draft()
        self.send_to_head(self.pid)
        self.as_(self.acc_head).post(f'/api/proposals/{self.pid}/return-to-encoder/',
                                     {'note': NOTE}, format='json')
        self.submit(self.pid)
        self.decide(self.pid, self.bud_head, Concurrence.RETURN,
                    feedback='Name the cashier.', section=self.s1)

    def trail(self, user=None):
        return self.as_(user or self.acc_enc).get(f'/api/proposals/{self.pid}/trail/')


class TheBlock(TrailFixture):

    def test_the_summary(self):
        s = self.trail().data['summary']
        self.assertEqual(s['initiated_by'], {'position': 'Accounting Office — Encoder',
                                             'name': 'Juan Dela Cruz'})
        self.assertEqual((s['versions'], s['times_returned']), (2, 2))
        self.assertEqual([r['by'] for r in s['returned_by']],
                         ['Accounting Office — Head', 'Budget Office'])
        self.assertEqual(s['stage'], 'Drafting')
        self.assertEqual(s['holder']['who'], 'Accounting Office')

    def test_the_timeline_by_version_with_who_stages_and_verbatim_notes(self):
        v1 = self.trail().data['versions'][0]
        steps = [(i['label'], i['by']['position'], i['to']) for i in v1['items'] if i['kind'] == 'event']
        self.assertEqual(steps[:4], [
            ('Created', 'Accounting Office — Encoder', 'Drafting'),
            ('Sent to the Head', 'Accounting Office — Encoder', 'With Head'),
            ('Returned to the Encoder', 'Accounting Office — Head', 'Returned by the Head'),
            ('Sent to the Head', 'Accounting Office — Encoder', 'With Head'),
        ])
        returned = next(i for i in v1['items'] if i['label'] == 'Returned to the Encoder')
        self.assertEqual(returned['detail'], NOTE)
        self.assertEqual(returned['by']['name'], 'Maria Santos')
        self.assertEqual(returned['from'], 'With Head')
        self.assertIsNotNone(returned['time_in_previous'])
        office_return = next(i for i in v1['items'] if i['label'] == 'Returned with feedback'
                             or i['event'] == 'returned')
        self.assertIn('Name the cashier.', office_return['detail'])
        self.assertIn('(Section: 3.0 POLICIES)', office_return['detail'])

    def test_the_ai_checks_come_from_the_stored_results(self):
        checks = [i for i in self.trail().data['versions'][0]['items'] if i['kind'] == 'ai_check']
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0]['detail'].startswith('3.0 POLICIES: '))
        self.assertEqual(checks[0]['by']['position'], 'Accounting Office — Encoder')

    def test_only_those_who_may_open_it(self):
        outsider = CustomUser.objects.create_user(username='out', password='pw', is_approved=True)
        office = Office.objects.create(name='Registry')
        position = Position.objects.create(office=office, kind=Position.HEAD)
        from api.models import PositionAssignment
        PositionAssignment.objects.create(user=outsider, position=position, starts_on=self.today)
        self.assertEqual(self.trail(outsider).status_code, 403)


class TheExports(TrailFixture):

    def export(self, user=None, **body):
        return self.as_(user or self.acc_head).post(
            f'/api/proposals/{self.pid}/trail/export/', {'format': 'csv', **body}, format='json')

    def test_csv_is_utf8_marked_formula_safe_and_logged(self):
        response = self.export(filters={'action': 'returned_to_encoder'})
        self.assertEqual(response.status_code, 200)
        text = response.content.decode('utf-8')
        self.assertTrue(text.startswith('﻿'))
        self.assertIn("'=Say which day.", text)
        self.assertNotIn(',=Say', text)
        self.assertNotIn('Sent to the Head', text)            # filtered to one action
        serial = response['X-Report-Serial']
        self.assertTrue(serial.endswith('-CSV'))
        logged = TrailReport.objects.get(serial=serial)
        self.assertEqual((logged.generated_by, logged.generated_as),
                         (self.acc_head, 'Accounting Office — Head'))
        self.assertEqual(len(logged.sha256), 64)

    def test_pdf_with_a_serial_on_every_page(self):
        response = self.export(format='pdf')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))
        import fitz
        document = fitz.open('pdf', response.content)
        self.assertIn(response['X-Report-Serial'], document[0].get_text())
        self.assertIn(f'Page 1 of {document.page_count}', document[0].get_text())

    def test_refusals_name_the_reason(self):
        admin = CustomUser.objects.create_user(username='tr_admin', password='pw', role='admin',
                                               is_approved=True,
                                               system_role=CustomUser.SYSTEM_ADMIN)
        self.assertEqual(self.export(admin).data['reason'], 'reason_required')
        self.assertEqual(self.export(admin, reason='Audit sample').status_code, 200)
        self.assertEqual(self.export(format='docx').data['reason'], 'invalid_format')
        outsider = CustomUser.objects.create_user(username='out2', password='pw', is_approved=True)
        self.assertEqual(self.export(outsider).data['reason'], 'not_in_trail')
