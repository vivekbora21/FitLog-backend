from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nutrition', '0005_targets_lifestyle_and_history'),
    ]

    operations = [
        migrations.AddField(
            model_name='macrotarget',
            name='weekly_calories_burned',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='targethistory',
            name='weekly_calories_burned',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
