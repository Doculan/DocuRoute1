"""Phase 2B: the Encoder-to-Head step.

A new status, `with_head`, counts as open: the one-open-proposal-per-office
constraint now includes it, so a draft with the Head still holds its
office's slot. New audit events (sent to the Head, recalled, returned to
the Encoder) and their notification kinds. Choices only otherwise - no
data changes. On SQLite the constraint change rebuilds api_proposal.
"""


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0044_notification_constraints'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='proposal',
            name='one_open_proposal_per_office_and_document',
        ),
        migrations.AlterField(
            model_name='auditevent',
            name='event',
            field=models.CharField(choices=[('created', 'Created'), ('sent_to_head', 'Sent to the Head'), ('recalled', 'Recalled by the Encoder'), ('returned_to_encoder', 'Returned to the Encoder'), ('submitted', 'Submitted for concurrence'), ('concurred', 'Concurred'), ('returned', 'Returned with feedback'), ('redrafted', 'Redrafted'), ('locked', 'Locked'), ('documents_generated', 'Documents generated'), ('scan_uploaded', 'Signed copy uploaded'), ('scan_replaced', 'Signed copy replaced'), ('package_complete', 'Signed copies complete'), ('imr_accepted', 'Accepted by the IMR'), ('imr_denied', 'Denied by the IMR'), ('approval_uploaded', 'Approving authority signed'), ('package_returned', 'Returned for package defects'), ('made_effective', 'Made effective'), ('withdrawn', 'Withdrawn')], max_length=32),
        ),
        migrations.AlterField(
            model_name='notification',
            name='kind',
            field=models.CharField(choices=[('sent_to_head', 'Sent to the Head'), ('returned_to_encoder', 'Returned to the Encoder'), ('recalled', 'Recalled by the Encoder'), ('concurrence_requested', 'Concurrence requested'), ('returned_by_office', 'Returned by an office'), ('concurred', 'An office concurred'), ('locked', 'Locked; documents ready to sign'), ('ready_for_imr', 'Ready for the IMR'), ('imr_accepted', 'Accepted by the IMR'), ('imr_denied', 'Denied by the IMR'), ('approval_uploaded', 'Signed DCR uploaded'), ('package_returned', 'Package returned by the custodian'), ('package_resubmitted', 'Package back with the custodian'), ('made_effective', 'Made effective'), ('withdrawn', 'Withdrawn'), ('stalled', 'Stalled'), ('position_vacant', 'Position vacant')], max_length=40),
        ),
        migrations.AlterField(
            model_name='proposal',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('with_head', 'With the Head'), ('concurrence', 'Out for concurrence'), ('locked', 'Locked'), ('awaiting_signature', 'Awaiting signature'), ('ready_for_imr', 'Ready for the IMR'), ('denied', 'Denied by the IMR'), ('awaiting_approval', 'Awaiting the approving authority'), ('with_custodian', 'With the Document Custodian'), ('package_returned', 'Returned for package defects'), ('effective', 'Effective'), ('withdrawn', 'Withdrawn')], default='draft', max_length=32),
        ),
        migrations.AddConstraint(
            model_name='proposal',
            constraint=models.UniqueConstraint(condition=models.Q(('status__in', ['draft', 'with_head', 'concurrence'])), fields=('manual', 'initiating_office'), name='one_open_proposal_per_office_and_document'),
        ),
    ]
