"""The office name typed by an applicant whose office is not listed.

Blank for every existing account: none of them typed one.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0039_demorecord_source'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='requested_office_name',
            field=models.CharField(blank=True, max_length=60),
        ),
    ]
