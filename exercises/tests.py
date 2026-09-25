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
        names = [e['name'] for e in bob.get('/api/exercises/').data]
        self.assertEqual(names, ['Row'])

    def test_catalog_exercises_are_read_only_for_members(self):
        res = self.client.patch(f'/api/exercises/{self.catalog.id}/', {'name': 'Hacked'}, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.client.delete(f'/api/exercises/{self.catalog.id}/').status_code, 403)
