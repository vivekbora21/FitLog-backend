import importlib

from django.apps import apps as global_apps
from django.test import TestCase

# Create your tests here.


from rest_framework.test import APIClient
from users.models import User
from .models import Exercise, MuscleGroup, EquipmentType


class CustomExerciseTests(TestCase):
    def setUp(self):
        self.muscle = MuscleGroup.objects.create(name='Back', slug='back')
        self.equipment = EquipmentType.objects.create(name='Cable', slug='cable')
        self.catalog = Exercise.objects.create(name='Row', slug='row', primary_muscle=self.muscle, equipment=self.equipment)
        self.alice = User.objects.create_user(email='a@example.com', username='a', password='testpassword123')
        self.bob = User.objects.create_user(email='b@example.com', username='b', password='testpassword123')
        self.client = APIClient()
        self.client.force_authenticate(self.alice)

    def test_custom_exercise_is_private_to_its_creator(self):
        res = self.client.post('/api/exercises/', {
            'name': 'Meadows Row', 'primary_muscle': str(self.muscle.id), 'equipment': str(self.equipment.id),
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data['is_custom'])
        self.assertEqual(res.data['slug'], 'meadows-row')

        bob = APIClient()
        bob.force_authenticate(self.bob)
        # The global catalog is no longer necessarily empty in a fresh test
        # database (exercises/migrations/0005_close_equipment_gaps_and_fix_bugs.py
        # adds a handful of real global exercises -- see that migration and
        # ExerciseGapFillMigrationTests below), so assert on privacy
        # (Alice's custom exercise is invisible to Bob) rather than an exact
        # list of every catalog row Bob can see.
        names = [e['name'] for e in bob.get('/api/exercises/').data]
        self.assertIn('Row', names)
        self.assertNotIn('Meadows Row', names)

    def test_catalog_exercises_are_read_only_for_members(self):
        res = self.client.patch(f'/api/exercises/{self.catalog.id}/', {'name': 'Hacked'}, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.client.delete(f'/api/exercises/{self.catalog.id}/').status_code, 403)


class ExerciseGapFillMigrationTests(TestCase):
    """Exercises the RunPython data function in
    exercises/migrations/0005_close_equipment_gaps_and_fix_bugs.py directly.

    A freshly migrated test database never contains the pre-existing buggy
    rows that migration conditionally fixes (no seed command runs against
    it), so to actually test that logic -- not just reimplement equivalent
    assertions -- this builds the pre-fix fixtures by hand (mirroring the
    live dev DB's real rows at audit time) and calls the migration's own
    function against them, using the current (not historical) model
    registry, which is safe here since 0005 is a pure data migration with
    no schema changes.
    """

    def setUp(self):
        self.migration = importlib.import_module(
            'exercises.migrations.0005_close_equipment_gaps_and_fix_bugs'
        )
        # get_or_create: migration 0005 itself already created the 'dumbbell'
        # EquipmentType (and the calves/biceps/hamstrings MuscleGroups) once,
        # for real, when this test database was first migrated -- reaching
        # for the same slug here must reuse that row, not collide with it.
        self.back, _ = MuscleGroup.objects.get_or_create(slug='back', defaults={'name': 'Back'})
        self.dumbbell, _ = EquipmentType.objects.get_or_create(slug='dumbbell', defaults={'name': 'Dumbbell'})
        self.barbell, _ = EquipmentType.objects.get_or_create(slug='barbell', defaults={'name': 'Barbell'})

        # The duplicate pair, same display name, different slugs -- matches
        # the live DB finding exactly.
        self.kept = Exercise.objects.create(
            name='Chest-Supported Dumbbell Row', slug='chest-supported-db-row',
            primary_muscle=self.back, equipment=self.dumbbell,
        )
        self.removed = Exercise.objects.create(
            name='Chest-Supported Dumbbell Row', slug='chest-supported-dumbbell-row',
            primary_muscle=self.back, equipment=self.dumbbell,
        )
        self.deadlift = Exercise.objects.create(
            name='Conventional Deadlift', slug='conventional-deadlift',
            primary_muscle=self.back, equipment=self.barbell,
        )

        # Give the "kept" row a real FK reference, mirroring
        # seed_vivek_journey.py's logged RoutineExercise row in the live DB
        # -- this is what must make the migration refuse to delete it.
        from workouts.models import Routine, RoutineExercise
        user = User.objects.create_user(
            email='migtest@example.com', username='migtest', password='testpassword123'
        )
        routine = Routine.objects.create(user=user, name='Test Routine')
        RoutineExercise.objects.create(routine=routine, exercise=self.kept, order=1)

        self.migration.add_gap_fill_exercises_and_fix_bugs(global_apps, None)

    def test_referenced_duplicate_is_kept_unreferenced_duplicate_is_removed(self):
        self.assertFalse(Exercise.objects.filter(slug='chest-supported-dumbbell-row').exists())
        self.assertTrue(Exercise.objects.filter(slug='chest-supported-db-row').exists())

    def test_conventional_deadlift_reclassified_to_hamstrings(self):
        self.deadlift.refresh_from_db()
        self.assertEqual(self.deadlift.primary_muscle.slug, 'hamstrings')

    def test_new_gap_fill_exercises_created_with_correct_fields(self):
        expected = {
            'bodyweight-standing-calf-raise': ('calves', 'bodyweight'),
            'resistance-band-standing-calf-raise': ('calves', 'resistance-band'),
            'dumbbell-standing-calf-raise': ('calves', 'dumbbell'),
            'resistance-band-bicep-curl': ('biceps', 'resistance-band'),
            'resistance-band-hammer-curl': ('biceps', 'resistance-band'),
            'resistance-band-concentration-curl': ('biceps', 'resistance-band'),
            'bodyweight-single-leg-deadlift': ('hamstrings', 'bodyweight'),
            'resistance-band-romanian-deadlift': ('hamstrings', 'resistance-band'),
            'resistance-band-lying-leg-curl': ('hamstrings', 'resistance-band'),
        }
        self.assertEqual(Exercise.objects.filter(slug__in=expected.keys()).count(), len(expected))
        for slug, (muscle_slug, equip_slug) in expected.items():
            ex = Exercise.objects.get(slug=slug, gym__isnull=True)
            self.assertEqual(ex.primary_muscle.slug, muscle_slug)
            self.assertEqual(ex.equipment.slug, equip_slug)
            self.assertIsNotNone(ex.met_value)

    def test_gap_fill_is_idempotent(self):
        before = Exercise.objects.count()
        self.migration.add_gap_fill_exercises_and_fix_bugs(global_apps, None)
        self.assertEqual(Exercise.objects.count(), before)
