"""Indexes for the admin's Proposals list: filter by status, sort by last
activity. Indexes only - no data changes."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0040_user_requested_office_name'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='proposal',
            index=models.Index(fields=['status'], name='proposal_status_idx'),
        ),
        migrations.AddIndex(
            model_name='proposal',
            index=models.Index(fields=['updated_at'], name='proposal_updated_at_idx'),
        ),
    ]
