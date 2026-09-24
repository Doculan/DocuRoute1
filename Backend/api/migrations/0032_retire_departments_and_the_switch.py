"""v4.1.0: departments and the access switch are retired.

Access is by position, permanently: the switch that chose between that and
v3's one-department rule is gone, and so are departments - on documents,
people and announcements. Offices, positions and office links carry all of
it.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0031_retire_single_section_revisions'),
    ]

    operations = [
        migrations.RemoveField(model_name='manual', name='department'),
        migrations.RemoveField(model_name='customuser', name='department'),
        migrations.RemoveField(model_name='announcement', name='department'),
        migrations.DeleteModel(name='AccessMode'),
        migrations.DeleteModel(name='Department'),
    ]
