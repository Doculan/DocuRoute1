"""The package: the generated documents, and the signed copies coming back.

Phase 3c. Three rules shape it.

**The system stores and records; it does not verify.** It cannot tell
whether a scan shows the right document, whether a signature is genuine,
or whether the person who signed held the position. The QMS office checks
that against the paper originals. What the system does check is that a
file is what it claims to be and can be opened - an empty or corrupt scan
would reach the IMR as a package that looks complete and is not.

**Replacement supersedes; it never overwrites.** The earlier file stays,
with who uploaded it and when, and the replacement carries its reason.
Replacing needs the password again; the first upload does not - uploading
is ordinary work on paper already signed, replacing changes the evidence.

**Files leave through this view, never as media URLs.** Under DEBUG,
Django serves MEDIA_ROOT to anyone; in production the proxy must not
(DEPLOYMENT.md). A signed DCR is fetched here, after the same visibility
check as the proposal itself.
"""

import io

from django.db import IntegrityError, transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import access, documents
from .concurrence_views import _load, _record, can_see
from .generation.common import position_title
from .models import Attachment, AuditEvent, Position, Proposal
from .proposal_views import _held_position, _switch_off
from .views import reauth_failure

# Scans of a few signed pages come in well under this. Large enough for a
# colour scan at a generous resolution; small enough that a mistaken video
# or archive is refused rather than stored.
MAX_SCAN_BYTES = 20 * 1024 * 1024

# Recognised by their first bytes, not by the name or the type the browser
# sent: both are the uploader's claim.
_SIGNATURES = (
    (b'%PDF-', 'application/pdf', '.pdf'),
    (b'\x89PNG\r\n\x1a\n', 'image/png', '.png'),
    (b'\xff\xd8\xff', 'image/jpeg', '.jpg'),
)

_SCAN_LABEL = dict(Attachment.KIND_CHOICES)


class ScanRefused(Exception):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason
        self.message = message


def check_scan(upload):
    """The file's bytes and its real type, or `ScanRefused` saying why not."""
    size = upload.size or 0
    if size == 0:
        raise ScanRefused('empty_file', 'That file is empty.')
    if size > MAX_SCAN_BYTES:
        raise ScanRefused(
            'too_large',
            f'That file is {size / 1048576:.1f} MB. The limit is '
            f'{MAX_SCAN_BYTES // 1048576} MB.',
        )
    data = upload.read()
    if len(data) != size or not data:
        raise ScanRefused('unreadable_file', 'That file could not be read in full.')

    kind = next(((t, ext) for magic, t, ext in _SIGNATURES if data.startswith(magic)), None)
    if kind is None:
        raise ScanRefused('unsupported_type', 'Upload a PDF, JPEG or PNG.')
    content_type, extension = kind

    try:
        if content_type == 'application/pdf':
            import pymupdf
            with pymupdf.open(stream=data, filetype='pdf') as pdf:
                if pdf.needs_pass:
                    raise ScanRefused(
                        'unreadable_file',
                        'That PDF is password-protected. Upload one the QMS office can open.',
                    )
                if pdf.page_count < 1:
                    raise ScanRefused('unreadable_file', 'That PDF has no pages.')
                pdf[0].get_text()   # touches the first page's content
        else:
            from PIL import Image
            Image.open(io.BytesIO(data)).verify()
            # `verify` checks the structure; loading catches a truncated one.
            Image.open(io.BytesIO(data)).load()
    except ScanRefused:
        raise
    except Exception:
        raise ScanRefused('unreadable_file', 'That file is damaged and cannot be opened.')

    return data, content_type, extension


# --- reading -------------------------------------------------

def _file_payload(attachment):
    return {
        'id': attachment.id,
        'kind': attachment.kind,
        'label': _SCAN_LABEL[attachment.kind],
        'filename': attachment.original_filename,
        'content_type': attachment.content_type,
        'size': attachment.size_bytes,
        'at': attachment.created_at,
        # The position as recorded at upload, never the person's name.
        'by': attachment.created_as or None,
        'current': attachment.is_current,
        'replacement_reason': attachment.replacement_reason,
    }


def _can_upload(user, proposal):
    """A current Encoder or Head of the office that made the request."""
    return _held_position(
        user, proposal.initiating_office, kinds=[Position.ENCODER, Position.HEAD],
    ) is not None


def package_payload(proposal, user):
    version = proposal.current_version()
    rows = list(
        Attachment.objects.filter(version=version)
        .select_related('created_by', 'proposal__initiating_office')
        .order_by('created_at')
    ) if version else []

    generated = [_file_payload(a) for a in rows if a.is_generated and a.is_current]
    order = {k: i for i, (k, _) in enumerate(Attachment.KIND_CHOICES)}
    generated.sort(key=lambda f: order[f['kind']])

    scans = {}
    for kind in Attachment.SCAN_KINDS:
        of_kind = [a for a in rows if a.kind == kind]
        current = next((a for a in of_kind if a.is_current), None)
        scans[kind] = {
            'label': _SCAN_LABEL[kind],
            'current': _file_payload(current) if current else None,
            'earlier': [_file_payload(a) for a in reversed(of_kind) if not a.is_current],
        }

    accepting = proposal.status in Proposal.SCAN_STATUSES
    allowed = accepting and _can_upload(user, proposal)
    return {
        'status': proposal.status,
        'dcr_number': proposal.dcr_number,
        'generated': generated,
        'scans': scans,
        'outstanding': documents.scans_outstanding(proposal, version) if version else [],
        'can_upload': allowed,
        'can_replace': allowed,
        'max_bytes': MAX_SCAN_BYTES,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def package(request, proposal_id):
    if not access.by_position():
        return _switch_off()
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    if not can_see(request.user, proposal):
        return Response({'error': 'Access denied'}, status=403)
    return Response(package_payload(proposal, request.user))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def download(request, proposal_id, attachment_id):
    """One file, generated or scanned, current or superseded - the record."""
    if not access.by_position():
        return _switch_off()
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    if not can_see(request.user, proposal):
        return Response({'error': 'Access denied'}, status=403)
    attachment = Attachment.objects.filter(pk=attachment_id, proposal=proposal).first()
    if attachment is None:
        return Response({'error': 'File not found', 'reason': 'not_found'}, status=404)
    return FileResponse(
        attachment.file.open('rb'), as_attachment=True,
        filename=attachment.original_filename or f'attachment-{attachment.id}',
        content_type=attachment.content_type or 'application/octet-stream',
    )


# --- writing -------------------------------------------------

def _refuse_writing(request, proposal):
    """Who may upload, and when. `None` when the answer is yes."""
    if not can_see(request.user, proposal) or not _can_upload(request.user, proposal):
        return Response({
            'error': f'Signed copies are uploaded by {proposal.initiating_office.name}.',
            'reason': 'not_in_office',
        }, status=403)
    if proposal.status not in Proposal.SCAN_STATUSES:
        if proposal.status == Proposal.LOCKED:
            message = 'The documents for this request have not been generated yet.'
        else:
            message = 'Signed copies can only be added or replaced while the request awaits them.'
        return Response({'error': message, 'reason': 'not_accepting_scans'}, status=409)
    return None


def _store(proposal, version, kind, upload, data, content_type, extension, user,
           supersedes=None, reason=''):
    from django.core.files.base import ContentFile
    filename = (upload.name or f'scan{extension}')[-255:]
    office = proposal.initiating_office
    held = _held_position(user, office, kinds=[Position.ENCODER, Position.HEAD])
    attachment = Attachment(
        proposal=proposal, version=version, kind=kind, slot='',
        original_filename=filename, content_type=content_type,
        size_bytes=len(data), created_by=user,
        created_as=position_title(office.name, held.kind) if held else office.name,
        supersedes=supersedes, replacement_reason=reason,
    )
    # The extension from the bytes, not the name: the stored path is ours.
    attachment.file.save(f'scan{extension}', ContentFile(data), save=False)
    attachment.save()
    return attachment


def _complete_if_ready(proposal, version, user):
    if proposal.status != Proposal.AWAITING_SIGNATURE:
        return
    if documents.scans_outstanding(proposal, version):
        return
    proposal.status = Proposal.READY_FOR_IMR
    proposal.save(update_fields=['status'])
    _record(proposal, version, AuditEvent.PACKAGE_COMPLETE, user,
            proposal.initiating_office, detail='Ready for the IMR')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def upload_scan(request, proposal_id):
    """The first signed copy of its kind. No password: see the module notes."""
    if not access.by_position():
        return _switch_off()
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    refused = _refuse_writing(request, proposal)
    if refused:
        return refused

    kind = request.data.get('kind')
    if kind not in Attachment.SCAN_KINDS:
        return Response({'error': 'Say which signed copy this is.', 'reason': 'unknown_kind'},
                        status=400)
    upload = request.FILES.get('file')
    if upload is None:
        return Response({'error': 'Choose a file to upload.', 'reason': 'no_file'}, status=400)

    version = proposal.current_version()
    if Attachment.objects.filter(version=version, kind=kind, slot='',
                                 superseded_at__isnull=True).exists():
        return Response({
            'error': 'That signed copy is already uploaded. Replace it instead.',
            'reason': 'already_uploaded',
        }, status=409)

    try:
        data, content_type, extension = check_scan(upload)
    except ScanRefused as refusal:
        return Response({'error': refusal.message, 'reason': refusal.reason}, status=400)

    try:
        with transaction.atomic():
            _store(proposal, version, kind, upload, data, content_type, extension, request.user)
            _record(proposal, version, AuditEvent.SCAN_UPLOADED, request.user,
                    proposal.initiating_office,
                    detail=f'{_SCAN_LABEL[kind]}: {upload.name}')
            _complete_if_ready(proposal, version, request.user)
    except IntegrityError:
        # Two people uploading the same copy at once: the index kept one.
        return Response({
            'error': 'That signed copy is already uploaded. Replace it instead.',
            'reason': 'already_uploaded',
        }, status=409)

    proposal.refresh_from_db()
    return Response(package_payload(proposal, request.user), status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def replace_scan(request, proposal_id, attachment_id):
    """A new file for a signed copy. The old one stays, superseded."""
    if not access.by_position():
        return _switch_off()
    proposal, error = _load(request, proposal_id)
    if error:
        return error
    refused = _refuse_writing(request, proposal)
    if refused:
        return refused

    old = Attachment.objects.filter(pk=attachment_id, proposal=proposal).first()
    if old is None:
        return Response({'error': 'File not found', 'reason': 'not_found'}, status=404)
    if old.kind not in Attachment.SCAN_KINDS:
        return Response({
            'error': 'Generated documents are never replaced; the content they were made from is frozen.',
            'reason': 'not_a_scan',
        }, status=400)
    if not old.is_current:
        return Response({
            'error': 'That file has already been replaced. Replace the current one.',
            'reason': 'not_current',
        }, status=409)

    reason = (request.data.get('reason') or '').strip()
    if not reason:
        return Response({'error': 'Say why it is being replaced.', 'reason': 'reason_required'},
                        status=400)
    upload = request.FILES.get('file')
    if upload is None:
        return Response({'error': 'Choose a file to upload.', 'reason': 'no_file'}, status=400)

    failure = reauth_failure(request)
    if failure is not None:
        return failure

    try:
        data, content_type, extension = check_scan(upload)
    except ScanRefused as refusal:
        return Response({'error': refusal.message, 'reason': refusal.reason}, status=400)

    with transaction.atomic():
        # Superseded first: the index allows one live file per slot.
        old.superseded_at = timezone.now()
        old.save(update_fields=['superseded_at'])
        _store(proposal, old.version, old.kind, upload, data, content_type, extension,
               request.user, supersedes=old, reason=reason)
        _record(proposal, old.version, AuditEvent.SCAN_REPLACED, request.user,
                proposal.initiating_office,
                detail=f'{_SCAN_LABEL[old.kind]}: {reason}')

    proposal.refresh_from_db()
    return Response(package_payload(proposal, request.user))
