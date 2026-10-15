from datetime import timedelta

from django.db import migrations, models


def backfill_plan_dates(apps, schema_editor):
    JourneyProgram = apps.get_model('workouts', 'JourneyProgram')
    ProgramDay = apps.get_model('workouts', 'ProgramDay')
    for program in JourneyProgram.objects.all():
        original_end = program.start_date + timedelta(days=program.duration_days - 1)
        JourneyProgram.objects.filter(pk=program.pk).update(
            original_end_date=original_end,
            effective_end_date=original_end,
        )
        for day in ProgramDay.objects.filter(program_id=program.pk):
            ProgramDay.objects.filter(pk=day.pk).update(
                scheduled_date=program.start_date + timedelta(days=day.day_number - 1)
            )


class Migration(migrations.Migration):
    dependencies = [('workouts', '0014_cardioentry_calories')]

    operations = [
        migrations.AddField('journeyprogram', 'original_end_date', models.DateField(blank=True, null=True)),
        migrations.AddField('journeyprogram', 'effective_end_date', models.DateField(blank=True, null=True)),
        migrations.AddField('journeyprogram', 'plan_status', models.CharField(choices=[('ACTIVE', 'Active'), ('COMPLETED', 'Completed')], default='ACTIVE', max_length=12)),
        migrations.AddField('journeyprogram', 'extension_status', models.CharField(choices=[('NONE', 'None'), ('DECLINED', 'Declined'), ('ACCEPTED', 'Accepted')], default='NONE', max_length=12)),
        migrations.AddField('journeyprogram', 'extension_days', models.PositiveSmallIntegerField(default=0)),
        migrations.AddField('programday', 'scheduled_date', models.DateField(blank=True, null=True)),
        migrations.RunPython(backfill_plan_dates, migrations.RunPython.noop),
    ]
