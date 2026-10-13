from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from users.models import User, UserProfile
from gyms.models import Gym
from memberships.models import GymMembership, TrainerClientAssignment
from workouts.models import WorkoutSession, WorkoutExercise, WorkoutSet, JourneyProgram
from exercises.models import MuscleGroup, EquipmentType, Exercise


class TimezoneMiddlewareTests(TestCase):
    """BUG-02: the backend had no per-user timezone handling at all, so every
    'today' boundary resolved against server UTC. These pin the fix to a
    specific, deterministic UTC instant that falls on different calendar
    dates in UTC vs. Asia/Kolkata (2026-01-01 19:00 UTC == 2026-01-02 00:30 IST)."""

    FIXED_NOW = datetime(2026, 1, 1, 19, 0, 0, tzinfo=dt_timezone.utc)

    def _authed_client(self, email, username, tz_name):
        user = User.objects.create_user(email=email, username=username, password='testpassword123')
        UserProfile.objects.filter(user=user).update(timezone=tz_name) if UserProfile.objects.filter(user=user).exists() \
            else UserProfile.objects.create(user=user, timezone=tz_name)
        login = self.client.post('/api/auth/login/', {'email': email, 'password': 'testpassword123'}, format='json')
        self.assertEqual(login.status_code, 200, login.data)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        return user, client

    @patch('django.utils.timezone.now')
    def test_plan_start_date_uses_member_local_date_not_utc(self, mock_now):
        mock_now.return_value = self.FIXED_NOW
        _, kolkata_client = self._authed_client('ist@example.com', 'ist-user', 'Asia/Kolkata')
        res = kolkata_client.post(
            '/api/workouts/sessions/start-journey/',
            {'mode': 'CUT', 'duration_days': 30, 'start_weight_kg': 80},
            format='json',
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['program']['start_date'], '2026-01-02')

    @patch('django.utils.timezone.now')
    def test_plan_start_date_still_correct_for_utc_user(self, mock_now):
        mock_now.return_value = self.FIXED_NOW
        _, utc_client = self._authed_client('utc@example.com', 'utc-user', 'UTC')
        res = utc_client.post(
            '/api/workouts/sessions/start-journey/',
            {'mode': 'CUT', 'duration_days': 30, 'start_weight_kg': 80},
            format='json',
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['program']['start_date'], '2026-01-01')

    @patch('django.utils.timezone.now')
    def test_exercise_calories_attributed_to_members_local_today(self, mock_now):
        mock_now.return_value = self.FIXED_NOW
        user, client = self._authed_client('calories@example.com', 'calories-user', 'Asia/Kolkata')
        muscle = MuscleGroup.objects.create(name='Legs', slug='legs-tz')
        equipment = EquipmentType.objects.create(name='Barbell', slug='barbell-tz')
        exercise = Exercise.objects.create(name='Squat TZ', slug='squat-tz', primary_muscle=muscle, equipment=equipment)
        session = WorkoutSession.objects.create(user=user, title='Late session', started_at=self.FIXED_NOW, completed_at=self.FIXED_NOW)
        we = WorkoutExercise.objects.create(session=session, exercise=exercise)
        WorkoutSet.objects.create(workout_exercise=we, set_number=1, set_type='NORMAL', weight_kg=100, reps=5, completed=True, calories=250)

        res = client.get('/api/nutrition/macro-targets/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['exercise_calories'], 250)

    def test_invalid_timezone_name_is_rejected(self):
        user = User.objects.create_user(email='badtz@example.com', username='badtz-user', password='testpassword123')
        client = APIClient()
        client.force_authenticate(user)
        res = client.patch('/api/auth/me/', {'profile': {'timezone': 'Not/AZone'}}, format='json')
        self.assertEqual(res.status_code, 400)


class FitLogCoreTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="test.member@example.com",
            username="test_member",
            password="testpassword123"
        )
        self.trainer = User.objects.create_user(
            email="test.trainer@example.com",
            username="test_trainer",
            password="testpassword123"
        )
        self.gym = Gym.objects.create(name="Test Performance Gym", slug="test-gym")
        self.member_ship = GymMembership.objects.create(
            user=self.user,
            gym=self.gym,
            role='MEMBER',
            status='ACTIVE'
        )
        self.trainer_ship = GymMembership.objects.create(
            user=self.trainer,
            gym=self.gym,
            role='TRAINER',
            status='ACTIVE'
        )
        self.assignment = TrainerClientAssignment.objects.create(
            trainer_membership=self.trainer_ship,
            client_membership=self.member_ship,
            is_active=True
        )

        muscle = MuscleGroup.objects.create(name="Chest", slug="chest")
        equipment = EquipmentType.objects.create(name="Barbell", slug="barbell")
        self.exercise = Exercise.objects.create(
            name="Bench Press",
            slug="bench-press",
            primary_muscle=muscle,
            equipment=equipment
        )

    def test_auth_login(self):
        response = self.client.post('/api/auth/login/', {
            'email': 'test.member@example.com',
            'password': 'testpassword123'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)

    def test_workout_session_creation(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            'title': 'Test Upper Body Session',
            'started_at': '2026-09-18T10:00:00Z',
            'duration_seconds': 3600,
            'exercises': [
                {
                    'exercise': str(self.exercise.id),
                    'order': 1,
                    'rest_seconds': 90,
                    'sets': [
                        {'set_number': 1, 'set_type': 'NORMAL', 'weight_kg': 80.0, 'reps': 8, 'completed': True},
                        {'set_number': 2, 'set_type': 'NORMAL', 'weight_kg': 80.0, 'reps': 8, 'completed': True}
                    ]
                }
            ]
        }
        response = self.client.post('/api/workouts/sessions/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(WorkoutSession.objects.filter(user=self.user).count(), 1)
        self.assertEqual(WorkoutSet.objects.count(), 2)

    def test_tenant_isolation_and_memberships(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(f'/api/memberships/?gym_id={self.gym.id}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Member can only see their own membership
        data = response.data.get('results', response.data)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['user']['email'], self.user.email)
