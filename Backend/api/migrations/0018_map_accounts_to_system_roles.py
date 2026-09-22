"""Give every existing account a v4 system role.

Derived from the v3 `role` field rather than from a list of usernames, so
this produces the same result on a teammate's checkout, a fresh clone
rebuilt from the master copies, or the demo machine.

No offices are created and no departments are read. The organisation
starts genuinely empty - that decision is not quietly undone here.

Nobody becomes QMS staff. Nobody can: QMS staff is defined by holding a
current IMR or Custodian position, positions belong to offices, and there
are no offices yet. That is why the review screen keeps a transitional
allowance for the system admin until phase 1c - see
`IsQmsReviewer` in views.py.
"""

from django.db import migrations


def set_system_roles(apps, schema_editor):
    CustomUser = apps.get_model('api', 'CustomUser')

    CustomUser.objects.filter(role='admin').update(system_role='system_admin')
    # Everything that is not an admin is an ordinary user, including
    # accounts still awaiting approval - approval and role are separate
    # gates, and an unapproved account still has to be *something*.
    CustomUser.objects.exclude(role='admin').update(system_role='user')


def unset_system_roles(apps, schema_editor):
    # The field's own default. Reversing this migration does not restore
    # "no value" - there was never one - it restores the default the
    # column was created with.
    CustomUser = apps.get_model('api', 'CustomUser')
    CustomUser.objects.update(system_role='user')


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0017_organisation_tables'),
    ]

    operations = [
        migrations.RunPython(set_system_roles, unset_system_roles),
    ]
