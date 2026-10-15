from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('plans', '0003_fix_bro_split_dips_reference')]

    operations = [
        migrations.AddField(model_name='trainingsplit', name='experience_levels', field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name='trainingsplit', name='compatible_goals', field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name='trainingsplit', name='rest_days', field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name='trainingsplit', name='muscle_groups', field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name='trainingsplit', name='equipment_requirements', field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name='trainingsplit', name='estimated_session_minutes', field=models.PositiveSmallIntegerField(default=60)),
        migrations.AddField(model_name='trainingsplit', name='weekly_volume', field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='trainingsplit', name='progression_strategy', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='trainingsplit', name='recovery_rules', field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name='trainingsplit', name='approval_status', field=models.CharField(choices=[('DRAFT', 'Draft'), ('APPROVED', 'Approved'), ('INACTIVE', 'Inactive')], default='DRAFT', max_length=20)),
        migrations.AddField(model_name='trainingsplit', name='catalog_version', field=models.CharField(default='1.0', max_length=20)),
    ]
