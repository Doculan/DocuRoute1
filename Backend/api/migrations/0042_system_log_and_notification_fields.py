"""Phase 2A, schema only: the system activity log, the monitoring job's
tables, and the new notification fields beside the old ones.

Every new notification field is nullable or has a placeholder default, so
the existing rows stay valid until 0043 fills them and 0044 drops what
they replace. Nothing is removed here.
"""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0041_proposal_status_updated_at_indexes'),
    ]

    operations = [
        migrations.CreateModel(
            name='SystemEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('seq', models.PositiveBigIntegerField(unique=True)),
                ('kind', models.CharField(choices=[
                    ('log_started', 'Log started'), ('notified', 'Notified'),
                    ('notification_read', 'Notification read'),
                    ('notification_acted', 'Notification acted on'),
                    ('stalled', 'Stalled past its stage threshold'),
                    ('position_vacant', 'Position has no current holder'),
                    ('email_sent', 'Email sent')], max_length=40)),
                ('actor_label', models.CharField(max_length=255)),
                ('office_name_at_time', models.CharField(blank=True, max_length=255)),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('at', models.DateTimeField()),
                ('prev_hash', models.CharField(max_length=64)),
                ('hash', models.CharField(max_length=64, unique=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='system_events', to=settings.AUTH_USER_MODEL)),
                ('manual', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='api.manual')),
                ('office', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='api.office')),
                ('position', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='api.position')),
                ('proposal', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='system_events', to='api.proposal')),
            ],
            options={
                'ordering': ['seq'],
                'constraints': [models.CheckConstraint(
                    condition=models.Q(
                        models.Q(('actor__isnull', True), ('actor_label', 'system')),
                        models.Q(('actor__isnull', False),
                                 models.Q(('actor_label', 'system'), _negated=True)),
                        _connector='OR'),
                    name='system_event_actor_or_system_label')],
            },
        ),
        migrations.CreateModel(
            name='LogHead',
            fields=[
                ('log', models.CharField(max_length=16, primary_key=True, serialize=False)),
                ('seq', models.PositiveBigIntegerField(default=0)),
                ('hash', models.CharField(max_length=64)),
            ],
        ),
        migrations.CreateModel(
            name='JobLock',
            fields=[
                ('name', models.CharField(max_length=40, primary_key=True, serialize=False)),
                ('holder', models.CharField(blank=True, max_length=80)),
                ('acquired_at', models.DateTimeField(blank=True, null=True)),
                ('expires_at', models.DateTimeField()),
            ],
        ),
        migrations.CreateModel(
            name='JobRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trigger', models.CharField(default='scheduled', max_length=16)),
                ('started_at', models.DateTimeField()),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('counts', models.JSONField(blank=True, default=dict)),
                ('error', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['-started_at'],
                'indexes': [models.Index(fields=['finished_at'], name='jobrun_finished_idx')],
            },
        ),
        migrations.CreateModel(
            name='MonitoringSetting',
            fields=[
                ('stage', models.CharField(max_length=32, primary_key=True, serialize=False)),
                ('days', models.PositiveIntegerField()),
            ],
        ),
        migrations.AddIndex(
            model_name='auditevent',
            index=models.Index(fields=['proposal', 'at'], name='auditevent_proposal_at_idx'),
        ),

        # The new notification fields, beside the old `user` and `event`.
        migrations.AddField('notification', 'addressed_office', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            related_name='+', to='api.office')),
        migrations.AddField('notification', 'addressed_office_name',
                            models.CharField(blank=True, max_length=255)),
        migrations.AddField('notification', 'addressed_position', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name='+', to='api.position')),
        migrations.AddField('notification', 'addressed_position_title',
                            models.CharField(blank=True, max_length=255)),
        migrations.AddField('notification', 'kind',
                            models.CharField(default='', max_length=40), preserve_default=False),
        migrations.AddField('notification', 'severity',
                            models.CharField(default='', max_length=8), preserve_default=False),
        migrations.AddField('notification', 'title',
                            models.CharField(default='', max_length=120), preserve_default=False),
        migrations.AddField('notification', 'body', models.CharField(blank=True, max_length=300)),
        migrations.AddField('notification', 'target_type', models.CharField(
            blank=True, max_length=16, choices=[
                ('proposal', 'Proposal'), ('manual', 'Manual'),
                ('office', 'Office'), ('people', 'People')])),
        migrations.AddField('notification', 'target_id',
                            models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField('notification', 'office_level', models.BooleanField(default=False)),
        migrations.AddField('notification', 'manual', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            related_name='+', to='api.manual')),
        migrations.AddField('notification', 'manual_title',
                            models.CharField(blank=True, max_length=255)),
        migrations.AddField('notification', 'proposal', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            related_name='notifications', to='api.proposal')),
        migrations.AddField('notification', 'audit_event', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            related_name='+', to='api.auditevent')),
        migrations.AddField('notification', 'system_event', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            related_name='notifications', to='api.systemevent')),
        migrations.AddField('notification', 'dedupe_key',
                            models.CharField(default='', max_length=200), preserve_default=False),
        migrations.AddField('notification', 'acted_at',
                            models.DateTimeField(blank=True, null=True)),
        migrations.AddField('notification', 'acted_by', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name='+', to=settings.AUTH_USER_MODEL)),
        migrations.AlterField('notification', 'created_at',
                              models.DateTimeField(default=django.utils.timezone.now)),
    ]
