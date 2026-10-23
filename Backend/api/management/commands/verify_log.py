"""Check the system activity log's hash chain.

    py manage.py verify_log system

Recomputes every row's hash in order and names the first row that does
not follow from the one before it - edited, deleted or inserted out of
order. Exits with an error when the chain is broken.
"""

from django.core.management.base import BaseCommand, CommandError

from api import system_log


class Command(BaseCommand):
    help = 'Verify the hash chain of the system activity log.'

    def add_arguments(self, parser):
        parser.add_argument('log', choices=['system'])

    def handle(self, *args, **options):
        checked, problem = system_log.verify()
        if problem:
            raise CommandError(f'Chain broken after {checked} row(s): {problem}.')
        self.stdout.write(self.style.SUCCESS(f'Chain intact: {checked} row(s).'))
