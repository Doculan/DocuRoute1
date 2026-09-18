"""Label the assessments that already exist for what they are.

Every revision predating the pre-submission check either carries a result a
reviewer produced by pressing an assess button, or none at all. Neither is
something the submitter read, and `ai_source` defaults to 'none', so without
this the older rows would claim the submitter saw an assessment they never
saw. Reversible: the reverse pass only puts the default back.
"""

from django.db import migrations


def label_existing_assessments(apps, schema_editor):
    ManualRevision = apps.get_model('api', 'ManualRevision')
    ManualRevision.objects.exclude(ai_verdict='').update(ai_source='admin_legacy')
    ManualRevision.objects.filter(ai_verdict='').update(ai_source='none')


def unlabel(apps, schema_editor):
    ManualRevision = apps.get_model('api', 'ManualRevision')
    ManualRevision.objects.update(ai_source='none')


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0012_manualrevision_ai_advisories_and_more'),
    ]

    operations = [
        migrations.RunPython(label_existing_assessments, unlabel),
    ]
