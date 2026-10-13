"""
Bug fix (spec v1.6 section 6.7 audit, FITLOG_EXERCISE_AUDIT_v1.md section 6):
TrainingSplit 'bro-split' day_1 (its Chest day) lists an exercise named
exactly 'Dips', which does not match any Exercise.name in the catalog --
the catalog only has 'Dips (Chest Focus)' (chest, bodyweight) and
'Tricep Dips' (triceps, bodyweight). Since day_1 is the split's dedicated
Chest session (bench press / incline press / cable fly / this entry), the
chest-focused variant is clearly the intended exercise -- 'Tricep Dips'
would put a triceps-primary movement on a day that otherwise trains
nothing but chest, which doesn't match the split's own per-muscle-per-day
design (bro-split's muscle groups are one-per-day: chest, back, legs,
shoulders, arms).

This migration patches the row(s) already persisted by
plans/management/commands/seed_training_splits.py in the live/dev database
(that command uses get_or_create and will never update an existing row's
content on re-run); the command's own source is also corrected separately
so a fresh seed from scratch produces the right content without needing
this migration's help.
"""
from django.db import migrations

OLD_NAME = 'Dips'
NEW_NAME = 'Dips (Chest Focus)'


def fix_dips_reference(apps, schema_editor):
    TrainingSplit = apps.get_model('plans', 'TrainingSplit')
    split = TrainingSplit.objects.filter(slug='bro-split').first()
    if split is None:
        return
    templates = split.workout_templates or {}
    day_1 = templates.get('day_1') or []
    changed = False
    for entry in day_1:
        if entry.get('exercise_name') == OLD_NAME:
            entry['exercise_name'] = NEW_NAME
            changed = True
    if changed:
        split.workout_templates = templates
        split.save(update_fields=['workout_templates'])


def reverse(apps, schema_editor):
    TrainingSplit = apps.get_model('plans', 'TrainingSplit')
    split = TrainingSplit.objects.filter(slug='bro-split').first()
    if split is None:
        return
    templates = split.workout_templates or {}
    day_1 = templates.get('day_1') or []
    changed = False
    for entry in day_1:
        if entry.get('exercise_name') == NEW_NAME:
            entry['exercise_name'] = OLD_NAME
            changed = True
    if changed:
        split.workout_templates = templates
        split.save(update_fields=['workout_templates'])


class Migration(migrations.Migration):

    dependencies = [
        ('plans', '0002_trainingsplit_blueprint_default_training_split'),
    ]

    operations = [
        migrations.RunPython(fix_dips_reference, reverse),
    ]
