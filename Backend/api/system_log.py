"""The system activity log: append-only, hash-chained.

Every row's hash covers the previous row's hash and the row's own stored
values, so editing or deleting any row breaks the chain from that point -
`verify()` finds where. Rows are written only through `record()`, which
locks the chain head for the length of the insert: two writers queue for
it rather than both extending the same link.

Callers are inside a transaction already (the action that caused the
event), or `record()` opens one; either way the head is held only until
that transaction ends, which is why callers keep their transactions short.
"""

import hashlib
import json
from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from .models import LogHead, SystemEvent

LOG = 'system'
GENESIS = '0' * 64


def canonical(values):
    """One fixed spelling of a row, so the same row always hashes the same."""
    return json.dumps(values, sort_keys=True, separators=(',', ':'), default=str)


def hashed_values(event):
    return {
        'seq': event.seq,
        'kind': event.kind,
        'actor_id': event.actor_id,
        'actor_label': event.actor_label,
        'position_id': event.position_id,
        'office_id': event.office_id,
        'office_name_at_time': event.office_name_at_time,
        'proposal_id': event.proposal_id,
        'manual_id': event.manual_id,
        'detail': event.detail,
        'at': event.at.astimezone(dt_timezone.utc).isoformat(timespec='microseconds'),
    }


def compute_hash(prev_hash, event):
    return hashlib.sha256(
        (prev_hash + canonical(hashed_values(event))).encode('utf-8')
    ).hexdigest()


def actor_fields(user=None, label=None):
    """`system` when no person acted; otherwise the person and how they
    acted (a position title, or "System administrator")."""
    if user is None:
        return {'actor': None, 'actor_label': SystemEvent.SYSTEM}
    return {'actor': user, 'actor_label': label or user.get_full_name() or user.username}


def locked_head():
    """The chain head, locked for this transaction.

    Rebuilt from the last row if it is missing - the migration seeds it,
    but a flushed database takes it, and the chain itself still says where
    it ends. Two writers rebuilding at once meet the primary key.
    """
    head = LogHead.objects.select_for_update().filter(log=LOG).first()
    if head is None:
        last = SystemEvent.objects.order_by('-seq').first()
        LogHead.objects.get_or_create(log=LOG, defaults={
            'seq': last.seq if last else 0,
            'hash': last.hash if last else GENESIS,
        })
        head = LogHead.objects.select_for_update().get(log=LOG)
    return head


def record(kind, *, user=None, label=None, position=None, office=None,
           proposal=None, manual=None, detail=None, at=None):
    """Append one event and return it."""
    with transaction.atomic():
        head = locked_head()
        event = SystemEvent(
            seq=head.seq + 1, kind=kind, position=position, office=office,
            office_name_at_time=office.name if office is not None else '',
            proposal=proposal, manual=manual,
            # Round-tripped through JSON first, so the value hashed is the
            # value read back later (tuples become lists, keys strings).
            detail=json.loads(canonical(detail or {})),
            # Microseconds kept, then read back exactly as stored.
            at=at or timezone.now(), prev_hash=head.hash,
            **actor_fields(user, label),
        )
        event.hash = compute_hash(head.hash, event)
        event.save(force_insert=True)
        head.seq, head.hash = event.seq, event.hash
        head.save(update_fields=['seq', 'hash'])
    return event


def verify():
    """Walk the chain in order. Returns `(rows_checked, problem or None)`."""
    previous, expected_seq, checked = GENESIS, 1, 0
    for event in SystemEvent.objects.order_by('seq').iterator(chunk_size=2000):
        if event.seq != expected_seq:
            return checked, f'seq {expected_seq} is missing (found {event.seq})'
        if event.prev_hash != previous:
            return checked, f'seq {event.seq} does not follow seq {event.seq - 1}'
        if compute_hash(previous, event) != event.hash:
            return checked, f'seq {event.seq} was changed after it was written'
        previous, expected_seq, checked = event.hash, expected_seq + 1, checked + 1
    head = LogHead.objects.filter(log=LOG).first()
    if head is not None and (head.seq, head.hash) != (checked, previous):
        return checked, f'the chain ends at seq {checked} but the head says {head.seq}'
    return checked, None
