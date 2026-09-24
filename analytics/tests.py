from datetime import date, timedelta
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from users.models import User
from workouts.models import JourneyProgram, ProgramDay, Routine
from progress.models import DailyLog, WeightEntry
from nutrition.models import MacroTarget, NutritionDay, MealEntry
from analytics.pacing import resolve_start_weight, resolve_target_weekly_rate, resolve_target_weight, calculate_journey_pacing

class AnalyticsAdherenceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="athlete@example.com",
            username="athlete",
            password="testpassword123"
        )
        self.client.force_authenticate(user=self.user)

    def test_dashboard_stats_adherence_without_program(self):
        response = self.client.get('/api/analytics/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('adherence', data)
        adherence = data['adherence']
        self.assertIn('workout', adherence)
        self.assertIn('weekly_workouts', adherence)
        self.assertIn('calories', adherence)
        self.assertIn('protein', adherence)
        self.assertIn('water', adherence)
        self.assertIn('cardio', adherence)

    def test_dashboard_stats_adherence_matches_pacing_with_program(self):
        routine = Routine.objects.create(
            user=self.user,
            name="Upper Body Power",
        )
        program = JourneyProgram.objects.create(
            user=self.user,
            name="Cut 60",
            mode="CUT",
            current_day=3,
            duration_days=60,
            active=True,
            start_date=date.today(),
        )
        ProgramDay.objects.create(program=program, day_number=1, routine=routine, status='COMPLETED')
        ProgramDay.objects.create(program=program, day_number=2, routine=routine, status='COMPLETED')
        ProgramDay.objects.create(program=program, day_number=3, routine=routine, status='UPCOMING')

        response = self.client.get('/api/analytics/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        adherence = data['adherence']
        pacing_adherence = data['journey_pacing']['adherence']

        # Verify adherence in both places is synchronized to identical numbers
        self.assertEqual(adherence['workout']['percent'], pacing_adherence['adherence_pct'])
        self.assertEqual(adherence['workout']['actual'], pacing_adherence['completed_sessions'])
        self.assertEqual(adherence['workout']['target'], pacing_adherence['scheduled_sessions'])
        self.assertEqual(adherence['workout']['status'], pacing_adherence['status'])

    def test_recovery_pillar_and_weekly_review_aggregation(self):
        start_d = date.today() - timedelta(days=6)
        program = JourneyProgram.objects.create(
            user=self.user,
            name="Cut 60",
            mode="CUT",
            current_day=7,
            duration_days=60,
            active=True,
            start_date=start_d,
            start_weight_kg=80.0,
        )

        # Log daily step & sleep entries across the week
        for i in range(7):
            d = start_d + timedelta(days=i)
            DailyLog.objects.create(
                user=self.user,
                date=d,
                steps=8500,
                sleep_hours=8.0,
                energy_level=4,
                recovery_notes="Feeling recovered"
            )
            WeightEntry.objects.create(user=self.user, date=d, weight_kg=79.5)

        response = self.client.get('/api/analytics/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        # Check recovery pillar
        pacing = data['journey_pacing']
        self.assertIn('recovery', pacing)
        rec = pacing['recovery']
        self.assertEqual(rec['status'], 'OPTIMAL')
        self.assertEqual(rec['avg_sleep_hours'], 8.0)
        self.assertEqual(rec['avg_daily_steps'], 8500)
        self.assertFalse(rec['fatigue_debt_detected'])

        # Check adherence payload includes steps and sleep
        self.assertIn('steps', data['adherence'])
        self.assertIn('sleep', data['adherence'])

        # Check weekly review sheet
        self.assertIn('weekly_review', data)
        self.assertTrue(len(data['weekly_review']) > 0)
        w1 = data['weekly_review'][0]
        self.assertEqual(w1['week'], 'Week 1')
        self.assertEqual(w1['avg_steps'], 8500)
        self.assertEqual(w1['avg_sleep'], 8.0)
        self.assertEqual(w1['avg_weight'], 79.5)
        self.assertEqual(w1['weight_change'], -0.5)

    def test_fatigue_debt_detection_rule_5(self):
        start_d = date.today() - timedelta(days=6)
        JourneyProgram.objects.create(
            user=self.user,
            name="Cut 60",
            mode="CUT",
            current_day=7,
            duration_days=60,
            active=True,
            start_date=start_d,
            start_weight_kg=80.0,
        )

        # Log daily entries with sleep deficit (< 6.5h)
        for i in range(7):
            d = start_d + timedelta(days=i)
            DailyLog.objects.create(
                user=self.user,
                date=d,
                steps=5000,
                sleep_hours=5.5,
                energy_level=2,
            )
            WeightEntry.objects.create(user=self.user, date=d, weight_kg=79.5)

        response = self.client.get('/api/analytics/dashboard/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        pacing = data['journey_pacing']
        rec = pacing['recovery']
        self.assertTrue(rec['fatigue_debt_detected'])
        self.assertEqual(rec['status'], 'FATIGUE_RISK')
        # Rule 5 check in insight
        self.assertIn('Rule 5', pacing['copilot_insight'])


class RightPathPacingEngineTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="pacing_athlete@example.com",
            username="pacing_athlete",
            password="testpassword123"
        )
        self.client.force_authenticate(user=self.user)
        self.macro_target, _ = MacroTarget.objects.update_or_create(
            user=self.user,
            defaults={
                'daily_calories': 2160,
                'protein_g': 165,
                'carbs_g': 240,
                'fat_g': 55,
                'water_ml': 3500,
            }
        )

    def test_copilot_insight_calibration_references_macro_target(self):
        program = JourneyProgram.objects.create(
            user=self.user,
            name="Cut 60",
            mode="CUT",
            current_day=3,
            duration_days=60,
            active=True,
            start_date=date.today(),
            start_weight_kg=80.0,
        )
        pacing = calculate_journey_pacing(self.user, program)
        self.assertTrue(pacing['is_calibrating'])
        self.assertIn("165g protein target", pacing['copilot_insight'])
        self.assertIn("2,160 kcal/day", pacing['copilot_insight'])

    def test_copilot_insight_cut_too_fast_with_logged_intake_gap(self):
        start_d = date.today() - timedelta(days=14)
        program = JourneyProgram.objects.create(
            user=self.user,
            name="Cut 60",
            mode="CUT",
            current_day=14,
            duration_days=60,
            active=True,
            start_date=start_d,
            start_weight_kg=80.0,
            target_weight_kg=75.7,
            target_weekly_rate_kg=-0.5,
        )
        # Log fast weight drop (80.0 -> 77.8 in 14 days = -1.1 kg/wk)
        WeightEntry.objects.create(user=self.user, date=start_d, weight_kg=80.0)
        WeightEntry.objects.create(user=self.user, date=start_d + timedelta(days=7), weight_kg=78.9)
        WeightEntry.objects.create(user=self.user, date=date.today(), weight_kg=77.8)

        # Log meals averaging 1,800 kcal (360 kcal deficit gap below 2,160 target)
        for i in range(5):
            d = date.today() - timedelta(days=i)
            nd = NutritionDay.objects.create(user=self.user, date=d)
            MealEntry.objects.create(nutrition_day=nd, meal_type='LUNCH', name='Lunch', calories=1000, protein_g=80)
            MealEntry.objects.create(nutrition_day=nd, meal_type='DINNER', name='Dinner', calories=800, protein_g=70)

        pacing = calculate_journey_pacing(self.user, program)
        self.assertEqual(pacing['velocity']['status'], 'TOO_FAST')
        insight = pacing['copilot_insight']
        self.assertIn("1,800 kcal/day", insight)
        self.assertIn("2,160 kcal target", insight)
        self.assertIn("360 kcal deficit gap", insight)
        self.assertIn("165g protein", insight)

    def test_copilot_insight_cut_too_fast_without_meal_logs_uses_velocity_gap(self):
        start_d = date.today() - timedelta(days=14)
        program = JourneyProgram.objects.create(
            user=self.user,
            name="Cut 60",
            mode="CUT",
            current_day=14,
            duration_days=60,
            active=True,
            start_date=start_d,
            start_weight_kg=80.0,
            target_weight_kg=75.7,
            target_weekly_rate_kg=-0.5,
        )
        WeightEntry.objects.create(user=self.user, date=start_d, weight_kg=80.0)
        WeightEntry.objects.create(user=self.user, date=start_d + timedelta(days=7), weight_kg=78.9)
        WeightEntry.objects.create(user=self.user, date=date.today(), weight_kg=77.8)

        pacing = calculate_journey_pacing(self.user, program)
        self.assertEqual(pacing['velocity']['status'], 'TOO_FAST')
        insight = pacing['copilot_insight']
        self.assertIn("velocity gap calls for", insight)
        self.assertIn("2,160 kcal", insight)
        self.assertIn("165g protein", insight)

    def test_copilot_insight_cut_stalled_with_excess_intake(self):
        start_d = date.today() - timedelta(days=14)
        program = JourneyProgram.objects.create(
            user=self.user,
            name="Cut 60",
            mode="CUT",
            current_day=14,
            duration_days=60,
            active=True,
            start_date=start_d,
            start_weight_kg=80.0,
            target_weight_kg=75.7,
            target_weekly_rate_kg=-0.5,
        )
        # Stalled weight (80.0 -> 80.0 over 14 days)
        WeightEntry.objects.create(user=self.user, date=start_d, weight_kg=80.0)
        WeightEntry.objects.create(user=self.user, date=start_d + timedelta(days=7), weight_kg=80.0)
        WeightEntry.objects.create(user=self.user, date=date.today(), weight_kg=80.0)

        # Log meals averaging 2,360 kcal (+200 kcal above 2,160 target)
        for i in range(5):
            d = date.today() - timedelta(days=i)
            nd = NutritionDay.objects.create(user=self.user, date=d)
            MealEntry.objects.create(nutrition_day=nd, meal_type='LUNCH', name='Lunch', calories=1360, protein_g=80)
            MealEntry.objects.create(nutrition_day=nd, meal_type='DINNER', name='Dinner', calories=1000, protein_g=70)

        pacing = calculate_journey_pacing(self.user, program)
        self.assertEqual(pacing['velocity']['status'], 'STALLED')
        insight = pacing['copilot_insight']
        self.assertIn("2,360 kcal/day", insight)
        self.assertIn("200 kcal above your 2,160 kcal target", insight)

    def test_start_journey_deduplication_and_rate_resolution(self):
        # Test start_journey endpoint resolving start weight and default weekly rate
        response = self.client.post('/api/workouts/sessions/start-journey/', {
            'mode': 'CUT',
            'duration_days': 60,
            'start_weight_kg': 82.5,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        program = data['program']
        self.assertEqual(program['start_weight_kg'], 82.5)
        self.assertEqual(program['target_weekly_rate_kg'], -0.5)
        # 82.5 + (-0.5 * (60 / 7)) = 82.5 - 4.2857 = 78.2
        self.assertEqual(program['target_weight_kg'], 78.2)

        # Check pacing payload includes copilot_insight referencing macro target
        pacing = data['pacing']
        self.assertIn('copilot_insight', pacing)
        self.assertIn('165g protein target (2,160 kcal/day)', pacing['copilot_insight'])

        # Verify WeightEntry was created for today
        latest_w = WeightEntry.objects.filter(user=self.user, date=date.today()).first()
        self.assertIsNotNone(latest_w)
        self.assertEqual(latest_w.weight_kg, 82.5)



    def test_start_journey_accepts_target_end_date(self):
        end_date = date.today() + timedelta(days=99)
        response = self.client.post('/api/workouts/sessions/start-journey/', {
            'mode': 'CUT',
            'end_date': end_date.isoformat(),
            'start_weight_kg': 82.5,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['program']['duration_days'], 100)
        program = JourneyProgram.objects.get(user=self.user, active=True)
        self.assertEqual(program.days.count(), 100)

    def test_start_journey_rejects_out_of_range_length(self):
        for payload in ({'duration_days': 3}, {'duration_days': 400}, {'end_date': 'not-a-date'}, {}):
            response = self.client.post('/api/workouts/sessions/start-journey/', {'mode': 'CUT', **payload}, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, payload)
        self.assertFalse(JourneyProgram.objects.filter(user=self.user).exists())

    def test_cardio_phase_scales_with_plan_length(self):
        program = JourneyProgram(duration_days=120, target_cardio_minutes_early=120, target_cardio_minutes_later=150)
        self.assertEqual(program.early_cardio_phase_days, 30)
        self.assertEqual(program.cardio_target_for_day(30), 120)
        self.assertEqual(program.cardio_target_for_day(31), 150)
        # Short plans still get a full first week in the early phase.
        self.assertEqual(JourneyProgram(duration_days=14).early_cardio_phase_days, 7)
