"""Merging and splitting sections after upload, to correct extraction.

Extraction sometimes splits one section of the master copy in two, or
misses a heading and joins two into one. The paper master is unchanged,
so putting DocuRoute's copy right is not a revision: no request, no DCR,
no revision number.

**Only before the document is under control.** Once the Document
Custodian has recorded its status, or any request has touched a section,
the sections are the controlled record. Merging then deletes a section
that requests, signed copies and feedback point at, and that is a change
to go through a request (plan §6, item 10), not a correction.

Admin only, with the password again, like any direct edit. Each one is
recorded in the surviving section's history as
`structure` - who, when, why, and the text before.
"""

from django.db import transaction
from django.db.models import F
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from ml.svm_model import predict_section

from .models import ManualSection, SectionChange, SectionHistory
from .views import IsAdminRole, reauth_failure

# Roughly what the AI check reads of each side. A section longer than
# this is still checked, but only its beginning.
AI_READ_LIMIT = 1200


def locked_reason(manual, sections):
    """Why these sections can no longer be merged or split, or None."""
    if manual.statuses.exists():
        return ('This document has a recorded status, so its sections are the '
                'controlled record. Change them through a request.')
    if SectionChange.objects.filter(section__in=sections).exists():
        return ('A request has included this section, so it can no longer be '
                'merged or split. Change it through a request.')
    return None


def restructurable_ids(manual):
    """Ids of this document's sections that may still be merged or split."""
    if manual.statuses.exists():
        return set()
    touched = set(
        SectionChange.objects.filter(section__manual=manual)
        .values_list('section_id', flat=True)
    )
    return {pk for pk in manual.sections.values_list('id', flat=True)
            if pk not in touched}


def _snapshot(section, user, reason):
    SectionHistory.objects.create(
        section=section, version=section.version, subtitle=section.subtitle,
        content=section.content, tag=section.tag, edited_by=user,
        source='structure', change_reason=reason,
    )


def _renumber(manual):
    for index, section in enumerate(manual.sections.order_by('order', 'id')):
        if section.order != index:
            ManualSection.objects.filter(pk=section.pk).update(order=index)


def _warnings(*sections):
    return [
        f'"{s.subtitle}" is {len(s.content):,} characters. The AI check reads '
        f'about the first {AI_READ_LIMIT:,} of a section, so a change near its '
        f'end is checked with less context.'
        for s in sections if len(s.content) > AI_READ_LIMIT
    ]


def _payload(section):
    return {'id': section.id, 'subtitle': section.subtitle,
            'order': section.order, 'version': section.version}


def _refused(message):
    return Response({'error': message, 'reason': 'controlled'}, status=409)


@api_view(['POST'])
@permission_classes([IsAdminRole])
def merge_next(request, section_id):
    """Join this section and the one after it into this one.

    Adjacent only: an over-split section is always split into neighbours,
    and merging across others would reorder the document. The next
    section's heading stays in the text, so nothing printed on the master
    copy is lost.
    """
    failure = reauth_failure(request)
    if failure:
        return failure
    try:
        keep = ManualSection.objects.select_related('manual').get(pk=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)
    manual = keep.manual
    absorbed = (
        manual.sections.filter(order__gt=keep.order).order_by('order', 'id').first()
        or manual.sections.filter(order=keep.order, id__gt=keep.id).order_by('id').first()
    )
    if absorbed is None:
        return Response({'error': 'This is the last section; there is nothing after it.',
                         'reason': 'no_next'}, status=400)
    locked = locked_reason(manual, [keep, absorbed])
    if locked:
        return _refused(locked)

    note = (request.data.get('reason') or '').strip()
    reason = f'Merged with the next section, "{absorbed.subtitle}".'
    if note:
        reason += f' {note}'

    with transaction.atomic():
        _snapshot(keep, request.user, reason)
        parts = [keep.content.rstrip(), absorbed.subtitle.strip(),
                 absorbed.content.strip()]
        keep.content = '\n\n'.join(p for p in parts if p)
        keep.version += 1
        keep.save(update_fields=['content', 'version'])
        # Its sub-sections move up rather than going with it: the parent
        # link cascades, so deleting it as it stands would delete them.
        absorbed.children.exclude(pk=keep.pk).update(parent=keep)
        absorbed.delete()
        _renumber(manual)
        keep.refresh_from_db()

    return Response({'section': _payload(keep), 'warnings': _warnings(keep)})


@api_view(['POST'])
@permission_classes([IsAdminRole])
def split(request, section_id):
    """Split this section in two at a character offset.

    `at` is where the second part starts. With `title_from_first_line`,
    the first line of the second part - the heading extraction missed -
    becomes its title rather than staying in its text.
    """
    failure = reauth_failure(request)
    if failure:
        return failure
    try:
        section = ManualSection.objects.select_related('manual').get(pk=section_id)
    except ManualSection.DoesNotExist:
        return Response({'error': 'Section not found'}, status=404)
    manual = section.manual
    locked = locked_reason(manual, [section])
    if locked:
        return _refused(locked)

    try:
        at = int(request.data.get('at'))
    except (TypeError, ValueError):
        return Response({'error': 'Say where to split.'}, status=400)
    if not 0 < at < len(section.content):
        return Response({'error': 'Both parts need some text.', 'reason': 'empty_part'},
                        status=400)
    first = section.content[:at].rstrip()
    second = section.content[at:].strip()

    subtitle = (request.data.get('subtitle') or '').strip()
    if request.data.get('title_from_first_line'):
        heading, _, rest = second.partition('\n')
        subtitle = subtitle or heading.strip()
        second = rest.strip()

    if not first or not second:
        return Response({'error': 'Both parts need some text.', 'reason': 'empty_part'},
                        status=400)
    if not subtitle:
        return Response({'error': 'Give the new section a title.'}, status=400)
    max_title = ManualSection._meta.get_field('subtitle').max_length
    if len(subtitle) > max_title:
        return Response({'error': f'Keep the title under {max_title} characters.'},
                        status=400)

    note = (request.data.get('reason') or '').strip()
    reason = f'Split: the text from "{subtitle}" on became a section of its own.'
    if note:
        reason += f' {note}'

    with transaction.atomic():
        _snapshot(section, request.user, reason)
        section.content = first
        section.version += 1
        section.save(update_fields=['content', 'version'])

        manual.sections.filter(order__gt=section.order).update(order=F('order') + 1)
        try:
            tag = predict_section(second)
        except Exception:
            tag = 'UNTAGGED'
        new = ManualSection.objects.create(
            manual=manual, subtitle=subtitle, content=second, tag=tag,
            page_number=section.page_number, order=section.order + 1,
            parent=section.parent, is_reviewed=section.is_reviewed,
        )
        _renumber(manual)
        section.refresh_from_db()
        new.refresh_from_db()

    return Response({
        'section': _payload(section), 'new_section': _payload(new),
        'warnings': _warnings(section, new),
    })
