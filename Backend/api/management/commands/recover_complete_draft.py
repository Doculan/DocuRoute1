"""Replace an unsigned legacy partial draft, explicitly using today's baseline.

Dry run by default. Original bytes and attachment records are always retained.
This is not a reconstruction of unchanged content at the original lock time.
"""

import io

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from docx import Document

from api.document_hygiene import scrub_document
from api.generation import pages
from api.generation.common import DOCX_TYPE, changed_sections, check_package
from api.models import Attachment, AuditEvent, CustomUser, Manual, Proposal


class Command(BaseCommand):
    help = 'Dry-run recovery of an unsigned changed-sections-only draft to a complete current-baseline draft.'

    def add_arguments(self, parser):
        parser.add_argument('--proposal', type=int, required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--actor', type=int, help='Approved, active system administrator user ID.')
        parser.add_argument('--reason', default='')
        parser.add_argument('--accept-current-baseline', action='store_true')

    def handle(self, *args, **options):
        apply = options['apply']
        reason = options['reason'].strip()
        if apply and not (options['accept_current_baseline'] and options['actor'] and reason):
            raise CommandError('--apply requires --actor, --reason and --accept-current-baseline.')
        created = None
        try:
            with transaction.atomic():
                proposal = Proposal.objects.select_for_update().filter(pk=options['proposal']).first()
                if proposal is None:
                    raise CommandError('Proposal not found.')
                if proposal.status != Proposal.AWAITING_SIGNATURE:
                    raise CommandError('Only a proposal awaiting signature may be recovered.')
                if proposal.attachments.filter(kind__in=Attachment.SCAN_KINDS).exists():
                    raise CommandError('Signed scans exist; retain the original package.')
                # Lock the manual too; read the baseline within the transaction.
                proposal.manual = Manual.objects.select_for_update().get(pk=proposal.manual_id)
                version = proposal.current_version()
                if version is None:
                    raise CommandError('Proposal has no version.')
                originals = list(Attachment.objects.select_for_update().filter(
                    proposal=proposal, version=version, kind=Attachment.PAGES_GENERATED,
                    superseded_at__isnull=True))
                if len(originals) != 1:
                    raise CommandError('Expected exactly one current draft attachment.')
                original = originals[0]
                try:
                    with original.file.open('rb') as stream:
                        paragraphs = [p.text for p in Document(stream).paragraphs]
                except Exception as error:
                    raise CommandError('The original draft cannot be read; recovery refused.') from error
                if not paragraphs or not paragraphs[0].endswith('· changed sections only'):
                    raise CommandError('The current draft is not a legacy partial draft; nothing to replace.')
                changes = changed_sections(version)
                if not changes:
                    raise CommandError('The proposal has no changed sections.')
                if any((c.section.content or '').strip() != (c.old_text or '').strip() for c in changes):
                    raise CommandError('A changed section no longer matches its agreed baseline; recovery refused.')

                count = proposal.manual.sections.count()
                moment = timezone.localtime()
                note = (
                    f'Complete draft manual incorporating the changes in {proposal.dcr_number}. '
                    f'Reconstructed on {moment:%Y-%m-%d %H:%M %Z} from the current manual '
                    'and the agreed proposal edits. Unchanged sections are not an original lock-time snapshot.'
                )
                document = pages.build_document(proposal, version, note=note)
                scrub_document(document)
                buffer = io.BytesIO()
                document.save(buffer)
                data = buffer.getvalue()
                filename = f'{proposal.dcr_number} Complete reconstructed draft.docx'
                check_package(data, filename)
                self.stdout.write(
                    f'Proposal {proposal.pk}: {count} sections, {len(changes)} revised; '
                    f'preserve attachment {original.pk}. Baseline: current manual, NOT original lock time.'
                )
                if not apply:
                    self.stdout.write('DRY RUN: no attachments or records changed.')
                    return
                actor = CustomUser.objects.filter(
                    pk=options['actor'], role='admin', is_active=True, is_approved=True,
                ).first()
                if actor is None:
                    raise CommandError('--actor must identify an approved, active system administrator.')

                original.superseded_at = moment
                original.save(update_fields=['superseded_at'])
                created = Attachment(
                    proposal=proposal, version=version, kind=Attachment.PAGES_GENERATED,
                    slot=original.slot, original_filename=filename, content_type=DOCX_TYPE,
                    size_bytes=len(data), created_by=actor, supersedes=original,
                    replacement_reason=reason,
                )
                created.file.save(filename, ContentFile(data), save=False)
                created.save()
                AuditEvent.objects.create(
                    proposal=proposal, version=version, event=AuditEvent.DOCUMENTS_GENERATED,
                    actor=actor, office=proposal.initiating_office,
                    office_name_at_time=proposal.initiating_office.name,
                    detail=(f'Complete draft recovery: attachment {original.pk} superseded by '
                            f'{created.pk}; current-manual baseline at {moment.isoformat()}; '
                            f'original retained. Reason: {reason}'),
                )
        except Exception:
            # Database rollback cannot remove bytes. Only remove this command's
            # newly created file; the preserved original is never touched.
            if created is not None and created.file and created.file._committed:
                created.file.delete(save=False)
            raise
        self.stdout.write(self.style.SUCCESS(
            f'Created attachment {created.pk}; original attachment {original.pk} retained.'
        ))
