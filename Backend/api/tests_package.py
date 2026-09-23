"""Signed copies: uploading, replacing, downloading.

What has teeth here:

**The system records; it does not verify - but it does check the file.**
A scan must be a real PDF, JPEG or PNG that opens, judged by its bytes and
not by its name. An empty or damaged file would reach the IMR as a
package that looks complete and is not.

**Replacement supersedes, with a reason and the password.** The earlier
file stays, downloadable, and the first upload needs no password.

**Only the office that made the request uploads**, and only while the
request is waiting for signed copies.

**Files leave through the authenticated view**, never as media URLs.

Every test that expects an error asserts the reason, not only the status.
"""

import io
import os
from unittest import mock

import pymupdf
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from api import package_views
from api.models import (
    Attachment, AuditEvent, CustomUser, PositionAssignment, Proposal,
)
from api.tests_generation import PackageFixture


def pdf_bytes(text='Signed.'):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def image_bytes(fmt='PNG'):
    buffer = io.BytesIO()
    Image.new('RGB', (40, 30), 'white').save(buffer, fmt)
    return buffer.getvalue()


def a_file(name='signed.pdf', data=None, content_type='application/pdf'):
    return SimpleUploadedFile(name, pdf_bytes() if data is None else data, content_type)


class PackageTestCase(PackageFixture):

    def setUp(self):
        super().setUp()
        self.proposal = self.locked()
        self.assertEqual(self.proposal.status, Proposal.AWAITING_SIGNATURE)
        self.url = '/api/proposals/%d/' % self.proposal.id

    def upload(self, kind=Attachment.SIGNED_DCR, file=None, user=None):
        return self.as_(user or self.acc_enc).post(
            self.url + 'scans/', {'kind': kind, 'file': file or a_file()},
            format='multipart',
        )

    def replace(self, attachment_id, reason='The first scan was unreadable.',
                file=None, user=None, token=True):
        user = user or self.acc_enc
        extra = {'HTTP_X_REAUTH_TOKEN': self.token(user)} if token else {}
        body = {'file': file or a_file('rescan.pdf')}
        if reason is not None:
            body['reason'] = reason
        return self.as_(user).post(
            self.url + 'scans/%d/replace/' % attachment_id, body,
            format='multipart', **extra,
        )

    def current(self, kind):
        return Attachment.objects.get(proposal=self.proposal, kind=kind,
                                      superseded_at__isnull=True)


# --- uploading -----------------------------------------------

class UploadTests(PackageTestCase):

    def test_the_office_uploads_and_the_upload_is_recorded(self):
        response = self.upload(file=a_file('DCR signed (1).pdf'))
        self.assertEqual(response.status_code, 201, response.data)

        scan = self.current(Attachment.SIGNED_DCR)
        self.assertEqual(scan.original_filename, 'DCR signed (1).pdf')
        self.assertEqual(scan.content_type, 'application/pdf')
        self.assertEqual(scan.size_bytes, os.path.getsize(scan.file.path))
        self.assertEqual(scan.created_by, self.acc_enc)
        self.assertEqual(scan.created_as, 'Accounting Office — Encoder')
        self.assertNotIn('signed', os.path.basename(scan.file.name).lower())
        event = self.proposal.events.get(event=AuditEvent.SCAN_UPLOADED)
        self.assertIn('DCR signed (1).pdf', event.detail)

    def test_the_first_upload_needs_no_password(self):
        """Ordinary work on paper already signed."""
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)

    def test_both_copies_in_makes_it_ready_for_the_imr(self):
        self.upload(Attachment.SIGNED_DCR)
        self.assertEqual(Proposal.objects.get(pk=self.proposal.pk).status,
                         Proposal.AWAITING_SIGNATURE)
        response = self.upload(Attachment.SIGNED_PAGES,
                               a_file('pages.png', image_bytes('PNG'), 'image/png'))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], Proposal.READY_FOR_IMR)
        self.assertEqual(response.data['outstanding'], [])
        self.assertTrue(self.proposal.events.filter(event=AuditEvent.PACKAGE_COMPLETE).exists())

    def test_a_head_may_upload_too(self):
        response = self.upload(user=self.acc_head)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.current(Attachment.SIGNED_DCR).created_as,
                         'Accounting Office — Head')

    def test_another_office_may_not(self):
        response = self.upload(user=self.bud_head)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'not_in_office')
        self.assertFalse(Attachment.objects.filter(kind=Attachment.SIGNED_DCR).exists())

    def test_oversight_reads_but_does_not_upload(self):
        """Configuring the system and controlling documents are separate."""
        admin = CustomUser.objects.create_user(
            username='sysadmin', password='x', is_approved=True,
            system_role=CustomUser.SYSTEM_ADMIN,
        )
        self.assertEqual(self.as_(admin).get(self.url + 'package/').status_code, 200)
        response = self.upload(user=admin)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'not_in_office')

    def test_the_same_copy_cannot_be_uploaded_twice(self):
        self.upload()
        response = self.upload()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'already_uploaded')

    def test_an_unknown_kind_is_refused(self):
        response = self.upload(kind='dcr_generated')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'unknown_kind')

    def test_nothing_is_accepted_before_the_documents_exist(self):
        Proposal.objects.filter(pk=self.proposal.pk).update(status=Proposal.LOCKED)
        response = self.upload()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_accepting_scans')
        self.assertIn('not been generated', response.data['error'])

    def test_the_uploaders_position_is_kept_as_it_was(self):
        """Ending the assignment later must not rewrite the upload."""
        self.upload()
        last_year = self.today.replace(year=self.today.year - 1)
        PositionAssignment.objects.filter(user=self.acc_enc).update(
            starts_on=last_year, ends_on=last_year,
        )
        payload = self.as_(self.acc_head).get(self.url + 'package/').data
        self.assertEqual(payload['scans'][Attachment.SIGNED_DCR]['current']['by'],
                         'Accounting Office — Encoder')


# --- checking the file ---------------------------------------

class FileCheckTests(PackageTestCase):

    def refused(self, file, reason):
        response = self.upload(file=file)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data['reason'], reason)
        self.assertFalse(Attachment.objects.filter(kind=Attachment.SIGNED_DCR).exists())
        return response

    def test_pdf_jpeg_and_png_are_accepted(self):
        for kind, file in ((Attachment.SIGNED_DCR, a_file('a.pdf')),
                           (Attachment.SIGNED_PAGES,
                            a_file('b.jpg', image_bytes('JPEG'), 'image/jpeg'))):
            response = self.upload(kind, file)
            self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.current(Attachment.SIGNED_PAGES).content_type, 'image/jpeg')

    def test_an_empty_file_is_refused(self):
        self.refused(a_file(data=b''), 'empty_file')

    def test_a_file_over_the_limit_is_refused(self):
        with mock.patch.object(package_views, 'MAX_SCAN_BYTES', 100):
            response = self.refused(a_file(), 'too_large')
        self.assertIn('The limit is', response.data['error'])

    def test_the_type_is_judged_by_the_bytes_not_the_name(self):
        """A text file called .pdf, sent as application/pdf, is still text."""
        self.refused(a_file('scan.pdf', b'Hello, this is not a PDF.', 'application/pdf'),
                     'unsupported_type')

    def test_a_damaged_pdf_is_refused(self):
        self.refused(a_file('scan.pdf', b'%PDF-1.4\n' + b'\x00garbage' * 50),
                     'unreadable_file')

    def test_a_truncated_image_is_refused(self):
        whole = image_bytes('PNG')
        self.refused(a_file('scan.png', whole[:len(whole) // 2], 'image/png'),
                     'unreadable_file')

    def test_a_password_protected_pdf_is_refused(self):
        """The QMS office has to be able to open it."""
        document = pymupdf.open()
        document.new_page()
        data = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                owner_pw='owner', user_pw='secret')
        response = self.refused(a_file('locked.pdf', data), 'unreadable_file')
        self.assertIn('password-protected', response.data['error'])


# --- replacing -----------------------------------------------

class ReplaceTests(PackageTestCase):

    def setUp(self):
        super().setUp()
        self.upload()
        self.first = self.current(Attachment.SIGNED_DCR)

    def test_replacing_supersedes_and_keeps_the_old_file(self):
        response = self.replace(self.first.id, reason='Page 2 was cut off.')
        self.assertEqual(response.status_code, 200, response.data)

        self.first.refresh_from_db()
        new = self.current(Attachment.SIGNED_DCR)
        self.assertIsNotNone(self.first.superseded_at)
        self.assertEqual(new.supersedes, self.first)
        self.assertEqual(new.replacement_reason, 'Page 2 was cut off.')
        self.assertTrue(os.path.exists(self.first.file.path))
        self.assertNotEqual(self.first.file.name, new.file.name)

        event = self.proposal.events.get(event=AuditEvent.SCAN_REPLACED)
        self.assertIn('Page 2 was cut off.', event.detail)
        earlier = response.data['scans'][Attachment.SIGNED_DCR]['earlier']
        self.assertEqual([e['id'] for e in earlier], [self.first.id])

    def test_replacing_needs_the_password(self):
        response = self.replace(self.first.id, token=False)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['reason'], 'reauth_required')
        self.assertIsNone(Attachment.objects.get(pk=self.first.pk).superseded_at)

    def test_replacing_needs_a_reason(self):
        response = self.replace(self.first.id, reason='  ')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'reason_required')

    def test_only_the_current_copy_can_be_replaced(self):
        self.replace(self.first.id)
        response = self.replace(self.first.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_current')

    def test_generated_documents_are_never_replaced(self):
        generated = Attachment.objects.get(proposal=self.proposal,
                                           kind=Attachment.DCR_GENERATED)
        response = self.replace(generated.id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'not_a_scan')

    def test_a_replacement_is_checked_like_an_upload(self):
        response = self.replace(self.first.id, file=a_file('x.pdf', b'not a pdf'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['reason'], 'unsupported_type')
        self.assertIsNone(Attachment.objects.get(pk=self.first.pk).superseded_at)

    def test_replacement_still_allowed_while_the_imr_has_not_decided(self):
        self.upload(Attachment.SIGNED_PAGES)
        self.assertEqual(Proposal.objects.get(pk=self.proposal.pk).status,
                         Proposal.READY_FOR_IMR)
        response = self.replace(self.first.id)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], Proposal.READY_FOR_IMR)

    def test_replacement_refused_once_the_request_has_moved_on(self):
        """Option A. P4's decided statuses fall outside SCAN_STATUSES."""
        Proposal.objects.filter(pk=self.proposal.pk).update(status=Proposal.WITHDRAWN)
        response = self.replace(self.first.id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['reason'], 'not_accepting_scans')


# --- reading and downloading ---------------------------------

class PackageReadingTests(PackageTestCase):

    def test_the_package_lists_the_documents_and_what_is_outstanding(self):
        payload = self.as_(self.bud_head).get(self.url + 'package/').data
        self.assertEqual(
            [g['kind'] for g in payload['generated']],
            [Attachment.DCR_GENERATED, Attachment.PAGES_GENERATED,
             Attachment.CONCURRENCE_RECORD],
        )
        self.assertEqual(payload['outstanding'],
                         [Attachment.SIGNED_DCR, Attachment.SIGNED_PAGES])
        self.assertFalse(payload['can_upload'])       # a concurring office reads
        self.assertTrue(self.as_(self.acc_enc).get(self.url + 'package/').data['can_upload'])

    def test_no_url_or_path_to_a_file_is_given_out(self):
        """Files leave through the authenticated view, never as media URLs."""
        self.upload()
        body = str(self.as_(self.acc_enc).get(self.url + 'package/').data)
        self.assertNotIn('/media/', body)
        self.assertNotIn('proposals/%d/' % self.proposal.id, body)

    def test_a_participant_downloads_under_the_original_name(self):
        self.upload(file=a_file('DCR signed.pdf'))
        scan = self.current(Attachment.SIGNED_DCR)
        response = self.as_(self.bud_head).get(
            self.url + 'attachments/%d/download/' % scan.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn('DCR signed.pdf', response['Content-Disposition'])
        self.assertEqual(b''.join(response.streaming_content), open(scan.file.path, 'rb').read())

    def test_a_superseded_copy_can_still_be_downloaded(self):
        self.upload()
        first = self.current(Attachment.SIGNED_DCR)
        self.replace(first.id)
        response = self.as_(self.acc_enc).get(
            self.url + 'attachments/%d/download/' % first.id)
        self.assertEqual(response.status_code, 200)

    def test_an_outsider_can_neither_read_nor_download(self):
        stranger = CustomUser.objects.create_user(
            username='stranger', password='x', is_approved=True)
        generated = Attachment.objects.get(proposal=self.proposal,
                                           kind=Attachment.DCR_GENERATED)
        for path in ('package/', 'attachments/%d/download/' % generated.id):
            response = self.as_(stranger).get(self.url + path)
            self.assertEqual(response.status_code, 403, path)
            self.assertEqual(response.data['error'], 'Access denied')

    def test_a_file_from_another_request_is_not_found_here(self):
        other = Attachment.objects.exclude(proposal=self.proposal).first()
        if other is None:
            other_proposal = Proposal.objects.create(
                manual=self.manual, initiating_office=self.budget,
                created_by=self.bud_head)
            version = other_proposal.versions.create(number=1)
            other = Attachment.objects.create(
                proposal=other_proposal, version=version,
                kind=Attachment.SIGNED_DCR, created_by=self.bud_head,
                file='proposals/x/y.pdf')
        response = self.as_(self.acc_enc).get(
            self.url + 'attachments/%d/download/' % other.id)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['reason'], 'not_found')
