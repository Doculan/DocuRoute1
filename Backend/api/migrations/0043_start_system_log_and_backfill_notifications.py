"""Phase 2A, data: start the system log and carry existing notices over.

1. The rows the new tables need: the chain head, the monitoring lock and
   the provisional stage thresholds (Checkpoint 0, decision 6).
2. **Seq 1, `log_started`**, written by `system`. Notices sent before this
   moment have no "notified" rows, and none are invented: fabricated past
   events in a tamper-evident chain would be worse than the gap, which this
   row states.
3. Each existing notification gains its kind, severity, stored text,
   addressed office and post, manual, cause and dedupe key. An action notice
   counts as done only where the data shows it was; who did it is not
   recorded for these, so `acted_by` stays empty.

The message and hash code are **copies**, frozen here, so this migration
reads the same if the application's code changes later.
"""

import hashlib
import json
from datetime import datetime, timezone as dt_timezone

from django.db import migrations
from django.utils import timezone

GENESIS = '0' * 64
KIND_LABEL = {'encoder': 'Encoder', 'head': 'Head',
              'imr': 'Integrated Management Representative',
              'document_custodian': 'Document Custodian'}
ACTION, INFO = 'action', 'info'


def _hash(prev_hash, row):
    values = {
        'seq': row.seq, 'kind': row.kind, 'actor_id': row.actor_id,
        'actor_label': row.actor_label, 'position_id': row.position_id,
        'office_id': row.office_id, 'office_name_at_time': row.office_name_at_time,
        'proposal_id': row.proposal_id, 'manual_id': row.manual_id,
        'detail': row.detail,
        'at': row.at.astimezone(dt_timezone.utc).isoformat(timespec='microseconds'),
    }
    text = json.dumps(values, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256((prev_hash + text).encode('utf-8')).hexdigest()


def _title(event, proposal):
    """The 0034-era wording, as the inbox showed it."""
    manual = proposal.manual.title
    office = event.office_name_at_time
    if event.event == 'submitted':
        return f'{proposal.initiating_office.name} asks your office to concur on {manual}'
    if event.event == 'concurred':
        return f'{office} concurred on {manual}'
    if event.event == 'returned':
        return f'{office} returned {manual}'
    if event.event == 'locked':
        return (f'{manual} is locked as {proposal.dcr_number}' if proposal.dcr_number
                else f'{manual} is locked')
    if event.event == 'approval_uploaded':
        return f'Signed DCR for {manual} uploaded'
    return f'{event.event.replace("_", " ").capitalize()}: {manual}'


KIND = {'submitted': 'concurrence_requested', 'concurred': 'concurred',
        'returned': 'returned_by_office', 'locked': 'locked',
        'approval_uploaded': 'approval_uploaded'}


def forwards(apps, schema_editor):
    LogHead = apps.get_model('api', 'LogHead')
    JobLock = apps.get_model('api', 'JobLock')
    MonitoringSetting = apps.get_model('api', 'MonitoringSetting')
    SystemEvent = apps.get_model('api', 'SystemEvent')
    Notification = apps.get_model('api', 'Notification')
    PositionAssignment = apps.get_model('api', 'PositionAssignment')
    Concurrence = apps.get_model('api', 'Concurrence')
    ProposalParticipant = apps.get_model('api', 'ProposalParticipant')

    JobLock.objects.get_or_create(
        name='monitoring', defaults={'expires_at': datetime(2000, 1, 1, tzinfo=dt_timezone.utc)})
    for stage, days in (('with_head', 3), ('concurrence', 7), ('awaiting_signature', 14),
                        ('with_imr', 7), ('with_custodian', 10)):
        MonitoringSetting.objects.get_or_create(stage=stage, defaults={'days': days})

    if not SystemEvent.objects.exists():
        start = SystemEvent(
            seq=1, kind='log_started', actor=None, actor_label='system',
            office_name_at_time='', detail={
                'note': 'Notifications sent before this moment were not logged here.',
                'notifications_carried_over': Notification.objects.count(),
            },
            at=timezone.now(), prev_hash=GENESIS,
        )
        start.hash = _hash(GENESIS, start)
        start.save()
        LogHead.objects.update_or_create(log='system', defaults={'seq': 1, 'hash': start.hash})

    for notice in Notification.objects.select_related(
            'event', 'event__proposal', 'event__proposal__manual',
            'event__proposal__initiating_office', 'event__version'):
        event, proposal = notice.event, notice.event.proposal
        kind = KIND.get(event.event, event.event)

        # Which office and post the person was told as: a concurring
        # office for a request, otherwise the office that asked.
        offices = ([p.office_id for p in ProposalParticipant.objects.filter(
            proposal=proposal, role='concurring')]
            if event.event == 'submitted' else [proposal.initiating_office_id])
        mine = PositionAssignment.objects.filter(
            user_id=notice.user_id).select_related('position', 'position__office')
        posts = list(mine.filter(position__office_id__in=offices))
        custodian = False
        if not posts and event.event == 'approval_uploaded':
            # Not in the requesting office: told as the Document Custodian.
            posts, custodian = list(mine.filter(position__kind='document_custodian')), True
        # A current post before an ended one, then the Head before others.
        posts.sort(key=lambda a: (a.ends_on is not None, a.position.kind != 'head',
                                  -a.starts_on.toordinal()))
        position = posts[0].position if posts else None

        if event.event == 'submitted':
            severity = ACTION if position and position.kind == 'head' else INFO
        elif event.event in ('returned', 'locked'):
            severity = ACTION
        elif event.event == 'approval_uploaded':
            severity = ACTION if custodian else INFO
        else:
            severity = INFO

        acted = None
        if severity == ACTION:
            status = proposal.status
            if event.event == 'submitted':
                decided = Concurrence.objects.filter(
                    version=event.version, office_id=position.office_id).exists()
                if decided or status != 'concurrence':
                    acted = event.at
            elif event.event == 'returned':
                if proposal.versions.filter(number__gt=event.version.number,
                                            submitted_at__isnull=False).exists() \
                        or status == 'withdrawn':
                    acted = event.at
            elif event.event == 'locked':
                if status not in ('locked', 'awaiting_signature'):
                    acted = event.at
            elif event.event == 'approval_uploaded':
                if status != 'with_custodian':
                    acted = event.at

        notice.kind = kind
        notice.severity = severity
        notice.title = _title(event, proposal)[:120]
        notice.body = (event.detail or '')[:300] if event.event == 'returned' else ''
        notice.target_type, notice.target_id = 'proposal', proposal.pk
        notice.manual_id = proposal.manual_id
        notice.manual_title = proposal.manual.title
        notice.proposal_id = proposal.pk
        notice.audit_event_id = event.pk
        notice.dedupe_key = f'audit:{event.pk}'
        notice.acted_at = acted
        if position is not None:
            notice.addressed_position = position
            notice.addressed_office_id = position.office_id
            notice.addressed_office_name = position.office.name
            notice.addressed_position_title = f'{position.office.name} — {KIND_LABEL[position.kind]}'
        else:
            office = proposal.initiating_office
            notice.addressed_office_id = office.pk
            notice.addressed_office_name = office.name
        notice.save()


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0042_system_log_and_notification_fields'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
