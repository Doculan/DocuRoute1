"""Which seeder wrote each `DemoRecord`.

Existing rows were all written by `seed_demo_org`, which is what the
default says - so they keep meaning exactly what they meant.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0038_user_requested_position_kind'),
    ]

    operations = [
        migrations.AddField(
            model_name='demorecord',
            name='source',
            field=models.CharField(
                choices=[('demo_org', 'seed_demo_org'), ('scale', 'seed_scale')],
                db_index=True, default='demo_org', max_length=16,
            ),
        ),
    ]
