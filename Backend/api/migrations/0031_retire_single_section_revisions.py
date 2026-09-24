"""v4.1.0: the v3 single-section revision flow is removed.

It existed for the switched-off state. Proposals replaced it; nothing in
the process reads a `ManualRevision` any more. Section history keeps its
proposal link; its `revision` link and the 'revision' and 'merge' sources
go with the flows that wrote them.

**Refuses to run while any v3 revision exists**, or any history row still
points at one - removing the table would destroy a record somebody made,
and that must be a decision, not a side effect of upgrading.
"""

from django.db import migrations, models


def refuse_if_revisions_exist(apps, schema_editor):
    ManualRevision = apps.get_model('api', 'ManualRevision')
    SectionHistory = apps.get_model('api', 'SectionHistory')
    revisions = ManualRevision.objects.count()
    linked = SectionHistory.objects.filter(revision__isnull=False).count()
    old_sources = SectionHistory.objects.filter(source__in=('revision', 'merge')).count()
    if revisions or linked or old_sources:
        raise RuntimeError(
            f'Not removing the v3 revision flow: {revisions} revision(s), '
            f'{linked} history row(s) linked to one and {old_sources} history '
            f'row(s) from a revision or a merge still exist. Export or '
            f'resolve them first.'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0030_baseline_corrections'),
    ]

    operations = [
        migrations.RunPython(refuse_if_revisions_exist, migrations.RunPython.noop),
        migrations.RemoveField(model_name='manualrevision', name='reviewed_by'),
        migrations.RemoveField(model_name='manualrevision', name='section'),
        migrations.RemoveField(model_name='manualrevision', name='submitted_by'),
        migrations.RemoveField(model_name='revisionpreassessment', name='consumed_by'),
        migrations.RemoveField(model_name='sectionhistory', name='revision'),
        migrations.AlterField(
            model_name='sectionhistory',
            name='change_reason',
            field=models.TextField(blank=True, help_text="Why this change was made. Carried over from the request's reason when it is made effective, typed by the admin on a direct edit."),
        ),
        migrations.AlterField(
            model_name='sectionhistory',
            name='source',
            field=models.CharField(choices=[('proposal', 'Change request made effective'), ('direct', 'Direct edit by an admin'), ('extraction', 'Re-extracted from the master copy'), ('unknown', 'Recorded before edits were attributed')], default='unknown', max_length=20),
        ),
        migrations.DeleteModel(name='ManualRevision'),
    ]
