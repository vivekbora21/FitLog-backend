from datetime import date, datetime, timedelta
from django.test import TestCase
from django.utils import timezone
from users.models import User
from exercises.models import Exercise, MuscleGroup, EquipmentType
from nutrition.models import MacroTarget, NutritionDay, MealEntry
from progress.models import WeightEntry, BodyMeasurement
from workouts.models import JourneyProgram, WorkoutSession, WorkoutExercise, WorkoutSet
from .weekly_review import build_weekly_review

START = date(2026, 9, 14)


class WeeklyReviewRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='wr@example.com', username='wr', password='testpassword123')
        self.program = JourneyProgram.objects.create(user=self.user, mode='CUT', start_date=START, duration_days=60, active=True)

    def review(self, target_kcal=2160, today=START + timedelta(days=30)):
        MacroTarget.objects.update_or_create(user=self.user, defaults={'daily_calories': target_kcal})
        return build_weekly_review(self.user, self.program, start_weight=77.76, start_waist=93.0, today=today)

    def log_week(self, w_idx, weight, waist=None, kcal=None):
        for d in range(7):
            WeightEntry.objects.create(user=self.user, date=START + timedelta(days=w_idx * 7 + d), weight_kg=weight)
        if waist is not None:
            BodyMeasurement.objects.create(user=self.user, date=START + timedelta(days=w_idx * 7 + 6), waist_cm=waist)
        if kcal is not None:
            day = NutritionDay.objects.create(user=self.user, date=START + timedelta(days=w_idx * 7))
            MealEntry.objects.create(nutrition_day=day, name='Day total', calories=kcal)

    def log_lift(self, w_idx, weight, reps=5):
        mg, _ = MuscleGroup.objects.get_or_create(name='Chest', slug='chest')
        eq, _ = EquipmentType.objects.get_or_create(name='Barbell', slug='barbell')
        ex, _ = Exercise.objects.get_or_create(name='Bench Press', slug='bench-press', primary_muscle=mg, equipment=eq)
        started = timezone.make_aware(datetime.combine(START + timedelta(days=w_idx * 7 + 1), datetime.min.time().replace(hour=12)))
        session = WorkoutSession.objects.create(user=self.user, started_at=started)
        we = WorkoutExercise.objects.create(session=session, exercise=ex)
        WorkoutSet.objects.create(workout_exercise=we, weight_kg=weight, reps=reps)

    def test_week_one_is_fixed_return_to_training_row(self):
        self.log_week(0, 77.0, waist=92.5)
        w1 = self.review()[0]
        self.assertEqual(w1['weight_change'], -0.76)  # vs Day-1 baseline
        self.assertEqual(w1['waist_change'], -0.5)
        self.assertEqual(w1['rule_triggered'], 'Return-to-Training Phase')
        self.assertEqual(w1['strength_trend'], 'Baseline Set')

    def test_later_weeks_compare_week_over_week_not_to_baseline(self):
        # Cumulative loss is 2.26 kg by week 3, but only 0.5 kg/wk — must NOT trigger Rule 4.
        self.log_week(0, 76.76, waist=92.0)
        self.log_week(1, 76.0, waist=91.5)
        self.log_week(2, 75.5, waist=91.0)
        w3 = self.review()[2]
        self.assertEqual(w3['weight_change'], -0.5)
        self.assertEqual(w3['waist_change'], -0.5)
        self.assertEqual(w3['rule_triggered'], 'Rule 1 / 2')

    def test_rule_4_fast_drop_with_personal_calorie_step(self):
        self.log_week(0, 77.0, waist=92.0)
        self.log_week(1, 76.0, waist=91.0, kcal=2150)
        w2 = self.review()[1]
        self.assertEqual(w2['rule_triggered'], 'Rule 4')
        self.assertIn('2,260–2,310', w2['personal_note'])

    def test_rule_4_flags_under_eating_instead_of_raising_target(self):
        self.log_week(0, 77.0, waist=92.0)
        self.log_week(1, 76.0, waist=91.0, kcal=1700)
        self.assertIn('460 below', self.review()[1]['personal_note'])

    def test_rule_3_plateau_points_at_calorie_gap(self):
        self.log_week(0, 77.0, waist=92.0)
        self.log_week(1, 76.9, waist=91.9, kcal=2500)
        w2 = self.review()[1]
        self.assertEqual(w2['rule_triggered'], 'Rule 3')
        self.assertIn('+340', w2['personal_note'])

    def test_rule_5_fires_when_strength_declines(self):
        self.log_week(0, 77.0, waist=92.0)
        self.log_week(1, 76.6, waist=91.5)
        self.log_lift(0, 80)
        self.log_lift(1, 72.5)
        w2 = self.review()[1]
        self.assertEqual(w2['strength_trend'], 'Declining')
        self.assertEqual(w2['rule_triggered'], 'Rule 5')

    def test_week_two_waist_falls_back_to_baseline_when_week_one_unmeasured(self):
        self.log_week(0, 77.5)
        self.log_week(1, 77.1, waist=92.0)
        self.assertEqual(self.review()[1]['waist_change'], -1.0)

    def test_weeks_without_weigh_ins_are_awaiting(self):
        rows = self.review()
        self.assertEqual(rows[3]['rule_triggered'], '—')
        self.assertTrue(rows[3]['action_recommendation'].startswith('Awaiting Week 4'))
        self.assertEqual(rows[-1]['action_recommendation'], 'Awaiting final days daily entries')

    def test_empty_nutrition_days_do_not_drag_down_average(self):
        self.log_week(0, 77.0, kcal=2000)
        NutritionDay.objects.create(user=self.user, date=START + timedelta(days=3))
        self.assertEqual(self.review()[0]['avg_calories'], 2000)


class WeeklyReviewTargetHistoryTests(TestCase):
    def test_past_weeks_keep_their_own_calorie_target(self):
        from nutrition.models import TargetHistory
        user = User.objects.create_user(email='hist@example.com', username='hist', password='testpassword123')
        start = date.today() - timedelta(days=20)
        program = JourneyProgram.objects.create(user=user, mode='CUT', start_date=start, duration_days=28, active=True)
        target = MacroTarget.objects.create(user=user, daily_calories=2160)
        TargetHistory.objects.filter(user=user).update(effective_from=start)
        target.daily_calories = 1900
        target.carbs_g -= 65
        target.save()  # changed today, during week 3
        rows = build_weekly_review(user, program, start_weight=80, start_waist=None, today=date.today())
        self.assertEqual([r['calorie_target'] for r in rows[:3]], [2160, 2160, 1900])
