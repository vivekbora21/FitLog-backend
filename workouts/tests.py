from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from users.models import User
from exercises.models import Exercise, MuscleGroup, EquipmentType
from .models import Routine, RoutineExercise, WorkoutSession, WorkoutExercise, WorkoutSet
from .progression import parse_rep_range, progression_for


class ProgressionTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='prog@example.com', username='prog', password='testpassword123')
        muscle = MuscleGroup.objects.create(name='Chest', slug='chest')
        equipment = EquipmentType.objects.create(name='Barbell', slug='barbell')
        self.bench = Exercise.objects.create(name='Bench Press', slug='bench-press', primary_muscle=muscle, equipment=equipment)
        self.routine = Routine.objects.create(name='Push', user=self.user, created_by=self.user)
        self.prescription = RoutineExercise.objects.create(
            routine=self.routine, exercise=self.bench, target_sets=3, target_reps='6-8',
            target_rpe=8, suggested_weight_kg=60,
        )

    def log(self, weight, reps, rpe=None, days_ago=2, set_type='NORMAL'):
        started = timezone.now() - timedelta(days=days_ago)
        session = WorkoutSession.objects.create(user=self.user, routine=self.routine, started_at=started, completed_at=started)
        we = WorkoutExercise.objects.create(session=session, exercise=self.bench)
        for i, r in enumerate(reps, start=1):
            WorkoutSet.objects.create(workout_exercise=we, set_number=i, set_type=set_type, weight_kg=weight, reps=r, rpe=rpe)
        return session


class ProgressionRuleTests(ProgressionTestBase):
    def test_parse_rep_range(self):
        self.assertEqual(parse_rep_range('6-8'), (6, 8))
        self.assertEqual(parse_rep_range('12–15'), (12, 15))
        self.assertEqual(parse_rep_range('10'), (10, 10))
        self.assertEqual(parse_rep_range('AMRAP'), (None, None))

    def test_no_history_uses_routine_suggested_weight(self):
        rec = progression_for(self.user, self.prescription)
        self.assertEqual(rec['action'], 'START')
        self.assertEqual(rec['recommended_weight_kg'], 60)
        self.assertIsNone(rec['last_session'])

    def test_all_sets_at_top_of_range_increases_load(self):
        self.log(62.5, [8, 8, 8], rpe=8)
        rec = progression_for(self.user, self.prescription)
        self.assertEqual(rec['action'], 'INCREASE')
        self.assertEqual(rec['recommended_weight_kg'], 65)
        self.assertEqual(rec['last_session']['reps'], [8, 8, 8])

    def test_light_loads_use_smaller_increment(self):
        self.log(10, [8, 8, 8])
        self.assertEqual(progression_for(self.user, self.prescription)['recommended_weight_kg'], 11.25)

    def test_short_of_top_holds_load_and_adds_a_rep(self):
        self.log(62.5, [8, 7, 6])
        rec = progression_for(self.user, self.prescription)
        self.assertEqual(rec['action'], 'HOLD')
        self.assertEqual(rec['recommended_weight_kg'], 62.5)
        self.assertEqual(rec['target_reps'], [8, 8, 7])

    def test_overshooting_rpe_blocks_increase(self):
        self.log(62.5, [8, 8, 8], rpe=9.5)
        self.assertEqual(progression_for(self.user, self.prescription)['action'], 'HOLD')

    def test_uses_most_recent_session_and_ignores_warmups(self):
        self.log(60, [8, 8, 8], days_ago=5)
        self.log(62.5, [6, 6, 6], days_ago=2)
        self.log(40, [10, 10], days_ago=1, set_type='WARMUP')
        rec = progression_for(self.user, self.prescription)
        self.assertEqual(rec['last_session']['weight_kg'], 62.5)
        self.assertEqual(rec['action'], 'HOLD')


class ProgressionApiTests(ProgressionTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_routines_endpoint_exposes_progression(self):
        self.log(62.5, [8, 8, 8])
        res = self.client.get('/api/workouts/routines/')
        data = res.json()
        routines = data.get('results', data)
        progression = routines[0]['exercises'][0]['progression']
        self.assertEqual(progression['recommended_weight_kg'], 65)


class SessionCompletedAtTests(ProgressionTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_completed_at_derived_from_duration_when_omitted(self):
        started = timezone.now() - timedelta(hours=1)
        res = self.client.post('/api/workouts/sessions/', {
            'title': 'Push', 'started_at': started.isoformat(), 'duration_seconds': 3000, 'exercises': [],
        }, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        session = WorkoutSession.objects.get(id=res.json()['id'])
        self.assertEqual(session.completed_at, session.started_at + timedelta(seconds=3000))

    def test_client_completed_at_is_kept(self):
        started = timezone.now() - timedelta(hours=1)
        finished = started + timedelta(minutes=42)
        res = self.client.post('/api/workouts/sessions/', {
            'title': 'Push', 'started_at': started.isoformat(), 'completed_at': finished.isoformat(),
            'duration_seconds': 2520, 'exercises': [],
        }, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(WorkoutSession.objects.get(id=res.json()['id']).completed_at, finished)
