from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0037_user_requested_office')]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='requested_position_kind',
            field=models.CharField(
                choices=[('encoder', 'Encoder'), ('head', 'Head')],
                default='encoder', max_length=32,
            ),
        ),
    ]
