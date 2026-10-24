"""Phase 3A: announcements reshaped, and deadlines.

Announcements: `date` becomes `expires_on` (an item that was "Upcoming"
until its day is an announcement that expires on it); `audience` says
explicitly whether it is for everyone or for chosen offices, and a
targeted one gets an `AnnouncementOffice` row before `office` is dropped.
The three live rows were all for everyone: they stay so, rows 1-2 already
expired and row 3 still the banner. No deadline is created from them.

Deadlines: types (the spec's eleven presets, §6.2), deadlines, what the
admin targeted, and the obligations they materialise into.
"""


import api.models
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


PRESETS = [
    # (name, basis, confirm with the QMS office)
    ('ISO 9001 surveillance audit', 'Surveillance audits across the certification cycle', False),
    ('ISO 9001 recertification', 'At the end of the certification cycle', False),
    ('PRIME-HRM assessment (Civil Service Commission)', 'Level I/II maturity assessments', False),
    ('AACCUP program accreditation / institutional accreditation survey', 'Accreditation surveys', False),
    ('CHED SUC Leveling submission', 'SUC Leveling', False),
    ('CHED Institutional Sustainability Assessment (ISA)', 'Institutional Sustainability Assessment', False),
    ('COA audit recommendations follow-up', 'SUC performance reporting', False),
    ('Internal quality audit', 'Standard ISO practice', True),
    ('Management review', 'Standard ISO practice', True),
    ('Periodic document review', 'Internal: documents reviewed on a cycle', False),
    ("Citizen's Charter update (ARTA)", 'General knowledge', True),
]


def forwards(apps, schema_editor):
    DeadlineType = apps.get_model('api', 'DeadlineType')
    Announcement = apps.get_model('api', 'Announcement')
    AnnouncementOffice = apps.get_model('api', 'AnnouncementOffice')
    for name, basis, confirm in PRESETS:
        DeadlineType.objects.get_or_create(name=name, defaults={
            'basis': basis, 'is_preset': True, 'confirm_with_qms': confirm})
    for announcement in Announcement.objects.all():
        if announcement.office_id is None:
            announcement.audience = 'all'
        else:
            announcement.audience = 'offices'
            AnnouncementOffice.objects.get_or_create(
                announcement=announcement, office_id=announcement.office_id)
        announcement.save(update_fields=['audience'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0045_encoder_to_head_step'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='announcement',
            options={'ordering': ['-created_at']},
        ),
        # The old date becomes the expiry: an item that was "Upcoming" until
        # its day passed is an announcement that expires on that day.
        migrations.RenameField('announcement', 'date', 'expires_on'),
        migrations.AddField(
            model_name='announcement',
            name='audience',
            field=models.CharField(choices=[('all', 'Everyone'), ('offices', 'Selected offices')], default='all', max_length=8),
        ),
        migrations.AddField(
            model_name='announcement',
            name='deactivated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='announcement',
            name='deactivated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='announcement',
            name='active',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='notification',
            name='kind',
            field=models.CharField(choices=[('deadline_set', 'Deadline set for your office'), ('sent_to_head', 'Sent to the Head'), ('returned_to_encoder', 'Returned to the Encoder'), ('recalled', 'Recalled by the Encoder'), ('concurrence_requested', 'Concurrence requested'), ('returned_by_office', 'Returned by an office'), ('concurred', 'An office concurred'), ('locked', 'Locked; documents ready to sign'), ('ready_for_imr', 'Ready for the IMR'), ('imr_accepted', 'Accepted by the IMR'), ('imr_denied', 'Denied by the IMR'), ('approval_uploaded', 'Signed DCR uploaded'), ('package_returned', 'Package returned by the custodian'), ('package_resubmitted', 'Package back with the custodian'), ('made_effective', 'Made effective'), ('withdrawn', 'Withdrawn'), ('stalled', 'Stalled'), ('position_vacant', 'Position vacant')], max_length=40),
        ),
        migrations.AlterField(
            model_name='notification',
            name='target_type',
            field=models.CharField(blank=True, choices=[('proposal', 'Proposal'), ('manual', 'Manual'), ('office', 'Office'), ('people', 'People'), ('deadline', 'Deadline')], max_length=16),
        ),
        migrations.AlterField(
            model_name='systemevent',
            name='kind',
            field=models.CharField(choices=[('deadline_set', 'Deadline set'), ('deadline_changed', 'Deadline changed'), ('obligation_met', 'Deadline obligation met'), ('obligation_reopened', 'Deadline obligation reopened'), ('log_started', 'Log started'), ('notified', 'Notified'), ('notification_read', 'Notification read'), ('notification_acted', 'Notification acted on'), ('stalled', 'Stalled past its stage threshold'), ('position_vacant', 'Position has no current holder'), ('email_sent', 'Email sent')], max_length=40),
        ),
        migrations.CreateModel(
            name='DeadlineType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, unique=True)),
                ('basis', models.CharField(blank=True, max_length=255)),
                ('is_preset', models.BooleanField(default=False)),
                ('confirm_with_qms', models.BooleanField(default=False)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-is_preset', 'name'],
            },
        ),
        migrations.CreateModel(
            name='Deadline',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('due_on', models.DateField()),
                ('note', models.TextField(blank=True)),
                ('reminder_days', models.JSONField(default=api.models.default_reminder_days)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('obligations_total', models.PositiveIntegerField(default=0)),
                ('obligations_open', models.PositiveIntegerField(default=0)),
                ('obligations_met', models.PositiveIntegerField(default=0)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='deadlines_created', to=settings.AUTH_USER_MODEL)),
                ('type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='deadlines', to='api.deadlinetype')),
            ],
            options={
                'ordering': ['due_on', 'pk'],
            },
        ),
        migrations.CreateModel(
            name='AnnouncementOffice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('include_descendants', models.BooleanField(default=False)),
                ('announcement', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='targets', to='api.announcement')),
                ('office', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='api.office')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('announcement', 'office'), name='one_target_per_announcement_and_office')],
            },
        ),
        migrations.CreateModel(
            name='DeadlineObligation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('priority', models.BooleanField(default=False)),
                ('state', models.CharField(choices=[('open', 'Not yet met'), ('submitted', 'Submitted'), ('reviewed', 'Reviewed, no change'), ('effective', 'Made effective')], default='open', max_length=10)),
                ('office_met_at', models.DateTimeField(blank=True, null=True)),
                ('effective_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('deadline', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='obligations', to='api.deadline')),
                ('manual', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='obligations', to='api.manual')),
                ('met_by_proposal', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='obligations_met', to='api.proposal')),
                ('office', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='obligations', to='api.office')),
            ],
            options={
                'ordering': ['deadline', 'office', 'manual'],
                'indexes': [models.Index(fields=['office', 'state'], name='obligation_office_state_idx'), models.Index(fields=['manual', 'state'], name='obligation_manual_state_idx'), models.Index(fields=['deadline', 'state'], name='obligation_deadline_state_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('manual__isnull', True)), fields=('deadline', 'office'), name='one_office_obligation_per_deadline'), models.UniqueConstraint(condition=models.Q(('manual__isnull', False)), fields=('deadline', 'office', 'manual'), name='one_manual_obligation_per_deadline')],
            },
        ),
        migrations.CreateModel(
            name='DeadlineTarget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('all', 'All offices'), ('office', 'Office'), ('series', 'Manual series'), ('manual', 'Manual')], max_length=8)),
                ('include_descendants', models.BooleanField(default=False)),
                ('deadline', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='targets', to='api.deadline')),
                ('manual', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='api.manual')),
                ('office', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='api.office')),
                ('series', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='api.manualseries')),
            ],
            options={
                'constraints': [models.CheckConstraint(condition=models.Q(models.Q(('kind', 'all'), ('manual__isnull', True), ('office__isnull', True), ('series__isnull', True)), models.Q(('kind', 'office'), ('manual__isnull', True), ('office__isnull', False), ('series__isnull', True)), models.Q(('kind', 'series'), ('manual__isnull', True), ('office__isnull', True), ('series__isnull', False)), models.Q(('kind', 'manual'), ('manual__isnull', False), ('office__isnull', True), ('series__isnull', True)), _connector='OR'), name='deadline_target_matches_its_kind')],
            },
        ),
        migrations.AddIndex(
            model_name='deadline',
            index=models.Index(fields=['active', 'due_on'], name='deadline_active_due_idx'),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        # Only once every targeted announcement has its office row.
        migrations.RemoveField(
            model_name='announcement',
            name='office',
        ),
    ]
