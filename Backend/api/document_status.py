"""A document's official status: what the custodian records, what readers see.

Phase 4c. DCR section 5 - document number, version, revision, effectivity
date - recorded by the Document Custodian when a request is made
effective, or as a baseline for a document no request has touched yet.

Only models are imported here, so the reader views and the QMS views can
both use it without importing each other.
"""

import datetime

from django.utils import timezone
from rest_framework.response import Response


# --- reading the custodian's entry ---------------------------

_TEXT_FIELDS = (
    ('document_number', 'Document number', 64),
    ('version', 'Version', 32),
    ('revision', 'Revision', 32),
)


def _as_number(text):
    text = (text or '').strip()
    return int(text) if text.isdigit() else None


def revision_goes_backwards(current, new):
    """A lower revision than the current one, where both are plain numbers.

    Anything else - "Rev. 2", "A" - is recorded as written: the system
    cannot order what it cannot read, and refusing it would block real
    paperwork.
    """
    old, new = _as_number(current), _as_number(new)
    return old is not None and new is not None and new < old


def _date(data, field, label):
    raw = (data.get(field) or '').strip() if isinstance(data.get(field), str) else data.get(field)
    if not raw:
        return None, Response({
            'error': f'{label} is required.', 'field': field, 'reason': 'field_required',
        }, status=400)
    try:
        value = datetime.date.fromisoformat(str(raw))
    except ValueError:
        return None, Response({
            'error': f'{label} is not a date.', 'field': field, 'reason': 'invalid_date',
        }, status=400)
    if value > timezone.localdate():
        return None, Response({
            'error': (
                f'{label} is in the future. Record it on or after that date, '
                f'so readers never see text that is not yet in force.'
            ),
            'field': field, 'reason': 'future_date',
        }, status=400)
    return value, None


def read_status_fields(data, manual, with_ids_date):
    """The section 5 entry from a request body, or a response refusing it.

    `with_ids_date` is false for a baseline: the date the document was
    updated in the IDS belongs to a change, and a baseline records none.
    """
    fields = {}
    for field, label, limit in _TEXT_FIELDS:
        value = (data.get(field) or '').strip() if isinstance(data.get(field), str) else ''
        if not value:
            return None, Response({
                'error': f'{label} is required.', 'field': field, 'reason': 'field_required',
            }, status=400)
        if len(value) > limit:
            return None, Response({
                'error': f'{label} is too long.', 'field': field, 'reason': 'too_long',
            }, status=400)
        fields[field] = value

    dates = [('effective_on', 'The effectivity date')]
    if with_ids_date:
        dates.append(('updated_in_ids_on', 'The date updated in the IDS'))
    for field, label in dates:
        value, error = _date(data, field, label)
        if error:
            return None, error
        fields[field] = value

    current = manual.current_status
    if current is not None and revision_goes_backwards(current.revision, fields['revision']):
        return None, Response({
            'error': (
                f'Revision {fields["revision"]} is lower than the current '
                f'revision, {current.revision}.'
            ),
            'field': 'revision', 'reason': 'revision_backwards',
        }, status=400)
    return fields, None


def suggested_status(manual):
    """What the custodian's form starts with: the current entry, with the
    revision one higher where it is a plain number. They type over it."""
    current = manual.current_status
    today = timezone.localdate().isoformat()
    if current is None:
        return {'document_number': '', 'version': '', 'revision': '',
                'effective_on': today, 'updated_in_ids_on': today}
    number = _as_number(current.revision)
    return {
        'document_number': current.document_number,
        'version': current.version,
        'revision': str(number + 1) if number is not None else '',
        'effective_on': today,
        'updated_in_ids_on': today,
    }


# --- what readers see ----------------------------------------

def status_payload(status):
    """One recorded status, as every screen shows it. None stays None."""
    if status is None:
        return None
    proposal = status.proposal
    return {
        'document_number': status.document_number,
        'version': status.version,
        'revision': status.revision,
        'effective_on': status.effective_on,
        'updated_in_ids_on': status.updated_in_ids_on,
        'is_baseline': status.is_baseline,
        'dcr_number': proposal.dcr_number if proposal else None,
        'proposal_id': status.proposal_id,
        'recorded_as': status.recorded_as,
    }


def section_revision(section):
    """A section's own line: the revision under which a request last changed
    it. Nothing for a section no request has changed - the document's
    header carries the baseline for those."""
    status = section.status_changed
    if status is None:
        return None
    return {
        'revision': status.revision,
        'effective_on': status.effective_on,
        'dcr_number': status.proposal.dcr_number if status.proposal_id else None,
    }


def section_changes(section):
    """The requests that changed this section, newest first, for readers.

    Built from the history snapshots a request left behind, so it stays
    true after the request itself is long closed.
    """
    rows = section.history.filter(source='proposal', proposal__isnull=False).select_related(
        'proposal', 'proposal__document_status',
    ).order_by('-version')
    changes = []
    for row in rows:
        status = getattr(row.proposal, 'document_status', None)
        changes.append({
            'dcr_number': row.proposal.dcr_number,
            'revision': status.revision if status else None,
            'effective_on': status.effective_on if status else None,
            'reason': row.change_reason,
            'text_before': row.content,
        })
    return changes
