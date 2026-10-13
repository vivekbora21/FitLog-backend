"""
Data migration for the spec v1.6 section 6.7 exercise-library audit
(see /home/vivek/Desktop/Project/FITLOG_EXERCISE_AUDIT_v1.md) and the
product-owner decisions that followed it.

Implemented here (a migration, not a management command, so it is applied
automatically -- including on a freshly-migrated test database -- the same
way the rest of the schema is, instead of depending on someone remembering
to re-run a seed command):

1. Catalog gap-fill (additive only): adds bodyweight/resistance-band
   exercises for Calves, Biceps and Hamstrings so the "need >= 2 distinct
   exercises per muscle group at every equipment level" gate (spec 6.7)
   passes for home and minimal equipment on every split this pass approves.
   One exercise beyond the strict minimum of 2 is added for each group
   (-> 3 at minimal/home, except Hamstrings/Calves already had 1 so they
   land at 4) so the "no exercise twice in a session" rule has real slack,
   not a bare scrape to 2.

2. Bug fix -- duplicate catalog entry: two global Exercise rows were both
   named "Chest-Supported Dumbbell Row" (slugs chest-supported-dumbbell-row
   and chest-supported-db-row). Confirmed live (2026-10-12) that
   chest-supported-db-row has real FK references (2 RoutineExercise rows +
   2 WorkoutExercise rows from core/management/commands/seed_vivek_journey.py's
   demo journey data) and chest-supported-dumbbell-row has zero references
   anywhere (checked every FK pointing at Exercise: ExerciseSubstitute,
   RoutineExercise, WorkoutExercise, JourneyProgram.focus_exercise,
   ProgramDayExerciseSwap.replacement_exercise, PersonalRecord). So
   chest-supported-dumbbell-row is the one removed; chest-supported-db-row
   is left untouched (it must stay -- deleting it would cascade/orphan the
   demo journey's logged sets).

3. Bug fix -- Upper/Lower trains "Back" 3x/week instead of 2x: Conventional
   Deadlift (primary_muscle=Back) sits on Upper/Lower's day_2 (Lower) in
   addition to being the kind of exercise that already appears via other
   Back movements on both Upper days (day_1, day_4). A deadlift belonging
   on a Lower day is normal and is NOT being removed from that template;
   the fix is reclassifying Conventional Deadlift's own primary_muscle from
   Back to Hamstrings, which is a legitimate, common classification for a
   conventional-stance pull (it is a hip-hinge, posterior-chain/hamstring-
   dominant movement, not a vertical/horizontal pulling movement the way
   rows and pulldowns are) and matches how it is actually being used here:
   as the compound lift opening a leg day. This also does not newly break
   Bro Split's or PPL's own "N picks of Back in one session" need --- it
   only *reduces* those same-session Back counts (one fewer exercise
   tagged Back in those sessions), and both splits' Back pool has wide
   margin either way.
"""
from django.db import migrations


MUSCLE_GROUPS_NEEDED = [
    ('Calves', 'calves'),
    ('Biceps', 'biceps'),
    ('Hamstrings', 'hamstrings'),
]

EQUIPMENT_NEEDED = [
    ('Bodyweight', 'bodyweight'),
    ('Dumbbell', 'dumbbell'),
    ('Resistance Band', 'resistance-band'),
]

# (name, slug, muscle_slug, equipment_slug, instructions, met_value)
NEW_EXERCISES = [
    # --- Calves: home had 1 (Single-Leg Calf Raise, bodyweight), minimal
    # had the same 1 -- both fail the >=2 gate. ---
    (
        'Bodyweight Standing Calf Raise',
        'bodyweight-standing-calf-raise',
        'calves', 'bodyweight',
        'Stand on a flat floor or step edge, feet hip-width. Rise onto the balls '
        'of both feet, pause, then lower under control for a full stretch.',
        3.5,
    ),
    (
        'Resistance Band Standing Calf Raise',
        'resistance-band-standing-calf-raise',
        'calves', 'resistance-band',
        'Loop a band under the balls of both feet, holding the ends at your sides '
        'or anchored to a low point. Rise onto toes against band tension, lower slowly.',
        3.5,
    ),
    (
        'Dumbbell Standing Calf Raise',
        'dumbbell-standing-calf-raise',
        'calves', 'dumbbell',
        'Hold a dumbbell in each hand at your sides, balls of feet on a raised edge '
        'if available. Rise onto toes, pause, lower for a deep stretch.',
        4.0,
    ),

    # --- Biceps: home already had 7 (passes); minimal had 0. ---
    (
        'Resistance Band Bicep Curl',
        'resistance-band-bicep-curl',
        'biceps', 'resistance-band',
        'Stand on the middle of the band, one handle in each hand, palms facing '
        'forward. Curl hands to shoulders against band tension, lower with control.',
        3.0,
    ),
    (
        'Resistance Band Hammer Curl',
        'resistance-band-hammer-curl',
        'biceps', 'resistance-band',
        'Stand on the band with a neutral (palms-in) grip on each handle. Curl '
        'straight up keeping wrists neutral throughout, targeting brachialis.',
        3.0,
    ),
    (
        'Resistance Band Concentration Curl',
        'resistance-band-concentration-curl',
        'biceps', 'resistance-band',
        'Sit, anchor the band under one foot, brace the working elbow against the '
        'inner thigh. Curl the handle up with strict form, no body English.',
        3.0,
    ),

    # --- Hamstrings: home already had 4 (passes); minimal had 1 (Nordic
    # Hamstring Curl, bodyweight). ---
    (
        'Bodyweight Single-Leg Deadlift',
        'bodyweight-single-leg-deadlift',
        'hamstrings', 'bodyweight',
        'Stand on one leg, hinge at the hips while extending the free leg straight '
        'back for balance, lowering torso toward parallel. Drive hips forward to return.',
        3.5,
    ),
    (
        'Resistance Band Romanian Deadlift',
        'resistance-band-romanian-deadlift',
        'hamstrings', 'resistance-band',
        'Stand on the middle of the band, feet hip-width, holding a handle in each '
        'hand. Hinge at the hips keeping knees soft, lower until a hamstring stretch '
        'is felt, then drive hips forward to stand.',
        3.5,
    ),
    (
        'Resistance Band Lying Leg Curl',
        'resistance-band-lying-leg-curl',
        'hamstrings', 'resistance-band',
        'Lie face-down with the band anchored in front of you and looped around one '
        'ankle. Curl the heel toward the glute against band tension, control the return.',
        3.5,
    ),
]

# Exercise slugs to delete as the duplicate-entry fix. Left as a list (not a
# single constant) in case a future audit finds more of the same pattern.
DUPLICATE_SLUGS_TO_REMOVE = ['chest-supported-dumbbell-row']

RECLASSIFY_PRIMARY_MUSCLE = [
    # (exercise_slug, new_muscle_slug, new_muscle_name)
    ('conventional-deadlift', 'hamstrings', 'Hamstrings'),
]


def _get_or_create_muscle(MuscleGroup, name, slug):
    obj, _ = MuscleGroup.objects.get_or_create(slug=slug, defaults={'name': name})
    return obj


def _get_or_create_equipment(EquipmentType, name, slug):
    obj, _ = EquipmentType.objects.get_or_create(slug=slug, defaults={'name': name})
    return obj


def add_gap_fill_exercises_and_fix_bugs(apps, schema_editor):
    Exercise = apps.get_model('exercises', 'Exercise')
    MuscleGroup = apps.get_model('exercises', 'MuscleGroup')
    EquipmentType = apps.get_model('exercises', 'EquipmentType')

    muscles = {
        slug: _get_or_create_muscle(MuscleGroup, name, slug)
        for name, slug in MUSCLE_GROUPS_NEEDED
    }
    equipment = {
        slug: _get_or_create_equipment(EquipmentType, name, slug)
        for name, slug in EQUIPMENT_NEEDED
    }

    # --- Bug fix 2: duplicate catalog entry -----------------------------
    for slug in DUPLICATE_SLUGS_TO_REMOVE:
        qs = Exercise.objects.filter(slug=slug, gym__isnull=True)
        exercise = qs.first()
        if exercise is None:
            continue
        referenced = False
        for related in exercise._meta.related_objects:
            accessor = related.get_accessor_name() if related.one_to_many or related.one_to_one else related.field.name
            try:
                if related.one_to_many or related.one_to_one:
                    referenced = referenced or getattr(exercise, accessor).exists()
                else:
                    # m2m/other reverse relations -- be conservative.
                    referenced = referenced or getattr(exercise, accessor).exists()
            except Exception:
                # Never let an unexpected reverse-relation shape block the
                # rest of the migration; default to NOT deleting if unsure.
                referenced = True
        if not referenced:
            exercise.delete()
        # If referenced, intentionally leave it in place -- see module
        # docstring point 2. (Live-DB check already confirmed this specific
        # slug has zero references before this migration was written.)

    # --- Bug fix 3: Conventional Deadlift primary_muscle reclassification
    for exercise_slug, muscle_slug, muscle_name in RECLASSIFY_PRIMARY_MUSCLE:
        muscle = muscles.get(muscle_slug) or _get_or_create_muscle(MuscleGroup, muscle_name, muscle_slug)
        Exercise.objects.filter(slug=exercise_slug, gym__isnull=True).update(primary_muscle=muscle)

    # --- A: catalog gap-fill (additive) ---------------------------------
    for name, slug, muscle_slug, equip_slug, instructions, met_value in NEW_EXERCISES:
        Exercise.objects.get_or_create(
            slug=slug,
            gym=None,
            defaults={
                'name': name,
                'primary_muscle': muscles[muscle_slug],
                'equipment': equipment[equip_slug],
                'instructions': instructions,
                'met_value': met_value,
            },
        )


def reverse(apps, schema_editor):
    Exercise = apps.get_model('exercises', 'Exercise')
    MuscleGroup = apps.get_model('exercises', 'MuscleGroup')
    EquipmentType = apps.get_model('exercises', 'EquipmentType')

    # Undo A: remove the newly added exercises.
    Exercise.objects.filter(
        slug__in=[row[1] for row in NEW_EXERCISES], gym__isnull=True
    ).delete()

    # Undo bug fix 3: restore Conventional Deadlift's classification.
    back, _ = MuscleGroup.objects.get_or_create(slug='back', defaults={'name': 'Back'})
    Exercise.objects.filter(slug='conventional-deadlift', gym__isnull=True).update(primary_muscle=back)

    # Undo bug fix 2 (best-effort -- recreates the row, with a new id, if
    # it's still absent and still has zero live references under the old
    # slug; this is a data migration, so a perfect reverse isn't possible
    # once the original row's id has been reused by anything else).
    if not Exercise.objects.filter(slug='chest-supported-dumbbell-row').exists():
        dumbbell, _ = EquipmentType.objects.get_or_create(slug='dumbbell', defaults={'name': 'Dumbbell'})
        Exercise.objects.get_or_create(
            slug='chest-supported-dumbbell-row',
            gym=None,
            defaults={
                'name': 'Chest-Supported Dumbbell Row',
                'primary_muscle': back,
                'equipment': dumbbell,
                'instructions': (
                    'Lie face-down on incline bench. Row both dumbbells simultaneously. '
                    'Eliminates lower-back involvement for pure lat/rhomboid work.'
                ),
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('exercises', '0004_exercise_substitutes_and_secondary_equipment'),
    ]

    operations = [
        migrations.RunPython(add_gap_fill_exercises_and_fix_bugs, reverse),
    ]
