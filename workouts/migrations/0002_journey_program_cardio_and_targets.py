# Generated manually because the project does not vendor a Python environment.
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('workouts', '0001_initial'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='routineexercise', name='focus', field=models.CharField(blank=True, default='', max_length=80)),
        migrations.AddField(model_name='routineexercise', name='suggested_weight_kg', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='routineexercise', name='target_rpe', field=models.FloatField(blank=True, null=True)),
        migrations.CreateModel(name='JourneyProgram', fields=[
            ('id', models.UUIDField(primary_key=True, serialize=False, editable=False, default=uuid.uuid4)),
            ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)),
            ('name', models.CharField(default='60-Day Fitness Journey', max_length=150)), ('start_date', models.DateField()),
            ('duration_days', models.PositiveSmallIntegerField(default=60)), ('current_day', models.PositiveSmallIntegerField(default=1)),
            ('active', models.BooleanField(default=True)), ('target_cardio_minutes_early', models.PositiveSmallIntegerField(default=120)),
            ('target_cardio_minutes_later', models.PositiveSmallIntegerField(default=150)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='journey_programs', to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name='CardioEntry', fields=[
            ('id', models.UUIDField(primary_key=True, serialize=False, editable=False, default=uuid.uuid4)),
            ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)), ('date', models.DateField()),
            ('modality', models.CharField(choices=[('TREADMILL','Treadmill'),('CYCLING','Cycling'),('CROSS_TRAINER','Cross Trainer'),('ELLIPTICAL','Elliptical'),('ROWING','Rowing'),('OTHER','Other')], max_length=20)),
            ('duration_minutes', models.PositiveSmallIntegerField()), ('intensity', models.CharField(default='Zone 2', max_length=40)),
            ('heart_rate', models.PositiveSmallIntegerField(blank=True, null=True)), ('target_zone', models.CharField(blank=True, default='', max_length=40)),
            ('completed', models.BooleanField(default=True)), ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cardio_entries', to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name='ProgramDay', fields=[
            ('id', models.UUIDField(primary_key=True, serialize=False, editable=False, default=uuid.uuid4)),
            ('created_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)), ('day_number', models.PositiveSmallIntegerField()),
            ('label', models.CharField(blank=True, default='', max_length=60)), ('is_optional', models.BooleanField(default=False)),
            ('status', models.CharField(choices=[('UPCOMING','Upcoming'),('COMPLETED','Completed'),('MISSED','Missed')], default='UPCOMING', max_length=12)),
            ('completed_session', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='program_day_completion', to='workouts.workoutsession')),
            ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='days', to='workouts.journeyprogram')),
            ('routine', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='program_days', to='workouts.routine')),
        ], options={'ordering':['day_number']}),
        migrations.AddConstraint(model_name='journeyprogram', constraint=models.UniqueConstraint(condition=models.Q(active=True), fields=('user',), name='one_active_journey_per_user')),
        migrations.AddConstraint(model_name='programday', constraint=models.UniqueConstraint(fields=('program','day_number'), name='unique_program_day')),
        migrations.AddIndex(model_name='programday', index=models.Index(fields=['program','status'], name='workouts_pr_program_ba0af0_idx')),
    ]
