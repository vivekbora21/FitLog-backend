from datetime import timedelta
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from users.models import User, UserProfile
from exercises.models import Exercise, MuscleGroup, EquipmentType
from .models import Routine, RoutineExercise, WorkoutSession, WorkoutExercise, WorkoutSet, CardioEntry, JourneyProgram, ProgramDay
from gyms.models import Gym
from memberships.models import GymMembership
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


class SessionEditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='edit@example.com', username='edit', password='testpassword123')
        self.other = User.objects.create_user(email='other@example.com', username='other', password='testpassword123')
        muscle = MuscleGroup.objects.create(name='Legs', slug='legs')
        equipment = EquipmentType.objects.create(name='Barbell', slug='barbell')
        self.squat = Exercise.objects.create(name='Squat', slug='squat', primary_muscle=muscle, equipment=equipment)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self, weight, reps, set_type='NORMAL'):
        return {
            'title': 'Legs',
            'started_at': (timezone.now() - timedelta(hours=1)).isoformat(),
            'duration_seconds': 3600,
            'exercises': [{
                'exercise': str(self.squat.id), 'order': 1, 'rest_seconds': 120,
                'sets': [{'set_number': 1, 'set_type': set_type, 'weight_kg': weight, 'reps': reps, 'completed': True}],
            }],
        }

    def test_edit_replaces_sets_and_lowers_pr(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(140, 5), format='json')
        self.assertEqual(res.status_code, 201)
        session_id = res.data['id']
        res = self.client.put(f'/api/workouts/sessions/{session_id}/', self.payload(100, 5), format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['exercises'][0]['sets'][0]['weight_kg'], 100)
        self.assertEqual(self.user.personal_records.get(exercise=self.squat).max_weight_kg, 100)

    def test_delete_removes_orphaned_pr(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(120, 3), format='json')
        self.client.delete(f"/api/workouts/sessions/{res.data['id']}/")
        self.assertFalse(self.user.personal_records.exists())

    def test_warmup_set_does_not_register_as_a_pr(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(200, 5, set_type='WARMUP'), format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertFalse(self.user.personal_records.filter(exercise=self.squat).exists())

    def test_drop_set_does_not_register_as_a_pr(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(200, 5, set_type='DROP'), format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertFalse(self.user.personal_records.filter(exercise=self.squat).exists())

    def test_normal_set_still_registers_as_a_pr_alongside_a_warmup(self):
        payload = self.payload(120, 5, set_type='NORMAL')
        payload['exercises'][0]['sets'].insert(
            0, {'set_number': 1, 'set_type': 'WARMUP', 'weight_kg': 200, 'reps': 5, 'completed': True}
        )
        payload['exercises'][0]['sets'][1]['set_number'] = 2
        res = self.client.post('/api/workouts/sessions/', payload, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        pr = self.user.personal_records.get(exercise=self.squat)
        self.assertEqual(pr.max_weight_kg, 120)

    def test_rebuild_after_edit_excludes_warmup_and_drop_sets(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(120, 5, set_type='NORMAL'), format='json')
        session_id = res.data['id']
        self.assertEqual(self.user.personal_records.get(exercise=self.squat).max_weight_kg, 120)

        res = self.client.put(f'/api/workouts/sessions/{session_id}/', self.payload(300, 5, set_type='DROP'), format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(self.user.personal_records.filter(exercise=self.squat).exists())

    def test_cannot_edit_someone_elses_session(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(120, 3), format='json')
        intruder = APIClient()
        intruder.force_authenticate(self.other)
        res = intruder.patch(f"/api/workouts/sessions/{res.data['id']}/", {'title': 'x'}, format='json')
        self.assertEqual(res.status_code, 404)

    def test_last_performance_and_recent_exercises(self):
        self.client.post('/api/workouts/sessions/', self.payload(120, 3), format='json')
        res = self.client.get('/api/workouts/sessions/last-performance/', {'exercises': f'{self.squat.id},not-a-uuid'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data[str(self.squat.id)]['sets'][0], {'set_type': 'NORMAL', 'weight_kg': 120, 'reps': 3})
        res = self.client.get('/api/workouts/sessions/recent-exercises/')
        self.assertEqual(res.data[0]['name'], 'Squat')

    def test_negative_weight_is_rejected(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(-50, 5), format='json')
        self.assertEqual(res.status_code, 400)


class JourneyDetailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='journey@example.com', username='journey', password='testpassword123')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_journey_detail_returns_200_for_valid_journey(self):
        start_res = self.client.post(
            '/api/workouts/sessions/start-journey/',
            {'mode': 'CUT', 'duration_days': 30, 'start_weight_kg': 80},
            format='json',
        )
        self.assertEqual(start_res.status_code, 201, start_res.data)
        journey_id = start_res.data['program']['id']

        detail_res = self.client.get(f'/api/workouts/sessions/journey/{journey_id}/')
        self.assertEqual(detail_res.status_code, 200)
        self.assertIn('days', detail_res.data)

    def test_journey_detail_404_for_missing_journey(self):
        res = self.client.get('/api/workouts/sessions/journey/00000000-0000-0000-0000-000000000000/')
        self.assertEqual(res.status_code, 404)

    def test_journey_detail_404_for_other_users_journey(self):
        start_res = self.client.post(
            '/api/workouts/sessions/start-journey/',
            {'mode': 'CUT', 'duration_days': 30, 'start_weight_kg': 80},
            format='json',
        )
        journey_id = start_res.data['program']['id']
        other = User.objects.create_user(email='other-journey@example.com', username='other-journey', password='testpassword123')
        intruder = APIClient()
        intruder.force_authenticate(other)
        res = intruder.get(f'/api/workouts/sessions/journey/{journey_id}/')
        self.assertEqual(res.status_code, 404)


class DuplicateSubmissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='dup@example.com', username='dup', password='testpassword123')
        muscle = MuscleGroup.objects.create(name='Back', slug='back-dup')
        equipment = EquipmentType.objects.create(name='Barbell', slug='barbell-dup')
        self.row = Exercise.objects.create(name='Row', slug='row-dup', primary_muscle=muscle, equipment=equipment)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self, idempotency_key=None):
        data = {
            'title': 'Pull Day',
            'started_at': (timezone.now() - timedelta(hours=1)).isoformat(),
            'duration_seconds': 3600,
            'exercises': [{
                'exercise': str(self.row.id), 'order': 1, 'rest_seconds': 90,
                'sets': [{'set_number': 1, 'set_type': 'NORMAL', 'weight_kg': 80, 'reps': 8, 'completed': True}],
            }],
        }
        if idempotency_key:
            data['idempotency_key'] = idempotency_key
        return data

    def test_sequential_retry_with_same_key_does_not_duplicate_session(self):
        key = 'retry-key-1'
        res1 = self.client.post('/api/workouts/sessions/', self.payload(key), format='json')
        self.assertEqual(res1.status_code, 201, res1.data)
        res2 = self.client.post('/api/workouts/sessions/', self.payload(key), format='json')
        self.assertEqual(res2.status_code, 201, res2.data)
        self.assertEqual(res1.data['id'], res2.data['id'])
        self.assertEqual(WorkoutSession.objects.filter(user=self.user).count(), 1)

    def test_different_keys_create_separate_sessions(self):
        res1 = self.client.post('/api/workouts/sessions/', self.payload('key-a'), format='json')
        res2 = self.client.post('/api/workouts/sessions/', self.payload('key-b'), format='json')
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res2.status_code, 201)
        self.assertNotEqual(res1.data['id'], res2.data['id'])
        self.assertEqual(WorkoutSession.objects.filter(user=self.user).count(), 2)

    def test_no_key_behaves_as_before(self):
        res1 = self.client.post('/api/workouts/sessions/', self.payload(), format='json')
        res2 = self.client.post('/api/workouts/sessions/', self.payload(), format='json')
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res2.status_code, 201)
        self.assertEqual(WorkoutSession.objects.filter(user=self.user).count(), 2)

    def test_retry_does_not_double_advance_journey_program(self):
        routine = Routine.objects.create(name='Pull Day Routine', user=self.user, created_by=self.user)
        program = JourneyProgram.objects.create(
            user=self.user, name='Test Journey', mode='CUT',
            start_date=timezone.localdate(), duration_days=7, current_day=1, active=True,
        )
        day1 = ProgramDay.objects.create(program=program, day_number=1, routine=routine, label='Day 1', status='UPCOMING')
        ProgramDay.objects.create(program=program, day_number=2, routine=routine, label='Day 2', status='UPCOMING')

        payload = self.payload('journey-retry-key')
        payload['routine'] = str(routine.id)
        res1 = self.client.post('/api/workouts/sessions/', payload, format='json')
        self.assertEqual(res1.status_code, 201, res1.data)
        program.refresh_from_db()
        self.assertEqual(program.current_day, 2)

        res2 = self.client.post('/api/workouts/sessions/', payload, format='json')
        self.assertEqual(res2.status_code, 201, res2.data)
        self.assertEqual(res1.data['id'], res2.data['id'])
        program.refresh_from_db()
        self.assertEqual(program.current_day, 2)
        day1.refresh_from_db()
        self.assertEqual(day1.status, 'COMPLETED')


class ConcurrentDuplicateSubmissionTests(TransactionTestCase):
    """Uses TransactionTestCase (real commits, separate connections per thread) so the
    two requests genuinely race at the database level instead of sharing one
    uncommitted test-wrapper transaction."""

    def setUp(self):
        self.user = User.objects.create_user(email='dup-concurrent@example.com', username='dup-concurrent', password='testpassword123')
        muscle = MuscleGroup.objects.create(name='Back', slug='back-dup-concurrent')
        equipment = EquipmentType.objects.create(name='Barbell', slug='barbell-dup-concurrent')
        self.row = Exercise.objects.create(name='Row', slug='row-dup-concurrent', primary_muscle=muscle, equipment=equipment)

    def test_concurrent_retry_with_same_key_does_not_duplicate_session(self):
        import threading
        from django.db import connections

        key = 'retry-key-concurrent'
        results = []
        payload = {
            'title': 'Pull Day',
            'started_at': (timezone.now() - timedelta(hours=1)).isoformat(),
            'duration_seconds': 3600,
            'idempotency_key': key,
            'exercises': [{
                'exercise': str(self.row.id), 'order': 1, 'rest_seconds': 90,
                'sets': [{'set_number': 1, 'set_type': 'NORMAL', 'weight_kg': 80, 'reps': 8, 'completed': True}],
            }],
        }

        def submit():
            try:
                client = APIClient()
                client.force_authenticate(self.user)
                res = client.post('/api/workouts/sessions/', payload, format='json')
                results.append(res.status_code)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(results, [201, 201])
        self.assertEqual(WorkoutSession.objects.filter(user=self.user).count(), 1)


class RoutineDeletionPermissionTests(TestCase):
    def setUp(self):
        self.gym = Gym.objects.create(name='Iron Temple')
        self.owner = User.objects.create_user(email='owner@example.com', username='owner-routine', password='testpassword123')
        self.trainer = User.objects.create_user(email='trainer@example.com', username='trainer-routine', password='testpassword123')
        self.member_a = User.objects.create_user(email='membera@example.com', username='member-a-routine', password='testpassword123')
        self.member_b = User.objects.create_user(email='memberb@example.com', username='member-b-routine', password='testpassword123')
        GymMembership.objects.create(user=self.owner, gym=self.gym, role='OWNER', status='ACTIVE')
        GymMembership.objects.create(user=self.trainer, gym=self.gym, role='TRAINER', status='ACTIVE')
        GymMembership.objects.create(user=self.member_a, gym=self.gym, role='MEMBER', status='ACTIVE')
        GymMembership.objects.create(user=self.member_b, gym=self.gym, role='MEMBER', status='ACTIVE')
        self.template = Routine.objects.create(name='Gym Push Day', gym=self.gym, created_by=self.owner)
        self.personal = Routine.objects.create(name='My Routine', user=self.member_a, created_by=self.member_a)

    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_ordinary_member_cannot_delete_shared_template(self):
        res = self._client_for(self.member_a).delete(f'/api/workouts/routines/{self.template.id}/')
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Routine.objects.filter(id=self.template.id).exists())

    def test_owner_can_delete_shared_template(self):
        res = self._client_for(self.owner).delete(f'/api/workouts/routines/{self.template.id}/')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Routine.objects.filter(id=self.template.id).exists())

    def test_trainer_can_delete_shared_template(self):
        res = self._client_for(self.trainer).delete(f'/api/workouts/routines/{self.template.id}/')
        self.assertEqual(res.status_code, 204)

    def test_other_member_cannot_delete_someone_elses_personal_routine(self):
        # Not in this user's own-or-gym queryset at all, so it 404s rather than 403 —
        # consistent with how other per-user resources are isolated in this codebase.
        res = self._client_for(self.member_b).delete(f'/api/workouts/routines/{self.personal.id}/')
        self.assertEqual(res.status_code, 404)
        self.assertTrue(Routine.objects.filter(id=self.personal.id).exists())

    def test_owner_can_delete_own_personal_routine(self):
        res = self._client_for(self.member_a).delete(f'/api/workouts/routines/{self.personal.id}/')
        self.assertEqual(res.status_code, 204)

    def test_deleting_template_used_by_active_program_returns_clean_error_not_500(self):
        program = JourneyProgram.objects.create(
            user=self.member_a, name='Journey', mode='CUT',
            start_date=timezone.localdate(), duration_days=7, current_day=1, active=True,
        )
        ProgramDay.objects.create(program=program, day_number=1, routine=self.template, label='Day 1', status='UPCOMING')
        res = self._client_for(self.owner).delete(f'/api/workouts/routines/{self.template.id}/')
        self.assertEqual(res.status_code, 400)
        self.assertTrue(Routine.objects.filter(id=self.template.id).exists())


class DayStatusTests(TestCase):
    """BUG-09 support: lets a client holding a stale local draft check whether the
    server already considers that date done, before offering to 'Resume' it."""

    def setUp(self):
        self.user = User.objects.create_user(email='daystatus@example.com', username='daystatus', password='testpassword123')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        muscle = MuscleGroup.objects.create(name='Chest', slug='chest-daystatus')
        equipment = EquipmentType.objects.create(name='Barbell', slug='barbell-daystatus')
        self.bench = Exercise.objects.create(name='Bench', slug='bench-daystatus', primary_muscle=muscle, equipment=equipment)

    def test_no_activity_is_not_done(self):
        res = self.client.get('/api/workouts/sessions/day-status/', {'date': '2026-03-01'})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data['is_already_done'])
        self.assertFalse(res.data['has_session'])

    def test_logged_session_marks_day_done(self):
        session = WorkoutSession.objects.create(
            user=self.user, title='Push Day',
            started_at=timezone.make_aware(timezone.datetime(2026, 3, 1, 10, 0, 0)),
            completed_at=timezone.make_aware(timezone.datetime(2026, 3, 1, 11, 0, 0)),
        )
        res = self.client.get('/api/workouts/sessions/day-status/', {'date': '2026-03-01'})
        self.assertTrue(res.data['is_already_done'])
        self.assertTrue(res.data['has_session'])
        self.assertEqual(res.data['session_id'], str(session.id))

    def test_self_reported_completed_day_marks_day_done(self):
        from progress.models import DailyLog
        DailyLog.objects.create(user=self.user, date=timezone.datetime(2026, 3, 2).date(), day_status='COMPLETED')
        res = self.client.get('/api/workouts/sessions/day-status/', {'date': '2026-03-02'})
        self.assertTrue(res.data['is_already_done'])
        self.assertTrue(res.data['self_reported_completed'])
        self.assertFalse(res.data['has_session'])

    def test_completed_program_day_marks_day_done(self):
        routine = Routine.objects.create(name='Push Day Routine', user=self.user, created_by=self.user)
        program = JourneyProgram.objects.create(
            user=self.user, name='Journey', mode='CUT',
            start_date=timezone.datetime(2026, 3, 3).date(), duration_days=7, current_day=1, active=True,
        )
        ProgramDay.objects.create(program=program, day_number=1, routine=routine, label='Day 1', status='COMPLETED')
        res = self.client.get('/api/workouts/sessions/day-status/', {'date': '2026-03-03'})
        self.assertTrue(res.data['is_already_done'])
        self.assertTrue(res.data['program_day_completed'])

    def test_defaults_to_today_without_date_param(self):
        res = self.client.get('/api/workouts/sessions/day-status/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['date'], timezone.localdate().isoformat())

    def test_invalid_date_format_is_rejected(self):
        res = self.client.get('/api/workouts/sessions/day-status/', {'date': 'not-a-date'})
        self.assertEqual(res.status_code, 400)


class CardioEntrySyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='cardio@example.com', username='cardio', password='testpassword123')
        muscle = MuscleGroup.objects.create(name='Cardio', slug='cardio')
        equipment = EquipmentType.objects.create(name='Machine', slug='machine')
        self.treadmill = Exercise.objects.create(name='Treadmill Run', slug='treadmill-run', primary_muscle=muscle, equipment=equipment)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self, duration_seconds, with_cardio=True):
        exercises = []
        if with_cardio:
            exercises.append({
                'exercise': str(self.treadmill.id), 'order': 1, 'rest_seconds': 0,
                'sets': [{
                    'set_number': 1, 'set_type': 'NORMAL', 'weight_kg': 0, 'reps': 0,
                    'completed': True, 'duration_seconds': duration_seconds, 'intensity': 'Zone 2',
                }],
            })
        return {
            'title': 'Cardio',
            'started_at': (timezone.now() - timedelta(hours=1)).isoformat(),
            'duration_seconds': duration_seconds,
            'exercises': exercises,
        }

    def test_create_generates_cardio_entry_linked_to_session(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(1800), format='json')
        self.assertEqual(res.status_code, 201, res.data)
        entry = CardioEntry.objects.get(session_id=res.data['id'])
        self.assertEqual(entry.duration_minutes, 30)

    def test_edit_updates_existing_cardio_entry_instead_of_duplicating(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(1800), format='json')
        session_id = res.data['id']
        res = self.client.put(f'/api/workouts/sessions/{session_id}/', self.payload(2700), format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(CardioEntry.objects.filter(session_id=session_id).count(), 1)
        self.assertEqual(CardioEntry.objects.get(session_id=session_id).duration_minutes, 45)

    def test_removing_cardio_exercise_deletes_the_entry(self):
        res = self.client.post('/api/workouts/sessions/', self.payload(1800), format='json')
        session_id = res.data['id']
        res = self.client.put(f'/api/workouts/sessions/{session_id}/', self.payload(0, with_cardio=False), format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(CardioEntry.objects.filter(session_id=session_id).exists())


class StandaloneCardioCalorieTests(TestCase):
    """Covers the bug where cardio logged outside a workout session (via
    /api/workouts/cardio/ directly) contributed zero calories to the Progress
    Activity tab, because CardioEntry had no calorie figure of its own."""

    def setUp(self):
        self.user = User.objects.create_user(email='standalone@example.com', username='standalone', password='testpassword123')
        UserProfile.objects.create(user=self.user, weight_kg=80)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_standalone_cardio_entry_gets_an_estimated_calorie_figure(self):
        res = self.client.post('/api/workouts/cardio/', {
            'date': timezone.localdate().isoformat(),
            'modality': 'CYCLING',
            'duration_minutes': 30,
            'completed': True,
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        entry = CardioEntry.objects.get(id=res.data['id'])
        self.assertIsNone(entry.session)
        self.assertGreater(entry.calories, 0)
        self.assertEqual(res.data['calories'], entry.calories)

    def test_standalone_cardio_entry_counts_toward_calorie_history(self):
        self.client.post('/api/workouts/cardio/', {
            'date': timezone.localdate().isoformat(),
            'modality': 'TREADMILL',
            'duration_minutes': 45,
            'completed': True,
        }, format='json')
        res = self.client.get('/api/workouts/calorie-history/', {'days': 7})
        self.assertEqual(res.status_code, 200)
        today_entry = next(h for h in res.data['history'] if h['date'] == timezone.localdate().isoformat())
        self.assertGreater(today_entry['calories_burned'], 0)
        self.assertTrue(today_entry['has_workout'])
