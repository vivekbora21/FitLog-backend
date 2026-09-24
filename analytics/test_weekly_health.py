from datetime import date, datetime, timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from users.models import User
from nutrition.models import NutritionDay, MealEntry
from progress.models import DailyLog
from workouts.models import JourneyProgram, ProgramDay, CardioEntry, Routine, WorkoutSession
from .weekly_health import build_weekly_health, _paced_status, GOOD, WARN, BAD, PENDING


def by_key(health):
    return {m['key']: m for m in health['metrics']}


class PacedStatusTests(TestCase):
    def test_start_of_week_with_nothing_done_is_not_red(self):
        self.assertEqual(_paced_status(0, 5, days_elapsed=1, days_in_week=7, whole_units=True), GOOD)

    def test_behind_pace_mid_week(self):
        # Day 6 of 7 with a 5-session target → 5 days finished → 3 expected.
        self.assertEqual(_paced_status(2, 5, 6, 7, whole_units=True), WARN)
        self.assertEqual(_paced_status(1, 5, 6, 7, whole_units=True), BAD)
        self.assertEqual(_paced_status(3, 5, 6, 7, whole_units=True), GOOD)

    def test_hitting_full_target_is_good(self):
        self.assertEqual(_paced_status(120, 120, 2, 7), GOOD)


class WeeklyHealthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='wh@example.com', username='wh', password='testpassword123')
        self.today = date(2026, 9, 23)  # Wednesday

    def build(self, weekly_review=()):
        return build_weekly_health(self.user, list(weekly_review), weekly_workouts_target=5, cardio_target=120,
                                   calories_target=2160, protein_target=130, today=self.today)

    def test_calendar_fallback_without_program(self):
        monday = self.today - timedelta(days=2)
        for i in range(3):
            DailyLog.objects.create(user=self.user, date=monday + timedelta(days=i), steps=5000, sleep_hours=8.0)
            day = NutritionDay.objects.create(user=self.user, date=monday + timedelta(days=i))
            MealEntry.objects.create(nutrition_day=day, name='Day total', calories=2150, protein_g=108)
        for i in range(2):
            started = timezone.make_aware(datetime.combine(monday + timedelta(days=i), datetime.min.time().replace(hour=12)))
            WorkoutSession.objects.create(user=self.user, started_at=started)
        health = self.build()
        m = by_key(health)
        self.assertEqual(health['window']['source'], 'calendar')
        self.assertEqual(health['window']['days_elapsed'], 3)
        self.assertEqual((m['protein']['actual'], m['protein']['status']), (108, WARN))
        self.assertEqual(m['calories']['status'], GOOD)
        self.assertEqual((m['steps']['actual'], m['steps']['status']), (5000, BAD))
        self.assertEqual(m['sleep']['status'], GOOD)
        self.assertEqual((m['workouts']['actual'], m['workouts']['status']), (2, GOOD))
        self.assertTrue(health['focus'].startswith('Focus this week: steps'))

    def test_unlogged_metrics_are_pending_not_red(self):
        self.today = date(2026, 9, 21)  # Monday: nothing is behind pace yet
        health = self.build()
        m = by_key(health)
        for key in ('protein', 'calories', 'steps', 'sleep'):
            self.assertEqual(m[key]['status'], PENDING)
        self.assertEqual(m['workouts']['status'], GOOD)
        self.assertIn('start logging protein, calories, steps, sleep', health['focus'])


class WeeklyHealthMatchesReviewTests(TestCase):
    """The Dashboard strip and the Review table read the same numbers."""

    def setUp(self):
        self.user = User.objects.create_user(email='whr@example.com', username='whr', password='testpassword123')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        start = date.today() - timedelta(days=9)  # Day 10 → Week 2, 3 days in
        self.program = JourneyProgram.objects.create(user=self.user, mode='CUT', start_date=start, duration_days=60,
                                                     current_day=10, active=True, start_weight_kg=80.0)
        routine = Routine.objects.create(name='Push', user=self.user)
        for day_number in (8, 9):
            ProgramDay.objects.create(program=self.program, day_number=day_number, routine=routine, status='COMPLETED')
        CardioEntry.objects.create(user=self.user, date=start + timedelta(days=8), modality='TREADMILL', duration_minutes=30, completed=True)
        DailyLog.objects.create(user=self.user, date=start + timedelta(days=7), steps=9000, sleep_hours=7.0)

    def test_strip_equals_current_review_row(self):
        data = self.client.get('/api/analytics/dashboard/').json()
        row = next(r for r in data['weekly_review'] if r['is_current'])
        health = data['weekly_health']
        m = by_key(health)
        self.assertEqual(health['window']['source'], 'program')
        self.assertTrue(health['window']['label'].startswith('Week 2'))
        self.assertEqual(m['workouts']['actual'], row['workouts_completed'])
        self.assertEqual(m['workouts']['target'], row['workouts_target'])
        self.assertEqual(m['cardio']['actual'], row['cardio_minutes'])
        self.assertEqual(m['steps']['actual'], row['avg_steps'])
        self.assertEqual(m['sleep']['actual'], row['avg_sleep'])
        self.assertEqual((m['workouts']['actual'], m['cardio']['actual']), (2, 30))

    def test_sessions_count_in_the_week_they_were_done(self):
        # Program Day 5 completed today, a week behind schedule, belongs to the current week.
        started = timezone.now()
        session = WorkoutSession.objects.create(user=self.user, started_at=started)
        ProgramDay.objects.create(program=self.program, day_number=5, routine=Routine.objects.first(),
                                  status='COMPLETED', completed_session=session)
        data = self.client.get('/api/analytics/dashboard/').json()
        self.assertEqual(by_key(data['weekly_health'])['workouts']['actual'], 3)
        self.assertEqual(next(r for r in data['weekly_review'] if r['is_current'])['workouts_completed'], 3)


class CustomTargetDashboardTests(TestCase):
    def test_custom_steps_and_sleep_targets_drive_scoring(self):
        from nutrition.models import MacroTarget
        user = User.objects.create_user(email='ct@example.com', username='ct', password='testpassword123')
        client = APIClient()
        client.force_authenticate(user=user)
        MacroTarget.objects.create(user=user, daily_steps=5000, sleep_hours=7.0, weekly_workouts=3)
        DailyLog.objects.create(user=user, date=date.today(), steps=6000, sleep_hours=7.0)
        data = client.get('/api/analytics/dashboard/').json()
        self.assertEqual(data['adherence']['steps']['target'], 5000)
        self.assertEqual(data['adherence']['sleep']['target'], 7.0)
        self.assertEqual(data['weekly_workouts_target'], 3)
        m = by_key(data['weekly_health'])
        self.assertEqual((m['steps']['status'], m['sleep']['status']), (GOOD, GOOD))
