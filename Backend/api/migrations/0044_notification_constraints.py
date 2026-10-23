"""Phase 2A, finish: the notification as it now is.

`user` becomes `recipient`; `event` and its unique (user, event) give way
to `audit_event` and the unique (recipient, dedupe_key); the checks that
every notice has exactly one cause, names its manual unless it is about an
office, and is only "acted on" when it asked for action; and the indexes
the bell, the page and the resolvers read.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0043_start_system_log_and_backfill_notifications'),
    ]

    operations = [
        migrations.RemoveConstraint('notification', 'one_notification_per_user_per_event'),
        migrations.RemoveIndex('notification', 'api_notific_user_id_85c543_idx'),
        migrations.RemoveField('notification', 'event'),
        migrations.RenameField('notification', 'user', 'recipient'),
        migrations.AlterField('notification', 'audit_event', models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
            related_name='notifications', to='api.auditevent')),
        migrations.AlterField('notification', 'kind', models.CharField(max_length=40, choices=[
            ('concurrence_requested', 'Concurrence requested'),
            ('returned_by_office', 'Returned by an office'),
            ('concurred', 'An office concurred'),
            ('locked', 'Locked; documents ready to sign'),
            ('ready_for_imr', 'Ready for the IMR'),
            ('imr_accepted', 'Accepted by the IMR'),
            ('imr_denied', 'Denied by the IMR'),
            ('approval_uploaded', 'Signed DCR uploaded'),
            ('package_returned', 'Package returned by the custodian'),
            ('package_resubmitted', 'Package back with the custodian'),
            ('made_effective', 'Made effective'),
            ('withdrawn', 'Withdrawn'),
            ('stalled', 'Stalled'),
            ('position_vacant', 'Position vacant')])),
        migrations.AlterField('notification', 'severity', models.CharField(
            max_length=8, choices=[('action', 'Action required'), ('info', 'Info')])),
        migrations.AlterField('notification', 'title', models.CharField(max_length=120)),
        migrations.AlterField('notification', 'dedupe_key', models.CharField(max_length=200)),
        migrations.AddConstraint('notification', models.CheckConstraint(
            condition=(models.Q(('audit_event__isnull', False), ('system_event__isnull', True))
                       | models.Q(('audit_event__isnull', True), ('system_event__isnull', False))),
            name='notification_has_exactly_one_cause')),
        migrations.AddConstraint('notification', models.UniqueConstraint(
            fields=('recipient', 'dedupe_key'), name='one_notification_per_recipient_and_key')),
        migrations.AddConstraint('notification', models.CheckConstraint(
            condition=models.Q(('severity', 'action')) | models.Q(('acted_at__isnull', True)),
            name='only_action_notifications_are_acted_on')),
        migrations.AddConstraint('notification', models.CheckConstraint(
            condition=models.Q(('office_level', True)) | models.Q(('manual__isnull', False)),
            name='notification_names_its_manual')),
        migrations.AddIndex('notification', models.Index(
            fields=['recipient', 'read_at'], name='notif_recipient_read_idx')),
        migrations.AddIndex('notification', models.Index(
            fields=['recipient', 'severity', 'acted_at'], name='notif_recipient_open_idx')),
        migrations.AddIndex('notification', models.Index(
            fields=['recipient', 'created_at'], name='notif_recipient_time_idx')),
        migrations.AddIndex('notification', models.Index(
            fields=['proposal', 'kind', 'acted_at'], name='notif_resolver_idx')),
    ]
