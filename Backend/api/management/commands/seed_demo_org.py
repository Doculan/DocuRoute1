"""A fictional organisation, for showing the system to other people.

    py manage.py seed_demo_org
    py manage.py seed_demo_org --clear

**Demonstration data. Every person in it is invented.** The names below
are fictional and the structure is a simplified sketch - the real
organisation is entered through the Organisation screens, office by
office, by the system admin.

Three things make it safe to run and safe to undo.

**It refuses if a real organisation exists.** Any office the seeder did
not create means somebody has started entering the real one, and seeding
fictional offices beside it would mix the two beyond telling apart.

**It records what it did, row by row**, in `DemoRecord` - creations and
the previous values of anything it modified. `--clear` walks that
backwards. "Delete everything that looks like demo data" is not exact: a
real office can share a name with a fictional one.

**It is not a migration and never will be.** A migration runs on every
machine that deploys, including the one holding the university's real
data.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import (
    CustomUser, DemoRecord, Manual, ManualSeries, ManualSeriesOffice, Office,
    OfficeLink, Position, PositionAssignment,
)

DEMO_PASSWORD = 'Office123!'

# (name, abbreviation, parent abbreviation, is_approving_level)
OFFICES = [
    ('Office of the President', 'OP', None, True),

    ('Office of the VP for Administration and Finance', 'VPAF', 'OP', True),
    ('Office of the CAO for Administration', 'CAO-A', 'VPAF', False),
    ('Human Resource Management Office', 'HRMO', 'CAO-A', False),
    ('Quality Management System Office', 'QMS', 'CAO-A', False),
    ('Office of the CAO for Finance', 'CAO-F', 'VPAF', False),
    ('Accounting Office', 'ACC', 'CAO-F', False),
    ('Budget Office', 'BUD', 'CAO-F', False),
    ('Cash Management Office', 'CMO', 'CAO-F', False),

    ('Office of the VP for Student Development', 'VPSD', 'OP', True),
    ('Guidance Office', 'GUI', 'VPSD', False),
    ('Scholarship and Financial Assistance Office', 'SFA', 'VPSD', False),

    ('Office of the VP for Academic Services', 'VPAS', 'OP', True),
    ('Curriculum Development Office', 'CDO', 'VPAS', False),
]

# (code, title, owner, [concurring abbreviations])
#
# SDM and ASM have their owner among the concurring offices - the VP's own
# staff draft changes to the manual the VP signs. Allowed, and the reason
# the approval route has to continue above the owner.
SERIES = [
    ('FAM', 'Finance and Administration Manual', 'VPAF', ['ACC', 'BUD', 'CMO']),
    ('HRM', 'Human Resource Manual', 'VPAF', ['HRMO']),
    ('SDM', 'Student Development Manual', 'VPSD', ['GUI', 'SFA', 'VPSD']),
    ('ASM', 'Academic Services Manual', 'VPAS', ['CDO', 'VPAS']),
]

# (username, full name, office, position)
PEOPLE = [
    ('QMS_Ana', 'Ana Reyes', 'QMS', Position.IMR),
    ('QMS_Pedro', 'Pedro Cruz', 'QMS', Position.DOCUMENT_CUSTODIAN),
    ('ACC_Maria', 'Maria Santos', 'ACC', Position.HEAD),
    ('ACC_Juan', 'Juan Dela Cruz', 'ACC', Position.ENCODER),
    ('BUD_Jose', 'Jose Ramos', 'BUD', Position.HEAD),
    ('BUD_Rosa', 'Rosa Lim', 'BUD', Position.ENCODER),
    ('CMO_Carlo', 'Carlo Bautista', 'CMO', Position.HEAD),
    ('HRM_Liza', 'Liza Mendoza', 'HRMO', Position.HEAD),
    ('HRM_Mateo', 'Mateo Garcia', 'HRMO', Position.ENCODER),
    ('GUI_Nena', 'Nena Flores', 'GUI', Position.HEAD),
    ('SFA_Paolo', 'Paolo Villanueva', 'SFA', Position.HEAD),
    ('CDO_Elena', 'Elena Torres', 'CDO', Position.HEAD),
    ('VPSD_Ramon', 'Ramon Aquino', 'VPSD', Position.HEAD),
    ('VPAS_Teresa', 'Teresa Navarro', 'VPAS', Position.HEAD),
]


class Command(BaseCommand):
    help = 'Seed a fictional organisation for demonstrations. Not for a server.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear', action='store_true',
            help='remove exactly what this command created, and stop',
        )

    # -- bookkeeping ----------------------------------------------

    def _record(self, obj, previous=None):
        self._sequence += 1
        DemoRecord.objects.create(
            label=f'{obj._meta.app_label}.{obj._meta.object_name}',
            object_id=str(obj.pk),
            kind=DemoRecord.CHANGED if previous else DemoRecord.CREATED,
            previous=previous or {},
            sequence=self._sequence,
        )
        return obj

    # -- clearing --------------------------------------------------

    def _clear(self):
        from django.apps import apps

        records = list(DemoRecord.objects.order_by('-sequence'))
        if not records:
            self.stdout.write('Nothing to clear - no demo data recorded.')
            return

        restored = removed = 0
        with transaction.atomic():
            for record in records:
                model = apps.get_model(record.label)
                obj = model.objects.filter(pk=record.object_id).first()
                if obj is None:
                    continue
                if record.kind == DemoRecord.CHANGED:
                    # Put the field back the way it was rather than to a
                    # default - the row existed before and has to end up
                    # as it started.
                    for field, value in record.previous.items():
                        setattr(obj, field, value)
                    obj.save(update_fields=list(record.previous))
                    restored += 1
                else:
                    obj.delete()
                    removed += 1
            DemoRecord.objects.all().delete()

        self.stdout.write(self.style.SUCCESS(
            f'Removed {removed} demo row(s), restored {restored} changed row(s).'
        ))
        self.stdout.write(
            f'  offices {Office.objects.count()}, '
            f'series {ManualSeries.objects.count()}, '
            f'people {CustomUser.objects.count()}'
        )

    # -- seeding ---------------------------------------------------

    def handle(self, *args, **options):
        self._sequence = DemoRecord.objects.count()

        if options['clear']:
            self._clear()
            return

        def seeded(label):
            return set(
                DemoRecord.objects.filter(
                    label=label, kind=DemoRecord.CREATED,
                ).values_list('object_id', flat=True)
            )

        seeded_ids = seeded('api.Office')

        # Series as well as offices. A real series carrying one of these
        # codes collides on the unique constraint, and the command failed
        # with a raw database error instead of saying what was wrong -
        # which is how this half of the check came to exist.
        for model, label, what in (
            (Office, 'api.Office', 'office'),
            (ManualSeries, 'api.ManualSeries', 'manual series'),
        ):
            real = model.objects.exclude(pk__in=seeded(label))
            if real.exists():
                names = ", ".join(str(o) for o in real[:5])
                self.stderr.write(
                    f'Refusing to seed: {real.count()} {what}(s) exist that '
                    f'this command did not create ({names}).\n'
                    f'Somebody has started entering the real organisation, '
                    f'and fictional data beside it could not be told apart '
                    f'afterwards. Run --clear first if those are leftovers.'
                )
                return

        if seeded_ids:
            self.stdout.write(
                'Demo data is already seeded. Run --clear to start over.'
            )
            return

        today = timezone.localdate()

        with transaction.atomic():
            offices = {}
            for name, abbr, parent, approving in OFFICES:
                office = Office.objects.create(
                    name=name, abbreviation=abbr,
                    parent=offices.get(parent), is_approving_level=approving,
                )
                offices[abbr] = self._record(office)
            self.stdout.write(f'  {len(offices)} offices')

            series_by_code = {}
            for code, title, owner, concurring in SERIES:
                series = ManualSeries.objects.create(
                    code=code, title=title, owning_office=offices[owner],
                )
                series_by_code[code] = self._record(series)
                for abbr in concurring:
                    link = ManualSeriesOffice.objects.create(
                        series=series, office=offices[abbr],
                        relationship=OfficeLink.CONCURRING,
                    )
                    self._record(link)
            self.stdout.write(f'  {len(series_by_code)} series')

            placed = skipped = 0
            for manual in Manual.objects.all().order_by('title'):
                code = (manual.title or '').split(' ')[0]
                series = series_by_code.get(code)
                if series is None:
                    skipped += 1
                    continue
                # A change, not a creation: the document existed. Its
                # previous values are recorded so --clear restores them.
                self._record(manual, previous={'series_id': manual.series_id})
                manual.series = series
                manual.save(update_fields=['series'])
                placed += 1
            self.stdout.write(
                f'  {placed} documents placed'
                + (f', {skipped} skipped (no series for their prefix)'
                   if skipped else '')
            )

            for username, full_name, abbr, kind in PEOPLE:
                person = CustomUser.objects.create_user(
                    username=username, password=DEMO_PASSWORD,
                    full_name=full_name, is_approved=True,
                    system_role=(
                        CustomUser.QMS_STAFF
                        if kind in Position.QMS_KINDS else CustomUser.USER
                    ),
                )
                self._record(person)

                position = Position.objects.filter(
                    office=offices[abbr], kind=kind,
                ).first()
                if position is None:
                    position = self._record(Position.objects.create(
                        office=offices[abbr], kind=kind,
                    ))
                self._record(PositionAssignment.objects.create(
                    user=person, position=position, starts_on=today,
                ))
            self.stdout.write(f'  {len(PEOPLE)} people, all approved')

        self.stdout.write(self.style.SUCCESS(
            f'\nDemonstration organisation seeded. Every person in it is '
            f'fictional.'
        ))
        self.stdout.write(f'  Password for all demo accounts: {DEMO_PASSWORD}')
        self.stdout.write(
            '\nThe access switch is untouched. Check readiness on the '
            'Switchover screen, then flip it there.'
        )
        self.stdout.write('\nTo remove exactly this data:\n'
                          '    py manage.py seed_demo_org --clear')
