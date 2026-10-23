"""A synthetic university at the size the monitoring update must handle.

    py manage.py seed_scale                 # 500 offices, 3,000 manuals, ...
    py manage.py seed_scale --fraction 0.1  # a tenth of that
    py manage.py seed_scale --clear

**For measuring, not for showing.** `seed_demo_org` is a small, readable
organisation for demonstrations; this is a large, meaningless one for
timing screens against (MONITORING_UPDATE_SPEC.md, sections 3 and 9).
Every name in it says "Synthetic".

Run it on a scratch database - `SQLITE_PATH` or `DATABASE_URL` pointed at
a copy - never on the one holding the university's data. It enforces the
part of that it can:

**It refuses if real data exists.** Any office, manual series, manual or
proposal it did not create - the demo organisation's included - stops it.
Synthetic rows beside real ones could not be told apart afterwards.

**It records what it created, row by row**, in `DemoRecord` under its own
source, so `--clear` removes exactly those rows and `seed_demo_org
--clear` never touches them.

What it seeds, at `--fraction 1`:

| | |
|---|---|
| Offices | 500: a President, 6 VPs (approving levels), 24 directorates, units, and one QMS office |
| People | a Head for every office and an Encoder for every unit; ~3% of unit Heads vacant; a few concurrent Heads |
| Manual series | 30, five per VP, each with concurring and reader units |
| Manuals | 3,000, five sections each; 5% override their series' offices |
| Proposals | 5,000 open (drafting, concurrence and every frozen status) and 2,000 closed |
| Trail | versions, frozen participants, concurrences, audit events and notifications to match |

**Deadlines are not seeded yet**: the model arrives in Phase 3, and this
command gains them then.
"""

import random
from contextlib import contextmanager
from datetime import timedelta

from django.apps import apps
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api.models import (
    AuditEvent, Concurrence, CustomUser, DemoRecord, Manual, ManualOffice,
    ManualSection, ManualSeries, ManualSeriesOffice, Notification, Office,
    OfficeLink, Position, PositionAssignment, Proposal, ProposalParticipant,
    ProposalVersion, SectionChange,
)

SCALE_PASSWORD = 'Scale123!'

TARGETS = {
    'offices': 500,
    'manuals': 3000,
    'open_proposals': 5000,
    'closed_proposals': 2000,
}

SECTIONS_PER_MANUAL = 5

# Open work, by status. Shares of `open_proposals`.
OPEN_MIX = [
    (Proposal.DRAFT, 0.30),
    (Proposal.CONCURRENCE, 0.40),
    (Proposal.LOCKED, 0.03),
    (Proposal.AWAITING_SIGNATURE, 0.08),
    (Proposal.READY_FOR_IMR, 0.06),
    (Proposal.AWAITING_APPROVAL, 0.05),
    (Proposal.WITH_CUSTODIAN, 0.06),
    (Proposal.PACKAGE_RETURNED, 0.02),
]
CLOSED_MIX = [
    (Proposal.EFFECTIVE, 0.70),
    (Proposal.DENIED, 0.10),
    (Proposal.WITHDRAWN, 0.20),
]

# Children before parents, so a PROTECT never fires on the way out.
CLEAR_ORDER = [
    Notification, AuditEvent, Concurrence, SectionChange,
    ProposalParticipant, ProposalVersion, Proposal,
    ManualSection, ManualOffice, ManualSeriesOffice, Manual, ManualSeries,
    PositionAssignment, Position, CustomUser, Office,
]

# Rows the refusal looks at: what makes a database "real".
REAL_DATA = [Office, ManualSeries, Manual, Proposal]

CHUNK = 900


def _label(model):
    return f'{model._meta.app_label}.{model._meta.object_name}'


@contextmanager
def _dates_as_given(*models):
    """Let `bulk_create` keep the timestamps the seeder chose.

    `auto_now_add` and `auto_now` overwrite them on insert, which would put
    every synthetic proposal at today and leave nothing to age.
    """
    touched = []
    for model in models:
        for field in model._meta.concrete_fields:
            if getattr(field, 'auto_now', False) or getattr(field, 'auto_now_add', False):
                touched.append((field, field.auto_now, field.auto_now_add))
                field.auto_now = field.auto_now_add = False
    try:
        yield
    finally:
        for field, auto_now, auto_now_add in touched:
            field.auto_now, field.auto_now_add = auto_now, auto_now_add


class Command(BaseCommand):
    help = 'Seed a large synthetic organisation for performance measurement.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear', action='store_true',
            help='remove exactly what this command created, and stop',
        )
        parser.add_argument(
            '--fraction', type=float, default=1.0,
            help='seed this share of the targets (default 1 = full scale)',
        )
        parser.add_argument('--seed', type=int, default=4200)

    # -- bookkeeping ----------------------------------------------

    def _mine(self):
        return DemoRecord.objects.filter(source=DemoRecord.SCALE)

    def _record(self, model, objs):
        """Record a batch of created rows. One DemoRecord per row: the
        clear has to be exact, not a guess from names."""
        label = _label(model)
        start = self._sequence
        DemoRecord.objects.bulk_create([
            DemoRecord(
                source=DemoRecord.SCALE, label=label, object_id=str(obj.pk),
                kind=DemoRecord.CREATED, sequence=start + i + 1,
            ) for i, obj in enumerate(objs)
        ], batch_size=CHUNK)
        self._sequence += len(objs)
        self._counts[label] = self._counts.get(label, 0) + len(objs)
        return objs

    def _create(self, model, objs):
        created = model.objects.bulk_create(objs, batch_size=CHUNK)
        return self._record(model, created)

    # -- clearing --------------------------------------------------

    def _clear(self):
        records = self._mine()
        if not records.exists():
            self.stdout.write('Nothing to clear - no scale data recorded.')
            return

        removed = 0
        with transaction.atomic():
            # The tree first: an office's parent is PROTECT, and deleting
            # in chunks could otherwise meet a child in a later chunk.
            office_ids = list(records.filter(
                label=_label(Office)).values_list('object_id', flat=True))
            for start in range(0, len(office_ids), CHUNK):
                Office.objects.filter(
                    pk__in=office_ids[start:start + CHUNK]
                ).update(parent=None, merged_into=None)

            for model in CLEAR_ORDER:
                ids = list(records.filter(label=_label(model))
                           .values_list('object_id', flat=True))
                for start in range(0, len(ids), CHUNK):
                    deleted, _ = model.objects.filter(
                        pk__in=ids[start:start + CHUNK]
                    ).delete()
                    removed += deleted
            records.delete()

        self.stdout.write(self.style.SUCCESS(f'Removed {removed} synthetic row(s).'))

    # -- seeding ---------------------------------------------------

    def _refusal(self):
        """Why this database may not be seeded, or None."""
        for model in REAL_DATA:
            ours = self._mine().filter(label=_label(model)).values_list(
                'object_id', flat=True)
            real = model.objects.exclude(pk__in=[int(i) for i in ours])
            if real.exists():
                return (
                    f'Refusing to seed: {real.count()} '
                    f'{model._meta.verbose_name_plural} exist that this '
                    f'command did not create. Synthetic data beside real '
                    f'data could not be told apart afterwards. Point '
                    f'SQLITE_PATH or DATABASE_URL at an empty scratch '
                    f'database.'
                )
        if self._mine().exists():
            return 'Scale data is already seeded. Run --clear to start over.'
        return None

    def handle(self, *args, **options):
        self._sequence = self._mine().count()
        self._counts = {}

        if options['clear']:
            self._clear()
            return

        fraction = options['fraction']
        if not 0 < fraction <= 1:
            raise CommandError('--fraction must be above 0 and at most 1.')

        refusal = self._refusal()
        if refusal:
            self.stderr.write(refusal)
            return

        self.rng = random.Random(options['seed'])
        self.now = timezone.now()
        self.today = timezone.localdate()
        self.n = {
            'offices': max(20, round(TARGETS['offices'] * fraction)),
            'manuals': max(10, round(TARGETS['manuals'] * fraction)),
            'open': max(10, round(TARGETS['open_proposals'] * fraction)),
            'closed': max(5, round(TARGETS['closed_proposals'] * fraction)),
        }

        with transaction.atomic(), _dates_as_given(
            Proposal, ProposalVersion, Concurrence, AuditEvent, Notification,
        ):
            self._offices()
            self._people()
            self._series_and_manuals()
            self._proposals()

        self.stdout.write(self.style.SUCCESS('\nSynthetic organisation seeded.'))
        for label, count in self._counts.items():
            self.stdout.write(f'  {label:<26} {count:>7}')
        self.stdout.write(f'  Password for every synthetic account: {SCALE_PASSWORD}')
        self.stdout.write('\nTo remove exactly this data:\n'
                          '    py manage.py seed_scale --clear')

    # -- the organisation -----------------------------------------

    def _offices(self):
        total = self.n['offices']
        full = total >= 100
        vp_count, per_vp = (6, 4) if full else (2, 2)

        self.president = self._create(Office, [Office(
            name='Synthetic Office of the President', abbreviation='S-OP',
            is_approving_level=True,
        )])[0]
        self.vps = self._create(Office, [Office(
            name=f'Synthetic Office of the VP {v + 1}', abbreviation=f'S-VP{v + 1}',
            parent=self.president, is_approving_level=True,
        ) for v in range(vp_count)])
        self.directorates = self._create(Office, [Office(
            name=f'Synthetic Directorate {v + 1}.{d + 1}',
            abbreviation=f'S-D{v + 1}.{d + 1}', parent=vp,
        ) for v, vp in enumerate(self.vps) for d in range(per_vp)])

        self.qms = self._create(Office, [Office(
            name='Synthetic Quality Management Office', abbreviation='S-QMS',
            parent=self.directorates[0],
        )])[0]

        unit_count = total - 1 - len(self.vps) - len(self.directorates) - 1
        self.units = self._create(Office, [Office(
            name=f'Synthetic Unit {u + 1:04d}', abbreviation=f'S-U{u + 1:04d}',
            parent=self.directorates[u % len(self.directorates)],
        ) for u in range(unit_count)])

        # Which VP each unit sits under, for series membership.
        directorate_vp = {d.pk: d.parent_id for d in self.directorates}
        self.units_by_vp = {}
        for unit in self.units:
            self.units_by_vp.setdefault(directorate_vp[unit.parent_id], []).append(unit)

    def _people(self):
        password = make_password(SCALE_PASSWORD)
        heads_for = [self.president, *self.vps, *self.directorates, *self.units]

        positions = []
        for office in heads_for:
            positions.append(Position(office=office, kind=Position.HEAD))
        for unit in self.units:
            positions.append(Position(office=unit, kind=Position.ENCODER))
        positions.append(Position(office=self.qms, kind=Position.IMR))
        positions.append(Position(office=self.qms, kind=Position.DOCUMENT_CUSTODIAN))
        positions = self._create(Position, positions)

        # Vacant Heads: the position exists and nobody holds it, the case
        # the monitoring update has to escalate.
        unit_ids = {u.pk for u in self.units}
        vacant = {
            p.pk for p in positions
            if p.kind == Position.HEAD and p.office_id in unit_ids
            and self.rng.random() < 0.03
        }

        people, holds = [], []
        for position in positions:
            if position.pk in vacant:
                continue
            number = len(people) + 1
            qms = position.kind in Position.QMS_KINDS
            people.append(CustomUser(
                username=f'scale_{number:05d}', password=password,
                full_name=f'Synthetic Person {number:05d}',
                role='staff', is_approved=True,
                system_role=CustomUser.QMS_STAFF if qms else CustomUser.USER,
            ))
            holds.append(position)
        people = self._create(CustomUser, people)

        start = self.today - timedelta(days=400)
        assignments = [
            PositionAssignment(user=person, position=position, starts_on=start)
            for person, position in zip(people, holds)
        ]

        # Concurrent heads: a few unit Heads also head a second unit whose
        # Head post is vacant - one person, two offices.
        vacant_positions = [p for p in positions if p.pk in vacant]
        unit_heads = [
            (person, position) for person, position in zip(people, holds)
            if position.kind == Position.HEAD and position.office_id in unit_ids
        ]
        for (person, _), position in zip(unit_heads[::7], vacant_positions[: len(vacant_positions) // 3]):
            assignments.append(PositionAssignment(
                user=person, position=position, starts_on=start, is_acting=True,
            ))
        self._create(PositionAssignment, assignments)

        # Who is told what: people holding a post at each office.
        self.holders = {}
        self.head_of = {}
        self.encoder_of = {}
        position_by_id = {p.pk: p for p in positions}
        for a in assignments:
            position = position_by_id[a.position_id]
            self.holders.setdefault(position.office_id, []).append(a.user_id)
            if position.kind == Position.HEAD:
                self.head_of[position.office_id] = (a.user_id, position.pk)
            elif position.kind == Position.ENCODER:
                self.encoder_of[position.office_id] = (a.user_id, position.pk)
        self.office_name = {
            o.pk: o.name for o in
            [self.president, *self.vps, *self.directorates, self.qms, *self.units]
        }

    def _series_and_manuals(self):
        per_vp = 5 if len(self.vps) == 6 else 1
        series, links, concurring_by_series, readers_by_series = [], [], {}, {}
        for v, vp in enumerate(self.vps):
            pool = self.units_by_vp.get(vp.pk, [])
            for s in range(per_vp):
                code = f'S{v + 1}{s + 1:02d}'
                series.append(ManualSeries(
                    code=code, title=f'Synthetic Manual Series {code}',
                    owning_office=vp,
                ))
        series = self._create(ManualSeries, series)

        for item in series:
            pool = list(self.units_by_vp.get(item.owning_office_id, []))
            self.rng.shuffle(pool)
            concurring, readers = pool[:min(8, len(pool))], pool[8:12]
            concurring_by_series[item.pk] = [o.pk for o in concurring]
            readers_by_series[item.pk] = [o.pk for o in readers]
            links += [ManualSeriesOffice(series=item, office=o,
                                         relationship=OfficeLink.CONCURRING)
                      for o in concurring]
            links += [ManualSeriesOffice(series=item, office=o,
                                         relationship=OfficeLink.READER)
                      for o in readers]
        self._create(ManualSeriesOffice, links)

        manuals = []
        for m in range(self.n['manuals']):
            item = series[m % len(series)]
            manuals.append(Manual(
                title=f'{item.code} {m // len(series) + 1}.{m % 97:02d} - Synthetic document {m + 1:05d}',
                series=item, file='mastercopies/synthetic.pdf',
                offices_overridden=(m % 20 == 19),
            ))
        manuals = self._create(Manual, manuals)

        overrides = []
        self.concurring_of = {}
        for manual in manuals:
            offices = concurring_by_series[manual.series_id]
            if manual.offices_overridden:
                offices = offices[:max(1, len(offices) // 2)]
                overrides += [ManualOffice(manual=manual, office_id=o,
                                           relationship=OfficeLink.CONCURRING)
                              for o in offices]
                overrides += [ManualOffice(manual=manual, office_id=o,
                                           relationship=OfficeLink.READER)
                              for o in readers_by_series[manual.series_id][:2]]
            self.concurring_of[manual.pk] = offices
        self._create(ManualOffice, overrides)

        sections = [
            ManualSection(
                manual=manual, subtitle=f'{n + 1}.0 Synthetic section',
                content=(f'Synthetic text for section {n + 1} of document '
                         f'{manual.pk}. The office shall keep records of each '
                         f'transaction and report monthly.'),
                tag='PROCEDURE', order=n,
            )
            for manual in manuals for n in range(SECTIONS_PER_MANUAL)
        ]
        sections = self._create(ManualSection, sections)
        self.sections_of = {}
        for section in sections:
            self.sections_of.setdefault(section.manual_id, []).append(section)
        self.manuals = manuals
        self.series_owner = {s.pk: s.owning_office_id for s in series}

    # -- proposals ---------------------------------------------------

    def _statuses(self, mix, total):
        plan = []
        for status, share in mix:
            plan += [status] * round(total * share)
        while len(plan) < total:
            plan.append(mix[0][0])
        return plan[:total]

    def _proposals(self):
        rng = self.rng
        manuals = self.manuals
        plan = []

        # Open work: a manual takes at most one open proposal per office,
        # and each holds its own sections. Two passes over the manuals use
        # different offices and different sections.
        for i, status in enumerate(self._statuses(OPEN_MIX, self.n['open'])):
            manual = manuals[i % len(manuals)]
            lap = i // len(manuals)
            offices = self.concurring_of[manual.pk]
            sections = self.sections_of[manual.pk]
            if lap >= len(offices) or 2 * lap + 1 >= len(sections):
                continue
            plan.append((manual, offices[lap], status,
                         sections[2 * lap: 2 * lap + 1 + (i % 2)]))

        for status in self._statuses(CLOSED_MIX, self.n['closed']):
            manual = rng.choice(manuals)
            offices = self.concurring_of[manual.pk]
            plan.append((manual, rng.choice(offices), status,
                         self.sections_of[manual.pk][:1 + rng.randrange(2)]))

        proposals, rows = [], []
        for number, (manual, office, status, sections) in enumerate(plan, 1):
            created = self.now - timedelta(days=rng.randint(1, 240),
                                           minutes=rng.randint(0, 1440))
            proposal = Proposal(
                manual=manual, initiating_office_id=office, status=status,
                created_by_id=self._actor(office), created_at=created,
                updated_at=created,
            )
            if status in Proposal.FROZEN_STATUSES or status in (Proposal.EFFECTIVE, Proposal.DENIED):
                proposal.dcr_number = f'SCALE-{number:06d}'
            proposals.append(proposal)
            rows.append((proposal, sections))
        proposals = self._create(Proposal, proposals)

        versions, participants, concurrences, events, changes = [], [], [], [], []
        per_proposal = []
        for proposal, sections in rows:
            story = self._story(proposal)
            per_proposal.append((proposal, sections, story))
            for number, version_story in enumerate(story['versions'], 1):
                versions.append(ProposalVersion(
                    proposal=proposal, number=number,
                    overall_reason='Synthetic reason: align the procedure with current practice.',
                    created_at=version_story['created'],
                    submitted_at=version_story.get('submitted'),
                    submitted_by_id=(self._head(proposal.initiating_office_id)
                                     if version_story.get('submitted') else None),
                ))
        versions = self._create(ProposalVersion, versions)
        version_of = {(v.proposal_id, v.number): v for v in versions}

        for proposal, sections, story in per_proposal:
            last = len(story['versions'])
            if story['submitted']:
                concurring = [o for o in self.concurring_of[proposal.manual_id]
                              if o != proposal.initiating_office_id]
                for office in concurring:
                    participants.append(ProposalParticipant(
                        proposal=proposal, office_id=office,
                        office_name_at_time=self.office_name[office],
                        role=ProposalParticipant.CONCURRING,
                    ))
                owner = self.series_owner[proposal.manual.series_id]
                for order, office in enumerate((owner, self.president.pk), 1):
                    participants.append(ProposalParticipant(
                        proposal=proposal, office_id=office,
                        office_name_at_time=self.office_name[office],
                        role=ProposalParticipant.APPROVING, route_order=order,
                    ))
                story['concurring'] = concurring

            for number, version_story in enumerate(story['versions'], 1):
                version = version_of[(proposal.pk, number)]
                for kind, at, office, detail in version_story['events']:
                    events.append(AuditEvent(
                        proposal=proposal, version=version, event=kind,
                        actor_id=self._actor(office), office_id=office,
                        position_id=self._position(office),
                        office_name_at_time=self.office_name[office],
                        detail=detail, at=at,
                    ))
                for office, decision, at in version_story['decisions']:
                    concurrences.append(Concurrence(
                        version=version, office_id=office, decision=decision,
                        feedback=('Synthetic feedback: section 2 needs the '
                                  'reporting period.' if decision == Concurrence.RETURN else ''),
                        recorded_by_id=self._actor(office),
                        recorded_by_position_id=self._position(office),
                        recorded_at=at,
                    ))
                for section in sections:
                    changes.append(SectionChange(
                        version=version, section=section,
                        old_text=section.content,
                        new_text=section.content.replace('monthly', 'quarterly'),
                    ))
            proposal.updated_at = story['last_at']
            if story.get('locked'):
                proposal.locked_at = story['locked']
            if proposal.status == Proposal.WITHDRAWN:
                proposal.withdrawn_at = story['last_at']
                proposal.withdrawn_by_id = self._head(proposal.initiating_office_id)
                proposal.withdrawn_reason = 'Synthetic: superseded by another request.'

        Proposal.objects.bulk_update(
            proposals, ['updated_at', 'locked_at', 'withdrawn_at',
                        'withdrawn_by', 'withdrawn_reason'], batch_size=CHUNK,
        )
        self._create(ProposalParticipant, participants)
        self._create(Concurrence, concurrences)
        self.stdout.write(f'  writing {len(changes)} section changes...')
        self._create(SectionChange, changes)
        events = self._create(AuditEvent, events)
        self._notifications(events, {p.pk: (p, story) for p, _, story in per_proposal})

    def _story(self, proposal):
        """What happened to one proposal, version by version, ending in its
        status. Times move forward from its creation."""
        rng = self.rng
        office = proposal.initiating_office_id
        at = proposal.created_at
        concurring = [o for o in self.concurring_of[proposal.manual_id] if o != office]
        status = proposal.status

        def later(low=1, high=6):
            nonlocal at
            at = min(at + timedelta(days=rng.randint(low, high),
                                    minutes=rng.randint(0, 600)), self.now)
            return at

        versions = [{'created': at, 'events': [(AuditEvent.CREATED, at, office, '')],
                     'decisions': []}]
        returned_once = rng.random() < 0.25
        submitted = status != Proposal.DRAFT or returned_once
        withdrawn_early = status == Proposal.WITHDRAWN and rng.random() < 0.5
        if withdrawn_early:
            submitted = False

        if submitted:
            versions[0]['submitted'] = later()
            versions[0]['events'].append((AuditEvent.SUBMITTED, at, office, ''))
            if returned_once and concurring:
                returner = rng.choice(concurring)
                versions[0]['decisions'].append((returner, Concurrence.RETURN, later()))
                versions[0]['events'].append((AuditEvent.RETURNED, at, returner,
                                              'Synthetic feedback.'))
                versions.append({'created': at, 'events': [(AuditEvent.REDRAFTED, at, office, '')],
                                 'decisions': []})
                if status != Proposal.DRAFT:
                    versions[-1]['submitted'] = later()
                    versions[-1]['events'].append((AuditEvent.SUBMITTED, at, office, ''))

        current = versions[-1]
        locked = None
        if status == Proposal.CONCURRENCE:
            for other in concurring:
                if rng.random() < 0.5:
                    current['decisions'].append((other, Concurrence.CONCUR, later(0, 4)))
                    current['events'].append((AuditEvent.CONCURRED, at, other, ''))
        elif submitted and status != Proposal.WITHDRAWN:
            for other in concurring:
                current['decisions'].append((other, Concurrence.CONCUR, later(0, 3)))
                current['events'].append((AuditEvent.CONCURRED, at, other, ''))
            locked = later(0, 1)
            current['events'].append((AuditEvent.LOCKED, at, office, ''))
            if status != Proposal.LOCKED:
                current['events'].append((AuditEvent.DOCUMENTS_GENERATED, at, office, ''))
            qms = self.qms.pk
            steps = {
                Proposal.READY_FOR_IMR: [(AuditEvent.PACKAGE_COMPLETE, office)],
                Proposal.AWAITING_APPROVAL: [(AuditEvent.PACKAGE_COMPLETE, office),
                                             (AuditEvent.IMR_ACCEPTED, qms)],
                Proposal.WITH_CUSTODIAN: [(AuditEvent.PACKAGE_COMPLETE, office),
                                          (AuditEvent.IMR_ACCEPTED, qms),
                                          (AuditEvent.APPROVAL_UPLOADED, qms)],
                Proposal.PACKAGE_RETURNED: [(AuditEvent.PACKAGE_COMPLETE, office),
                                            (AuditEvent.IMR_ACCEPTED, qms),
                                            (AuditEvent.APPROVAL_UPLOADED, qms),
                                            (AuditEvent.PACKAGE_RETURNED, qms)],
                Proposal.DENIED: [(AuditEvent.PACKAGE_COMPLETE, office),
                                  (AuditEvent.IMR_DENIED, qms)],
                Proposal.EFFECTIVE: [(AuditEvent.PACKAGE_COMPLETE, office),
                                     (AuditEvent.IMR_ACCEPTED, qms),
                                     (AuditEvent.APPROVAL_UPLOADED, qms),
                                     (AuditEvent.MADE_EFFECTIVE, qms)],
            }.get(status, [])
            for kind, who in steps:
                current['events'].append((kind, later(1, 10), who, ''))
        if status == Proposal.WITHDRAWN:
            current['events'].append((AuditEvent.WITHDRAWN, later(), office,
                                       'Synthetic: superseded by another request.'))
        return {'versions': versions, 'submitted': submitted,
                'locked': locked, 'last_at': at}

    def _notifications(self, events, proposals):
        """The inbox entries `notifications.notify` would have written for
        these events: concurring offices on submission, the initiating
        office on a decision or the lock."""
        rows = []
        for event in events:
            proposal, story = proposals[event.proposal_id]
            if event.event == AuditEvent.SUBMITTED:
                offices = story.get('concurring', [])
            elif event.event in (AuditEvent.CONCURRED, AuditEvent.RETURNED, AuditEvent.LOCKED):
                offices = [proposal.initiating_office_id]
            else:
                continue
            seen = set()
            for office in offices:
                for user in self.holders.get(office, []):
                    if user == event.actor_id or user in seen:
                        continue
                    seen.add(user)
                    age = (self.now - event.at).days
                    rows.append(Notification(
                        user_id=user, event=event, created_at=event.at,
                        read_at=(event.at + timedelta(hours=6)
                                 if age > 14 or self.rng.random() < 0.5 else None),
                    ))
        self._create(Notification, rows)

    # -- who acts ---------------------------------------------------

    def _head(self, office):
        held = self.head_of.get(office)
        return held[0] if held else None

    def _actor(self, office):
        """Head, else Encoder, else any holder: an office with a vacant Head
        still has someone to record its act."""
        for table in (self.head_of, self.encoder_of):
            if office in table:
                return table[office][0]
        return self.holders[office][0]

    def _position(self, office):
        for table in (self.head_of, self.encoder_of):
            if office in table:
                return table[office][1]
        return None
