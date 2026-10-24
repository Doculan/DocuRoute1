"""In-app notifications: who is told about what, and when it is done.

**Positions, not people.** A notice goes to whoever holds the post today.
A person holding two posts in the office gets one notice, addressed to the
first of Head, Encoder, IMR, Custodian - the unique (recipient, dedupe
key) makes that hold even under a race.

**Two severities.** *Action required* clears only when the thing is done,
by anyone entitled to do it: once the Head concurs, the Encoder's copy
clears too, and `acted_by` names the Head. *Info* clears when read. Where
only the Head can act, the Encoder's copy is info - they can nudge, not
act.

**Written once, never rebuilt.** Title and body are stored when the notice
is created, from the facts of that moment.

Every notice is created by `create()`, which also writes one `notified`
row to the system log listing who was told. Every resolving action writes
one `notification_acted` row listing the notices it cleared, and every
first read one `notification_read` row. That is the trail of who was
told, when, and what they did.

| Event | Who is told | Severity |
|---|---|---|
| Sent to the Head | The Head (none: the parent office's Head and the system admin) | action |
| Returned to the Encoder | The Encoders (none: the Head) | action |
| Recalled by the Encoder | The Head | info |
| Submitted (or resubmitted) | Each concurring office | Head action, Encoder info |
| Returned by an office | Initiating office | action |
| Concurred | Initiating office | info |
| Locked | Initiating office | action (sign and upload) |
| Signed copies complete | IMR | action |
| Package fixed after a return | Document Custodian | action |
| IMR accepts | Initiating office | info |
| IMR denies | Initiating office and every participating office (concurring and approving) | info |
| Signed DCR uploaded | Initiating office; Document Custodian | info; action |
| Package returned | Initiating office (and the IMR for the DCR) | action |
| Made effective | Initiating office and every participating office (concurring and approving) | info |
| Withdrawn | Initiating office, and concurring offices once submitted | info |

Stall and vacancy notices come from `monitoring.py`.
"""

from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone

from . import system_log
from .generation.common import position_title
from .models import (
    Attachment, AuditEvent, Concurrence, Notification, Position,
    PositionAssignment, ProposalParticipant, QmsDecision, SystemEvent,
)

ACTION, INFO = Notification.ACTION, Notification.INFO

# Who a notice is addressed to, when a person holds several posts.
_POST_ORDER = {Position.HEAD: 0, Position.ENCODER: 1, Position.IMR: 2,
               Position.DOCUMENT_CUSTODIAN: 3}

EXCERPT = 160


@dataclass(frozen=True)
class Recipient:
    user_id: int
    office: object
    position: object
    title: str
    severity: str


def current_posts(office_ids=None, kinds=None):
    """Current assignments - at these offices, or anywhere for `kinds` -
    Head first, so a person's notice is addressed to their senior post."""
    today = timezone.localdate()
    query = PositionAssignment.objects.filter(
        starts_on__lte=today, user__is_active=True,
        position__is_active=True, position__office__is_active=True,
    ).filter(
        Q(ends_on__isnull=True) | Q(ends_on__gte=today)
    ).select_related('position', 'position__office')
    if office_ids is not None:
        query = query.filter(position__office_id__in=list(office_ids))
    if kinds:
        query = query.filter(position__kind__in=kinds)
    return sorted(query, key=lambda a: (_POST_ORDER.get(a.position.kind, 9), a.pk))


def _recipient(assignment, severity):
    position = assignment.position
    return Recipient(assignment.user_id, position.office, position,
                     position_title(position.office.name, position.kind), severity)


def office_recipients(office_ids, *, head=ACTION, encoder=ACTION):
    """The Head and Encoders of these offices, each with a severity; None
    leaves that post out."""
    by_kind = {Position.HEAD: head, Position.ENCODER: encoder}
    return [
        _recipient(a, by_kind[a.position.kind])
        for a in current_posts(office_ids, [Position.HEAD, Position.ENCODER])
        if by_kind[a.position.kind] is not None
    ]


def qms_recipients(kind, severity=ACTION):
    """Whoever holds the IMR or Document Custodian post, wherever it sits."""
    return [_recipient(a, severity) for a in current_posts(kinds=[kind])]


def create(kind, recipients, *, title, dedupe_key, body='', proposal=None,
           manual=None, audit_event=None, system_event=None, target=None,
           office_level=False, exclude_user_id=None, now=None):
    """The one way a notification is written. Returns the rows created.

    `office_level` marks a notice about an office as a whole; every other
    notice must name its manual, which the database checks.
    """
    now = now or timezone.now()
    chosen = {}
    for recipient in recipients:
        if recipient.user_id != exclude_user_id:
            chosen.setdefault(recipient.user_id, recipient)
    if not chosen:
        return []
    told = set(Notification.objects.filter(
        dedupe_key=dedupe_key, recipient_id__in=list(chosen),
    ).values_list('recipient_id', flat=True))
    target_type, target_id = target or (
        ('proposal', proposal.pk) if proposal is not None else ('', None))
    rows = [
        Notification(
            recipient_id=user_id, kind=kind, severity=r.severity,
            addressed_office=r.office,
            addressed_office_name=r.office.name if r.office is not None else '',
            addressed_position=r.position, addressed_position_title=r.title,
            title=title[:120], body=body[:300],
            target_type=target_type, target_id=target_id,
            office_level=office_level, manual=manual,
            manual_title=manual.title if manual is not None else '',
            proposal=proposal, audit_event=audit_event, system_event=system_event,
            dedupe_key=dedupe_key, created_at=now,
        )
        for user_id, r in chosen.items() if user_id not in told
    ]
    if not rows:
        return []
    Notification.objects.bulk_create(rows, ignore_conflicts=True)
    cause = ({'audit_event': audit_event.pk} if audit_event is not None
             else {'system_event': system_event.pk})
    system_log.record(
        SystemEvent.NOTIFIED, proposal=proposal, manual=manual, at=now,
        detail={
            'kind': kind, 'dedupe_key': dedupe_key, 'cause': cause,
            'recipients': [
                {'user': n.recipient_id, 'as': n.addressed_position_title,
                 'severity': n.severity} for n in rows
            ],
        },
    )
    return rows


def create_batch(kind, entries, *, dedupe_key, system_event, target, now=None):
    """Many notices for one cause, each office its own words - a deadline
    set for hundreds of offices - in one insert and one `notified` row.

    `entries`: dicts of recipients, title, body and manual_id (None makes
    the notice office-level). One notice per person, as in `create`.
    """
    from .models import Manual
    now = now or timezone.now()
    chosen = {}
    for entry in entries:
        for recipient in entry['recipients']:
            chosen.setdefault(recipient.user_id, (recipient, entry))
    if not chosen:
        return []
    told = set(Notification.objects.filter(
        dedupe_key=dedupe_key, recipient_id__in=list(chosen),
    ).values_list('recipient_id', flat=True))
    titles = dict(Manual.objects.filter(
        pk__in={e['manual_id'] for _, e in chosen.values() if e['manual_id']},
    ).values_list('pk', 'title'))
    rows = [
        Notification(
            recipient_id=user_id, kind=kind, severity=r.severity,
            addressed_office=r.office,
            addressed_office_name=r.office.name if r.office is not None else '',
            addressed_position=r.position, addressed_position_title=r.title,
            title=entry['title'][:120], body=entry['body'][:300],
            target_type=target[0], target_id=target[1],
            office_level=entry['manual_id'] is None, manual_id=entry['manual_id'],
            manual_title=titles.get(entry['manual_id'], ''),
            system_event=system_event, dedupe_key=dedupe_key, created_at=now,
        )
        for user_id, (r, entry) in chosen.items() if user_id not in told
    ]
    if not rows:
        return []
    Notification.objects.bulk_create(rows, batch_size=500, ignore_conflicts=True)
    system_log.record(
        SystemEvent.NOTIFIED, at=now,
        detail={
            'kind': kind, 'dedupe_key': dedupe_key,
            'cause': {'system_event': system_event.pk},
            'recipients': [{'user': n.recipient_id, 'as': n.addressed_position_title,
                            'severity': n.severity} for n in rows],
        },
    )
    return rows


def resolve(queryset, *, by=None, label=None, proposal=None, now=None,
            reason=''):
    """Clear open action notices and write one `notification_acted` row
    naming them. Returns the ids cleared."""
    now = now or timezone.now()
    ids = list(queryset.filter(severity=ACTION, acted_at__isnull=True)
               .values_list('pk', flat=True))
    if not ids:
        return []
    Notification.objects.filter(pk__in=ids).update(acted_at=now, acted_by=by)
    system_log.record(
        SystemEvent.NOTIFICATION_ACTED, user=by, label=label,
        proposal=proposal, at=now,
        detail={'notices': ids, **({'reason': reason} if reason else {})},
    )
    return ids


def mark_read(user, proposal_id=None, ids=None):
    """Mark this person's unread notices read - all, one proposal's, or the
    ids given - and log the first read. Returns how many changed."""
    unread = Notification.objects.filter(recipient=user, read_at__isnull=True)
    if proposal_id is not None:
        unread = unread.filter(proposal_id=proposal_id)
    if ids is not None:
        unread = unread.filter(pk__in=ids)
    read = list(unread.values_list('pk', flat=True))
    if not read:
        return 0
    now = timezone.now()
    Notification.objects.filter(pk__in=read).update(read_at=now)
    system_log.record(SystemEvent.NOTIFICATION_READ, user=user, at=now,
                      detail={'notices': read})
    return len(read)


def open_q():
    """What the bell counts: unread info, and action not yet done."""
    return (Q(severity=INFO, read_at__isnull=True)
            | Q(severity=ACTION, acted_at__isnull=True))


def bell_count(user):
    return Notification.objects.filter(recipient=user).filter(open_q()).count()


def payload(notice):
    return {
        'id': notice.id,
        'kind': notice.kind,
        'severity': notice.severity,
        'title': notice.title,
        'body': notice.body,
        'target': ({'type': notice.target_type, 'id': notice.target_id}
                   if notice.target_type else None),
        'proposal_id': notice.proposal_id,
        'manual_id': notice.manual_id,
        'manual': notice.manual_title,
        'addressed_to': notice.addressed_position_title,
        'created_at': notice.created_at,
        'read': notice.read_at is not None,
        'acted': notice.acted_at is not None,
        'acted_at': notice.acted_at,
    }


# ─── From proposal events ────────────────────────────────────

def _excerpt(text):
    text = ' '.join((text or '').split())
    return text if len(text) <= EXCERPT else text[:EXCERPT - 1].rstrip() + '…'


def _concurring_ids(proposal):
    return list(proposal.participants.filter(
        role=ProposalParticipant.CONCURRING).values_list('office_id', flat=True))


def _participant_ids(proposal):
    """Every office in the request: concurring, and the approving route
    (the owner and the levels above it) - they signed, or would have."""
    return list(proposal.participants.values_list('office_id', flat=True).distinct())


def _actor_label(event):
    if event.position is not None:
        return position_title(event.office_name_at_time, event.position.kind)
    return event.actor.get_full_name() or event.actor.username


def _messages(event):
    """(kind, recipients, title, body[, tell_the_actor]) for each notice
    this event sends. The actor is left out unless the fifth is True."""
    proposal = event.proposal
    manual = proposal.manual.title
    initiating = [proposal.initiating_office_id]
    office = event.office_name_at_time
    number = proposal.dcr_number or manual
    kind = event.event

    if kind == AuditEvent.SENT_TO_HEAD:
        heads = office_recipients(initiating, head=ACTION, encoder=None)
        if heads:
            return [(Notification.SENT_TO_HEAD, heads, f'{manual} is with you to submit',
                     f'Sent by {office} — Encoder. Submit it, or return it with a note.')]
        # No Head to send it to: the office above, and the admin who fills posts.
        from .monitoring import system_admins
        parent = proposal.initiating_office.parent_id
        above = office_recipients([parent], head=ACTION, encoder=None) if parent else []
        return [(Notification.SENT_TO_HEAD, above + system_admins(),
                 f'{manual} is waiting for a Head',
                 f'{office} has no current Head to submit it.')]
    if kind == AuditEvent.RETURNED_TO_ENCODER:
        encoders = office_recipients(initiating, head=None, encoder=ACTION)
        if encoders:
            return [(Notification.RETURNED_TO_ENCODER, encoders,
                     f'Your Head returned {manual}', f'“{_excerpt(event.detail)}”')]
        # No Encoder to redraft it: it stays with the Head, who is told so.
        return [(Notification.RETURNED_TO_ENCODER,
                 office_recipients(initiating, head=ACTION, encoder=None),
                 f'{manual} is back in draft', 'The office has no current Encoder to redraft it.',
                 True)]
    if kind == AuditEvent.RECALLED:
        return [(Notification.RECALLED, office_recipients(initiating, head=INFO, encoder=None),
                 f'{manual} was recalled by the Encoder', 'It is back in draft.')]
    if kind == AuditEvent.SUBMITTED:
        version = event.version.number if event.version else 1
        return [(Notification.CONCURRENCE_REQUESTED,
                 office_recipients(_concurring_ids(proposal), head=ACTION, encoder=INFO),
                 f'{proposal.initiating_office.name} asks your office to concur on {manual}',
                 f'Version {version}.' if version > 1 else '')]
    if kind == AuditEvent.CONCURRED:
        return [(Notification.CONCURRED, office_recipients(initiating, head=INFO, encoder=INFO),
                 f'{office} concurred on {manual}', '')]
    if kind == AuditEvent.RETURNED:
        returned = Concurrence.objects.filter(
            version=event.version, office=event.office, decision=Concurrence.RETURN,
        ).select_related('section').first()
        where = f' — {returned.section.subtitle}' if returned and returned.section else ''
        return [(Notification.RETURNED_BY_OFFICE, office_recipients(initiating),
                 f'{office} returned {manual}', f'“{_excerpt(event.detail)}”{where}')]
    if kind == AuditEvent.LOCKED:
        return [(Notification.LOCKED, office_recipients(initiating),
                 f'{manual} is locked as {proposal.dcr_number}' if proposal.dcr_number
                 else f'{manual} is locked',
                 'Print, sign and upload the signed copies.')]
    if kind == AuditEvent.PACKAGE_COMPLETE:
        if proposal.status == proposal.READY_FOR_IMR:
            return [(Notification.READY_FOR_IMR, qms_recipients(Position.IMR),
                     f'{number} is ready for your decision',
                     f'{manual}, from {proposal.initiating_office.name}.')]
        if proposal.status == proposal.WITH_CUSTODIAN:
            return [(Notification.PACKAGE_RESUBMITTED, qms_recipients(Position.DOCUMENT_CUSTODIAN),
                     f'{number} is back with you', 'The returned copies were replaced.')]
        return []
    if kind == AuditEvent.IMR_ACCEPTED:
        return [(Notification.IMR_ACCEPTED, office_recipients(initiating, head=INFO, encoder=INFO),
                 f'The IMR accepted {number}', 'Next: the approving authority signs.')]
    if kind == AuditEvent.IMR_DENIED:
        offices = initiating + _participant_ids(proposal)
        return [(Notification.IMR_DENIED, office_recipients(offices, head=INFO, encoder=INFO),
                 f'The IMR denied {number}', f'“{_excerpt(event.detail)}”')]
    if kind == AuditEvent.APPROVAL_UPLOADED:
        by = 'the IMR' if event.position and event.position.kind == Position.IMR else office
        return [
            (Notification.APPROVAL_UPLOADED, office_recipients(initiating, head=INFO, encoder=INFO),
             f'Signed DCR for {manual} uploaded by {by}', 'Awaiting Document Custodian acceptance.'),
            (Notification.APPROVAL_UPLOADED, qms_recipients(Position.DOCUMENT_CUSTODIAN),
             f'Signed DCR for {manual} uploaded by {by}', 'Accept it or return it.'),
        ]
    if kind == AuditEvent.PACKAGE_RETURNED:
        decision = QmsDecision.objects.filter(
            proposal=proposal, stage=QmsDecision.CUSTODIAN, outcome=QmsDecision.RETURN,
        ).order_by('-decided_at').first()
        recipients = office_recipients(initiating)
        if decision and Attachment.APPROVED_DCR in (decision.returned_kinds or []):
            recipients += qms_recipients(Position.IMR)
        return [(Notification.PACKAGE_RETURNED, recipients,
                 f'The custodian returned {number}', f'“{_excerpt(event.detail)}”')]
    if kind == AuditEvent.MADE_EFFECTIVE:
        offices = initiating + _participant_ids(proposal)
        return [(Notification.MADE_EFFECTIVE, office_recipients(offices, head=INFO, encoder=INFO),
                 f'{manual} is effective', event.detail)]
    if kind == AuditEvent.WITHDRAWN:
        offices = initiating + _concurring_ids(proposal)
        return [(Notification.WITHDRAWN, office_recipients(offices, head=INFO, encoder=INFO),
                 f'{proposal.initiating_office.name} withdrew {manual}',
                 f'“{_excerpt(event.detail)}”')]
    return []


# Which open notices an event clears. `None` for the office means every
# office's copy; 'event' means only the office that acted.
_CLEARS = {
    AuditEvent.SENT_TO_HEAD: [(Notification.RETURNED_TO_ENCODER, None)],
    AuditEvent.RECALLED: [(Notification.SENT_TO_HEAD, None)],
    AuditEvent.RETURNED_TO_ENCODER: [(Notification.SENT_TO_HEAD, None)],
    AuditEvent.SUBMITTED: [(Notification.RETURNED_BY_OFFICE, None),
                           (Notification.SENT_TO_HEAD, None),
                           (Notification.RETURNED_TO_ENCODER, None)],
    AuditEvent.CONCURRED: [(Notification.CONCURRENCE_REQUESTED, 'event'),
                           (Notification.STALLED, 'event')],
    AuditEvent.RETURNED: [(Notification.CONCURRENCE_REQUESTED, None)],
    AuditEvent.LOCKED: [(Notification.CONCURRENCE_REQUESTED, None)],
    AuditEvent.PACKAGE_COMPLETE: [(Notification.LOCKED, None),
                                  (Notification.PACKAGE_RETURNED, None)],
    AuditEvent.IMR_ACCEPTED: [(Notification.READY_FOR_IMR, None)],
    AuditEvent.IMR_DENIED: [(Notification.READY_FOR_IMR, None)],
    AuditEvent.APPROVAL_UPLOADED: [],
    AuditEvent.PACKAGE_RETURNED: [(Notification.APPROVAL_UPLOADED, None),
                                  (Notification.PACKAGE_RESUBMITTED, None)],
    AuditEvent.MADE_EFFECTIVE: [(Notification.APPROVAL_UPLOADED, None),
                                (Notification.PACKAGE_RESUBMITTED, None)],
}

# Events that move a proposal to a new stage end any stall in the old one.
_ENDS_STALLS = {
    AuditEvent.SENT_TO_HEAD, AuditEvent.RECALLED, AuditEvent.RETURNED_TO_ENCODER,
    AuditEvent.SUBMITTED, AuditEvent.RETURNED, AuditEvent.LOCKED,
    AuditEvent.DOCUMENTS_GENERATED, AuditEvent.PACKAGE_COMPLETE,
    AuditEvent.IMR_ACCEPTED, AuditEvent.IMR_DENIED, AuditEvent.APPROVAL_UPLOADED,
    AuditEvent.PACKAGE_RETURNED, AuditEvent.MADE_EFFECTIVE, AuditEvent.WITHDRAWN,
}


def _clearing_query(event):
    proposal = event.proposal
    if event.event == AuditEvent.WITHDRAWN:
        return Notification.objects.filter(proposal=proposal)
    rules = list(_CLEARS.get(event.event, []))
    if event.event in _ENDS_STALLS:
        rules.append((Notification.STALLED, None))
    if not rules:
        return None
    match = Q()
    for kind, office in rules:
        rule = Q(kind=kind)
        if office == 'event':
            rule &= Q(addressed_office_id=event.office_id)
        match |= rule
    return Notification.objects.filter(proposal=proposal).filter(match)


def notify(event):
    """Clear what this event finishes, then tell whoever must hear of it.

    Called inside the transaction that writes the event, so an event that
    rolls back takes its notices with it. Returns how many were created.
    """
    clearing = _clearing_query(event)
    if clearing is not None:
        resolve(clearing, by=event.actor, label=_actor_label(event),
                proposal=event.proposal, now=event.at)
    created = 0
    for kind, recipients, title, body, *tell_actor in _messages(event):
        created += len(create(
            kind, recipients, title=title, body=body,
            dedupe_key=f'audit:{event.pk}',
            proposal=event.proposal, manual=event.proposal.manual,
            audit_event=event, now=event.at,
            exclude_user_id=None if tell_actor and tell_actor[0] else event.actor_id,
        ))
    return created
