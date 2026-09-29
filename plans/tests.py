from types import SimpleNamespace
from django.test import TestCase
from rest_framework.test import APIClient
from users.models import User
from workouts.models import JourneyProgram, ProgramDay
from .models import Blueprint
from .services.plan_generator import calculate_targets, generate_roadmap, activity_level_from_days_per_week


def make_blueprint_stub(mode, duration_days=60, days_per_week=4):
    return SimpleNamespace(
        mode=mode,
        default_duration_days=duration_days,
        default_days_per_week=days_per_week,
        phases=[
            {'name': 'Foundation', 'start_day': 1, 'end_day': round(duration_days * 0.3)},
            {'name': 'Build', 'start_day': round(duration_days * 0.3) + 1, 'end_day': round(duration_days * 0.7)},
            {'name': 'Peak', 'start_day': round(duration_days * 0.7) + 1, 'end_day': duration_days},
        ],
        workout_templates={
            'day_1': [{'exercise_name': 'Squat', 'sets': 4, 'reps': '6-8', 'rpe': 7.5, 'rest_seconds': 120, 'progression_rule': 'add load'}],
            'day_2': [],
            'day_3': [{'exercise_name': 'Bench', 'sets': 4, 'reps': '6-8', 'rpe': 7.5, 'rest_seconds': 120, 'progression_rule': 'add load'}],
            'day_4': [],
            'day_5': [{'exercise_name': 'Deadlift', 'sets': 3, 'reps': '5', 'rpe': 8.0, 'rest_seconds': 150, 'progression_rule': 'add load'}],
            'day_6': [],
            'day_7': [],
        },
        meal_templates={
            'breakfast': {'sample_foods': ['Eggs'], 'protein_g': 30, 'kcal': 400, 'fat_g': 12, 'swap_options': ['Yogurt']},
            'lunch': {'sample_foods': ['Chicken'], 'protein_g': 40, 'kcal': 550, 'fat_g': 14, 'swap_options': ['Turkey']},
            'snack': {'sample_foods': ['Shake'], 'protein_g': 25, 'kcal': 280, 'fat_g': 8, 'swap_options': ['Nuts']},
            'dinner': {'sample_foods': ['Salmon'], 'protein_g': 35, 'kcal': 520, 'fat_g': 18, 'swap_options': ['Beef']},
        },
    )


class ActivityLevelTests(TestCase):
    def test_monotonic_buckets(self):
        self.assertEqual(activity_level_from_days_per_week(1), 'LIGHT')
        self.assertEqual(activity_level_from_days_per_week(2), 'LIGHT')
        self.assertEqual(activity_level_from_days_per_week(3), 'MODERATE')
        self.assertEqual(activity_level_from_days_per_week(4), 'MODERATE')
        self.assertEqual(activity_level_from_days_per_week(5), 'HIGH')
        self.assertEqual(activity_level_from_days_per_week(6), 'HIGH')
        self.assertEqual(activity_level_from_days_per_week(7), 'ATHLETE')


class CalculateTargetsTests(TestCase):
    base_kwargs = dict(weight_kg=80, height_cm=178, age_years=30, sex='MALE', days_per_week=4, duration_days=60)

    def test_cut_produces_deficit_and_protein(self):
        result = calculate_targets(mode='CUT', **self.base_kwargs)
        self.assertLess(result['daily_calories'], result['tdee'])
        self.assertEqual(result['protein_g'], round(2.2 * 80))
        self.assertLess(result['weekly_rate_kg'], 0)
        self.assertEqual(result['warnings'], [])

    def test_bulk_produces_surplus(self):
        result = calculate_targets(mode='BULK', **self.base_kwargs)
        self.assertEqual(result['daily_calories'], round(result['tdee']) + 275)
        self.assertEqual(result['protein_g'], round(1.8 * 80))
        self.assertGreater(result['weekly_rate_kg'], 0)

    def test_recomp_small_deficit(self):
        result = calculate_targets(mode='RECOMP', **self.base_kwargs)
        self.assertLess(result['daily_calories'], result['tdee'])
        self.assertAlmostEqual(result['weekly_rate_kg'], -0.15, places=2)

    def test_focus_maintenance(self):
        result = calculate_targets(mode='FOCUS', **self.base_kwargs)
        self.assertEqual(result['daily_calories'], round(result['tdee']))
        self.assertEqual(result['weekly_rate_kg'], 0.0)

    def test_habit_maintenance(self):
        result = calculate_targets(mode='HABIT', **self.base_kwargs)
        self.assertEqual(result['daily_calories'], round(result['tdee']))
        self.assertEqual(result['protein_g'], round(1.8 * 80))

    def test_unsafe_pacing_is_clamped_and_warned(self):
        # 20kg loss over 60 days (~2.3 kg/week) far exceeds the 1.0 kg/week cap.
        result = calculate_targets(mode='CUT', weight_kg=80, height_cm=178, age_years=30, sex='MALE',
                                    days_per_week=4, duration_days=60, goal_weight_kg=60)
        self.assertEqual(abs(result['weekly_rate_kg']), 1.0)
        self.assertTrue(any('clamped' in w for w in result['warnings']))

    def test_calorie_floor_enforced_for_small_female(self):
        # Very small bodyweight + aggressive cut should hit the calorie floor.
        result = calculate_targets(mode='CUT', weight_kg=45, height_cm=150, age_years=25, sex='FEMALE',
                                    days_per_week=3, duration_days=60, goal_weight_kg=40)
        self.assertGreaterEqual(result['daily_calories'], 1200)
        self.assertTrue(any('floor' in w.lower() for w in result['warnings']))


class GenerateRoadmapStubTests(TestCase):
    def user_inputs(self, **overrides):
        base = dict(
            duration_days=60, days_per_week=4, weekdays=[1, 3, 5, 6],
            current_weight_kg=80, goal_weight_kg=75, height_cm=178, age=30, sex='MALE',
        )
        base.update(overrides)
        return base

    def test_roadmap_shape_and_length(self):
        blueprint = make_blueprint_stub('CUT')
        roadmap = generate_roadmap(blueprint, self.user_inputs())
        for key in ('summary', 'feasibility', 'phases', 'days', 'meal_template', 'targets', 'warnings'):
            self.assertIn(key, roadmap)
        self.assertEqual(len(roadmap['days']), 60)
        self.assertEqual(roadmap['phases'][-1]['end_day'], 60)
        self.assertEqual(roadmap['phases'][0]['start_day'], 1)

    def test_rest_day_vs_training_day_targets_differ(self):
        blueprint = make_blueprint_stub('CUT')
        roadmap = generate_roadmap(blueprint, self.user_inputs())
        training_day = next(d for d in roadmap['days'] if not d['is_rest'])
        rest_day = next(d for d in roadmap['days'] if d['is_rest'])
        self.assertLess(rest_day['targets']['daily_calories'], training_day['targets']['daily_calories'])
        self.assertIsNotNone(training_day['workout'])
        self.assertIsNone(rest_day['workout'])

    def test_weight_interpolation(self):
        blueprint = make_blueprint_stub('CUT')
        roadmap = generate_roadmap(blueprint, self.user_inputs(duration_days=10, goal_weight_kg=70, current_weight_kg=80, weekdays=[1, 3, 5, 6]))
        self.assertEqual(roadmap['days'][0]['expected_weight_kg'], 80)
        self.assertEqual(roadmap['days'][-1]['expected_weight_kg'], 70)

    def test_aggressive_or_unrealistic_feasibility_flagged(self):
        blueprint = make_blueprint_stub('CUT')
        # 30kg loss in 60 days => 3.5 kg/week, way past the cap -> unrealistic.
        roadmap = generate_roadmap(blueprint, self.user_inputs(current_weight_kg=100, goal_weight_kg=70, duration_days=60))
        self.assertEqual(roadmap['feasibility']['status'], 'unrealistic')
        self.assertTrue(any('pace' in w.lower() for w in roadmap['warnings']))

    def test_safe_feasibility(self):
        blueprint = make_blueprint_stub('RECOMP')
        roadmap = generate_roadmap(blueprint, self.user_inputs(current_weight_kg=80, goal_weight_kg=79, duration_days=60))
        self.assertEqual(roadmap['feasibility']['status'], 'safe')

    def test_fallback_weekday_uses_blueprint_frequency(self):
        blueprint = make_blueprint_stub('HABIT')
        roadmap = generate_roadmap(blueprint, self.user_inputs(weekdays=[], duration_days=7))
        # blueprint template has non-empty day_1, day_3, day_5 -> 3 training days.
        rest_flags = [d['is_rest'] for d in roadmap['days']]
        self.assertEqual(rest_flags, [False, True, False, True, False, True, True])


class BlueprintOrmTests(TestCase):
    def test_generate_roadmap_against_real_blueprint(self):
        blueprint = Blueprint.objects.create(
            slug='test-cut',
            name='Test Cut',
            mode='CUT',
            default_duration_days=60,
            default_days_per_week=4,
            pacing_kg_per_week=-0.5,
            phases=[{'name': 'Foundation', 'start_day': 1, 'end_day': 18},
                    {'name': 'Build', 'start_day': 19, 'end_day': 42},
                    {'name': 'Peak', 'start_day': 43, 'end_day': 60}],
            workout_templates={'day_1': [{'exercise_name': 'Squat', 'sets': 4, 'reps': '6-8', 'rpe': 7.5, 'rest_seconds': 120, 'progression_rule': 'add load'}],
                                'day_2': [], 'day_3': [], 'day_4': [], 'day_5': [], 'day_6': [], 'day_7': []},
            meal_templates={'breakfast': {'sample_foods': ['Eggs'], 'protein_g': 30, 'kcal': 400, 'fat_g': 12, 'swap_options': []}},
        )
        roadmap = generate_roadmap(blueprint, dict(
            duration_days=60, days_per_week=4, weekdays=[1], current_weight_kg=80,
            goal_weight_kg=75, height_cm=178, age=30, sex='MALE',
        ))
        self.assertEqual(len(roadmap['days']), 60)
        self.assertEqual(roadmap['meal_template'], blueprint.meal_templates)


class PlanApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='plans@example.com', username='plansuser', password='testpassword123')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        from django.core.management import call_command
        call_command('seed_blueprints')

    def valid_payload(self, **overrides):
        payload = dict(
            blueprint_slug='cut-60', duration_days=60, days_per_week=4, weekdays=[1, 2, 4, 6],
            current_weight_kg=85, goal_weight_kg=80, height_cm=180, age=28, sex='MALE',
        )
        payload.update(overrides)
        return payload

    def test_list_blueprints(self):
        response = self.client.get('/api/plans/blueprints/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['blueprints']), 5)

    def test_preview_does_not_persist(self):
        response = self.client.post('/api/plans/preview/', self.valid_payload(), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        for key in ('summary', 'feasibility', 'phases', 'days', 'meal_template', 'targets', 'warnings'):
            self.assertIn(key, response.data)
        self.assertEqual(JourneyProgram.objects.count(), 0)

    def test_create_plan_persists_program_and_days(self):
        response = self.client.post('/api/plans/', self.valid_payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(JourneyProgram.objects.filter(user=self.user, active=True).count(), 1)
        program = JourneyProgram.objects.get(user=self.user, active=True)
        self.assertEqual(ProgramDay.objects.filter(program=program).count(), 60)
        day = ProgramDay.objects.filter(program=program, day_number=1).first()
        self.assertIsNotNone(day.macro_targets)
        self.assertIsNotNone(day.meal_payload)

    def test_create_plan_twice_archives_first(self):
        self.client.post('/api/plans/', self.valid_payload(), format='json')
        self.client.post('/api/plans/', self.valid_payload(duration_days=30, weekdays=[1, 3, 5, 6]), format='json')
        self.assertEqual(JourneyProgram.objects.filter(user=self.user, active=True).count(), 1)
        self.assertEqual(JourneyProgram.objects.filter(user=self.user).count(), 2)

    def test_missing_blueprint_and_mode_fails(self):
        payload = self.valid_payload()
        payload.pop('blueprint_slug')
        response = self.client.post('/api/plans/preview/', payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_focus_mode_large_goal_weight_delta_rejected(self):
        payload = self.valid_payload(blueprint_slug=None, mode='FOCUS', goal_weight_kg=70, current_weight_kg=85)
        payload.pop('blueprint_slug')
        response = self.client.post('/api/plans/preview/', payload, format='json')
        self.assertEqual(response.status_code, 400)
