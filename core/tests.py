from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from users.models import User
from gyms.models import Gym
from memberships.models import GymMembership, TrainerClientAssignment
from workouts.models import WorkoutSession, WorkoutSet
from exercises.models import MuscleGroup, EquipmentType, Exercise

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
