"""Create one approved staff account per department, for testing.

Registering through the UI leaves an account unapproved, so a fresh clone
has nobody who can actually submit a revision until an admin approves them -
which means the first thing anyone does on a new machine is a chore. These
accounts exist so the staff side can be opened immediately.

    py manage.py seed_test_users
    py manage.py seed_test_users --password mypassword

Test credentials only. They are printed to the console on purpose, and are
not something to create on a server.
"""

from django.core.management.base import BaseCommand

from api.models import CustomUser, Department

DEFAULT_PASSWORD = "staff12345"


class Command(BaseCommand):
    help = "Create an approved staff account for each department."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password", default=DEFAULT_PASSWORD,
            help=f"password for every created account (default {DEFAULT_PASSWORD})",
        )
        parser.add_argument(
            "--reset", action="store_true",
            help="reset the password on accounts that already exist",
        )

    def handle(self, *args, **options):
        departments = list(Department.objects.order_by("name"))
        if not departments:
            self.stderr.write(
                "no departments exist yet - run import_mastercopies first, "
                "which creates them from the master copy filenames."
            )
            return

        password = options["password"]
        self.stdout.write(f"{len(departments)} department(s)\n")

        for department in departments:
            username = f"staff.{department.name.lower()}"
            user, created = CustomUser.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.test",
                    "role": "staff",
                    "is_approved": True,
                    "department": department,
                },
            )
            if created or options["reset"]:
                user.set_password(password)
                # An account that exists but is unapproved is the same
                # problem as no account at all, so fix both together.
                user.is_approved = True
                user.department = department
                user.role = "staff"
                user.save()

            state = "created" if created else (
                "reset" if options["reset"] else "exists"
            )
            self.stdout.write(f"  {state:<8} {username:<18} {department.name}")

        self.stdout.write(self.style.SUCCESS(
            f"\nSign in with any of the above. Password: {password}"
        ))
        self.stdout.write(
            "Test credentials only - do not create these on a server."
        )
