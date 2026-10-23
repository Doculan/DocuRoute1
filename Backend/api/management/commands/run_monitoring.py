"""Time-based monitoring: stalls and vacancies (deadlines join in Phase 3).

    py manage.py run_monitoring
    py manage.py run_monitoring --only stalls

Safe to run every few minutes and twice at once: a second run finds the
lock held and exits quietly, and no notice is ever sent twice. Scheduling
is described in DEPLOYMENT.md ("QMS CDMS monitoring").
"""

from django.core.management.base import BaseCommand, CommandError

from api import monitoring


class Command(BaseCommand):
    help = 'Flag stalled proposals and vacant posts, and notify whoever must act.'

    def add_arguments(self, parser):
        parser.add_argument('--only', choices=monitoring.STEPS, action='append',
                            help='run only this step (repeatable)')

    def handle(self, *args, **options):
        counts = monitoring.run(only=options['only'])
        if counts is None:
            self.stdout.write('Another run holds the lock; nothing to do.')
            return
        if not counts:
            raise CommandError('No step ran.')
        self.stdout.write(' · '.join(f'{name.replace("_", " ")} {n}'
                                     for name, n in counts.items()))
