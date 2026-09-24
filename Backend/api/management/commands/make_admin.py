"""Promote a user to the application's admin role.

`createsuperuser` gives Django-admin access, which is not the same thing:
this project's screens check `role == 'admin'` and `is_approved`, both of
which a fresh superuser lacks. Without this the first account can reach
/admin/ and nothing else, which looks like a broken login rather than a
missing flag.

    py manage.py make_admin <username>
"""

from django.core.management.base import BaseCommand

from api.models import CustomUser


class Command(BaseCommand):
    help = "Give an existing user the admin role and mark them approved."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **options):
        try:
            user = CustomUser.objects.get(username=options["username"])
        except CustomUser.DoesNotExist:
            names = ", ".join(
                CustomUser.objects.values_list("username", flat=True)[:10]
            ) or "(none)"
            self.stderr.write(
                f"no user called {options['username']!r}. Existing users: {names}"
            )
            return

        user.role = "admin"
        user.system_role = CustomUser.SYSTEM_ADMIN
        user.is_approved = True
        user.save(update_fields=["role", "system_role", "is_approved"])
        self.stdout.write(self.style.SUCCESS(
            f"{user.username} is now an approved system admin"
        ))
