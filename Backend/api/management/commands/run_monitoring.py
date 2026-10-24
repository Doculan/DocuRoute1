"""Time-based monitoring: stalls, vacancies, the deadline ladder and the
optional periodic review.

    py manage.py run_monitoring
    py manage.py run_monitoring --only stalls
    py manage.py run_monitoring --dry-run
    py manage.py run_monitoring --dry-run --as-of 2026-12-01

Safe to run every few minutes and twice at once: a second run finds the
lock held and exits quietly, and no notice is ever sent twice. Scheduling
is described in DEPLOYMENT.md ("QMS CDMS monitoring").

**--dry-run** lists what a run would send - each deadline notice's step,
deadline, office and recipients, and the stalls and vacancies it would
flag - and writes nothing. **--as-of YYYY-MM-DD** acts as if it were that
day. With --dry-run it always works. Without it, it sends real notices
dated that day, so it is refused unless `QMS_ALLOW_AS_OF` is set: an
overdue escalation must never go out by accident on live data
(DEMO_CHECKLIST.md).
"""

from datetime import date, datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api import monitoring


class Command(BaseCommand):
    help = 'Flag stalled proposals and vacant posts, send deadline reminders and escalations.'

    def add_arguments(self, parser):
        parser.add_argument('--only', choices=monitoring.STEPS, action='append',
                            help='run only this step (repeatable)')
        parser.add_argument('--dry-run', action='store_true',
                            help='list what would be sent; write nothing')
        parser.add_argument('--as-of', metavar='YYYY-MM-DD',
                            help='act as if it were this day (demo databases; see --help)')

    def handle(self, *args, **options):
        now = None
        if options['as_of']:
            try:
                day = date.fromisoformat(options['as_of'])
            except ValueError:
                raise CommandError('--as-of takes a date as YYYY-MM-DD.')
            if not options['dry_run'] and not settings.MONITORING_ALLOW_AS_OF:
                raise CommandError(
                    'Refused: --as-of without --dry-run sends real notices dated that day. '
                    'It is for demo databases only; set QMS_ALLOW_AS_OF=1 there. '
                    'To see what would be sent, add --dry-run.')
            now = timezone.make_aware(datetime.combine(day, timezone.localtime().time()))

        if options['dry_run']:
            plan = monitoring.dry_run(now)
            when = f'as of {options["as_of"]}' if options['as_of'] else 'now'
            self.stdout.write(f'Dry run, {when}. Nothing is written.')
            for line in plan['deadlines']:
                self.stdout.write(f'  {line}')
            self.stdout.write(f'{len(plan["deadlines"])} deadline notices, '
                              f'{plan["stalls"]} stalls, {plan["vacancies"]} vacancies would be flagged')
            return

        counts = monitoring.run(only=options['only'], now=now)
        if counts is None:
            self.stdout.write('Another run holds the lock; nothing to do.')
            return
        if not counts:
            raise CommandError('No step ran.')
        self.stdout.write(' · '.join(f'{name.replace("_", " ")} {n}'
                                     for name, n in counts.items()))
