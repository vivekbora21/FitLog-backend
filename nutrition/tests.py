from datetime import date, timedelta
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from users.models import User, UserProfile
from progress.models import WeightEntry
from workouts.models import JourneyProgram
from .models import Food, MacroTarget, MealEntry, NutritionDay
from .defaults import DIET_PLAN_OPTION_A_TARGETS
from .targets import calculate_recommended_targets, mifflin_st_jeor_bmr


def make_user(email='lifter@example.com', **profile):
    user = User.objects.create_user(email=email, username=email, password='testpassword123')
    UserProfile.objects.create(user=user, **profile)
    return user


# The Diet Plan sheet's reference athlete: 31 y/o male, 77.76 kg, moderate activity.
WORKBOOK_PROFILE = dict(sex='MALE', height_cm=174.5, weight_kg=77.76, date_of_birth=date(1995, 1, 1), activity_level='MODERATE')


class RecommendedTargetTests(TestCase):
    def test_bmr_matches_workbook(self):
        self.assertAlmostEqual(mifflin_st_jeor_bmr(77.76, 174.5, 31, 'MALE'), 1718, delta=2)

    def test_cut_journey_reproduces_workbook_targets(self):
        user = make_user(**WORKBOOK_PROFILE)
        JourneyProgram.objects.create(user=user, mode='CUT', start_date=date(2026, 9, 14), duration_days=45, active=True)
        rec = calculate_recommended_targets(user, today=date(2026, 9, 20))
        self.assertTrue(rec['available'])
        self.assertEqual(rec['bmr'], 1718)
        self.assertEqual(rec['calorie_adjustment'], -500)
        self.assertAlmostEqual(rec['daily_calories'], DIET_PLAN_OPTION_A_TARGETS['daily_calories'], delta=10)
        self.assertEqual(rec['protein_g'], 163)  # 2.1 g/kg
        self.assertIn('active journey', rec['goal_source'])

    def test_opposite_goals_get_different_targets(self):
        cutter = make_user('cut@example.com', fitness_goal='FAT_LOSS', **WORKBOOK_PROFILE)
        builder = make_user('bulk@example.com', fitness_goal='HYPERTROPHY', **WORKBOOK_PROFILE)
        cut = calculate_recommended_targets(cutter)
        bulk = calculate_recommended_targets(builder)
        self.assertEqual(bulk['daily_calories'] - cut['daily_calories'], 750)

    def test_latest_weigh_in_overrides_profile_weight(self):
        user = make_user(**WORKBOOK_PROFILE)
        WeightEntry.objects.create(user=user, date=date(2026, 9, 20), weight_kg=70.0)
        rec = calculate_recommended_targets(user)
        self.assertEqual(rec['inputs']['weight_kg'], 70.0)
        self.assertEqual(rec['inputs']['weight_source'], 'latest weigh-in')

    def test_incomplete_profile_reports_missing_fields(self):
        user = make_user(height_cm=180)
        rec = calculate_recommended_targets(user)
        self.assertFalse(rec['available'])
        self.assertEqual(set(rec['missing']), {'weight', 'date_of_birth', 'sex'})

    def test_new_target_is_seeded_from_profile_and_apply_endpoint(self):
        user = make_user(fitness_goal='FAT_LOSS', **WORKBOOK_PROFILE)
        client = APIClient()
        client.force_authenticate(user=user)
        rec = client.get('/api/nutrition/macro-targets/recommended/').json()

        target = client.get('/api/nutrition/macro-targets/').json()
        self.assertEqual(target['daily_calories'], rec['daily_calories'])

        MacroTarget.objects.filter(user=user).update(daily_calories=3000)
        res = client.post('/api/nutrition/macro-targets/recommended/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()['daily_calories'], rec['daily_calories'])

    def test_apply_endpoint_rejects_incomplete_profile(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user=user)
        res = client.post('/api/nutrition/macro-targets/recommended/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


class FoodLoggingTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_catalog_is_seeded_from_diet_plan(self):
        res = self.client.get('/api/nutrition/foods/?search=soaked almonds')
        names = [f['name'] for f in res.json()]
        self.assertIn('Black Coffee + Soaked Almonds + Banana', names)

    def test_logging_food_computes_macros_from_servings(self):
        food = Food.objects.get(name='Whole Boiled Eggs + Steamed Egg Whites')  # 230 kcal, 23/2/11
        res = self.client.post('/api/nutrition/meals/', {'meal_type': 'BREAKFAST', 'food': str(food.id), 'servings': 1.5}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        body = res.json()
        self.assertEqual(body['name'], food.name)
        self.assertEqual(body['calories'], 345)
        self.assertEqual(body['protein_g'], 34.5)
        self.assertEqual(body['fat_g'], 16.5)

    def test_client_macros_are_ignored_when_food_is_given(self):
        food = Food.objects.get(name='Fresh Ripe Banana + Green Tea')
        res = self.client.post('/api/nutrition/meals/', {'meal_type': 'SNACK', 'food': str(food.id), 'calories': 9999}, format='json')
        self.assertEqual(res.json()['calories'], 100)

    def test_free_text_entry_still_works_and_needs_calories(self):
        ok = self.client.post('/api/nutrition/meals/', {'meal_type': 'LUNCH', 'name': 'Thali', 'calories': 700, 'protein_g': 25}, format='json')
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED)
        bad = self.client.post('/api/nutrition/meals/', {'meal_type': 'LUNCH', 'name': 'Thali'}, format='json')
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

    def test_custom_foods_are_private_and_catalog_is_read_only(self):
        mine = self.client.post('/api/nutrition/foods/', {'name': 'My Protein Shake', 'serving_label': '1 scoop + 300ml milk', 'calories': 280, 'protein_g': 32}, format='json')
        self.assertEqual(mine.status_code, status.HTTP_201_CREATED)
        self.assertTrue(mine.json()['is_custom'])

        other = make_user('other@example.com')
        other_client = APIClient()
        other_client.force_authenticate(user=other)
        self.assertNotIn('My Protein Shake', [f['name'] for f in other_client.get('/api/nutrition/foods/?search=shake').json()])
        res = other_client.post('/api/nutrition/meals/', {'meal_type': 'SNACK', 'food': mine.json()['id']}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        catalog = Food.objects.filter(owner=None).first()
        self.assertEqual(self.client.delete(f'/api/nutrition/foods/{catalog.id}/').status_code, status.HTTP_403_FORBIDDEN)

    def test_logged_entry_is_a_snapshot(self):
        food = self.client.post('/api/nutrition/foods/', {'name': 'Poha', 'serving_label': '1 plate', 'calories': 250}, format='json').json()
        self.client.post('/api/nutrition/meals/', {'meal_type': 'BREAKFAST', 'food': food['id']}, format='json')
        self.client.patch(f"/api/nutrition/foods/{food['id']}/", {'calories': 400}, format='json')
        self.assertEqual(MealEntry.objects.get(food_id=food['id']).calories, 250)

    def test_logging_food_with_quantity_field(self):
        food = Food.objects.get(name='Whole Boiled Eggs + Steamed Egg Whites')  # 230 kcal, 23/2/11
        res = self.client.post('/api/nutrition/meals/', {'meal_type': 'BREAKFAST', 'food': str(food.id), 'quantity': 2.0}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        body = res.json()
        self.assertEqual(body['quantity'], 2.0)
        self.assertEqual(body['servings'], 2.0)
        self.assertEqual(body['calories'], 460)
        self.assertEqual(body['protein_g'], 46.0)


class RecentFoodsAndRepeatYesterdayTests(TestCase):
    def setUp(self):
        self.user = make_user('tester@example.com')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_recent_foods_endpoint_returns_user_history(self):
        food = Food.objects.first()
        today = date.today()
        day = NutritionDay.objects.create(user=self.user, date=today)
        MealEntry.objects.create(
            nutrition_day=day,
            meal_type='BREAKFAST',
            name=food.name,
            food=food,
            servings=1.5,
            calories=300,
            protein_g=20,
            carbs_g=30,
            fat_g=5
        )
        MealEntry.objects.create(
            nutrition_day=day,
            meal_type='LUNCH',
            name='Homemade Dal Rice',
            servings=1.0,
            calories=500,
            protein_g=22,
            carbs_g=75,
            fat_g=8
        )

        res = self.client.get('/api/nutrition/recent-foods/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        recents = res.json()
        self.assertEqual(len(recents), 2)
        names = [r['name'] for r in recents]
        self.assertIn(food.name, names)
        self.assertIn('Homemade Dal Rice', names)

    def test_repeat_yesterdays_breakfast(self):
        yesterday = date.today() - timedelta(days=1)
        y_day = NutritionDay.objects.create(user=self.user, date=yesterday)
        food = Food.objects.first()
        MealEntry.objects.create(
            nutrition_day=y_day,
            meal_type='BREAKFAST',
            name=food.name,
            food=food,
            servings=2.0,
            calories=460,
            protein_g=46.0,
            carbs_g=4.0,
            fat_g=22.0
        )
        MealEntry.objects.create(
            nutrition_day=y_day,
            meal_type='LUNCH',
            name='Grilled Chicken',
            servings=1.0,
            calories=350,
            protein_g=40.0,
            carbs_g=0.0,
            fat_g=10.0
        )

        # Repeat yesterday's breakfast
        res = self.client.post('/api/nutrition/repeat-yesterday/', {'meal_type': 'BREAKFAST'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertEqual(data['copied_count'], 1)
        self.assertEqual(data['meals'][0]['name'], food.name)
        self.assertEqual(data['meals'][0]['meal_type'], 'BREAKFAST')
        self.assertEqual(data['meals'][0]['quantity'], 2.0)

        # Today's day should only have Breakfast, not Lunch
        today_day = NutritionDay.objects.get(user=self.user, date=date.today())
        self.assertEqual(today_day.meals.count(), 1)
        self.assertEqual(today_day.meals.first().meal_type, 'BREAKFAST')

    def test_repeat_yesterday_handles_missing_log_gracefully(self):
        # No yesterday exists
        res = self.client.post('/api/nutrition/repeat-yesterday/', {'meal_type': 'BREAKFAST'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

        # Yesterday exists, but has no breakfast
        yesterday = date.today() - timedelta(days=1)
        y_day = NutritionDay.objects.create(user=self.user, date=yesterday)
        MealEntry.objects.create(nutrition_day=y_day, meal_type='DINNER', name='Salad', calories=100)
        res2 = self.client.post('/api/nutrition/repeat-yesterday/', {'meal_type': 'BREAKFAST'}, format='json')
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nutrition_day_view_includes_yesterday_meals(self):
        yesterday = date.today() - timedelta(days=1)
        y_day = NutritionDay.objects.create(user=self.user, date=yesterday)
        MealEntry.objects.create(nutrition_day=y_day, meal_type='BREAKFAST', name='Oatmeal', calories=300)

        res = self.client.get('/api/nutrition/today/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertIn('yesterday_meals', data)
        self.assertEqual(len(data['yesterday_meals']), 1)
        self.assertEqual(data['yesterday_meals'][0]['name'], 'Oatmeal')


class EditableTargetTests(TestCase):
    URL = '/api/nutrition/macro-targets/'

    def setUp(self):
        self.user = make_user(**WORKBOOK_PROFILE)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        MacroTarget.objects.update_or_create(user=self.user, defaults=DIET_PLAN_OPTION_A_TARGETS)

    def put(self, **data):
        return self.client.put(self.URL, data, format='json')

    def test_raising_protein_takes_calories_from_carbs(self):
        res = self.put(protein_g=180)  # +15 g = +60 kcal
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        body = res.json()
        self.assertEqual((body['protein_g'], body['carbs_g'], body['daily_calories']), (180, 249, 2160))
        self.assertIn('264 g to 249 g', body['adjustments'][0])

    def test_changing_calories_alone_moves_carbs(self):
        body = self.put(daily_calories=2260).json()
        self.assertEqual(body['carbs_g'], 289)

    def test_explicit_carbs_are_not_rebalanced(self):
        body = self.put(protein_g=180, carbs_g=264).json()
        self.assertEqual(body['carbs_g'], 264)
        self.assertEqual(body['adjustments'], [])

    def test_dry_run_previews_without_saving(self):
        body = self.put(protein_g=180, dry_run=True).json()
        self.assertEqual(body['carbs_g'], 249)
        self.assertEqual(MacroTarget.objects.get(user=self.user).protein_g, 165)

    def test_hard_limits_reject(self):
        res = self.put(daily_calories=900, sleep_hours=2)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(set(res.json()['errors']), {'daily_calories', 'sleep_hours'})
        # Protein so high that carbs would go negative.
        self.assertEqual(self.put(protein_g=400, fat_g=200).status_code, status.HTTP_400_BAD_REQUEST)

    def test_extreme_but_allowed_values_warn(self):
        res = self.put(protein_g=260, carbs_g=150, sleep_hours=6)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        fields = {w['field'] for w in res.json()['warnings']}
        self.assertTrue({'protein_g', 'sleep_hours'} <= fields)

    def test_plan_fields_follow_plan_until_set(self):
        body = self.client.get(self.URL).json()
        self.assertIsNone(body['weekly_workouts'])
        self.assertEqual(body['effective']['weekly_workouts'], 5)
        body = self.put(weekly_workouts=3, weekly_cardio_minutes=90).json()
        self.assertEqual(body['effective'], {'weekly_workouts': 3, 'weekly_cardio_minutes': 90})
        body = self.put(weekly_workouts=None).json()
        self.assertEqual(body['effective']['weekly_workouts'], 5)
        self.assertIn('suggested', body)


class TargetHistoryTests(TestCase):
    def setUp(self):
        self.user = make_user(**WORKBOOK_PROFILE)

    def test_each_day_resolves_the_target_in_effect(self):
        from .models import TargetHistory
        from .targets import TargetTimeline
        target = MacroTarget.objects.create(user=self.user, protein_g=140)
        today = date.today()
        TargetHistory.objects.filter(user=self.user).update(effective_from=today - timedelta(days=30))
        target.protein_g = 180
        target.save()
        timeline = TargetTimeline(self.user)
        self.assertEqual(timeline.on(today - timedelta(days=10)).protein_g, 140)
        self.assertEqual(timeline.on(today - timedelta(days=60)).protein_g, 140)  # before first record
        self.assertEqual(timeline.on(today).protein_g, 180)

    def test_saving_unchanged_values_adds_no_history(self):
        from .models import TargetHistory
        target = MacroTarget.objects.create(user=self.user)
        target.save()
        self.assertEqual(TargetHistory.objects.filter(user=self.user).count(), 1)


class NutritionHistoryViewTests(TestCase):
    def setUp(self):
        self.user = make_user('historyuser@example.com', **WORKBOOK_PROFILE)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_nutrition_history_endpoint(self):
        today = date.today()
        program = JourneyProgram.objects.create(
            user=self.user,
            mode='CUT',
            start_date=today - timedelta(days=9),
            duration_days=30,
            active=True
        )

        # Log meals for today and 2 days ago
        day_today = NutritionDay.objects.create(user=self.user, date=today, water_consumed_ml=2000)
        MealEntry.objects.create(
            nutrition_day=day_today,
            meal_type='BREAKFAST',
            name='Oatmeal & Protein',
            calories=450,
            protein_g=35.0,
            carbs_g=50.0,
            fat_g=8.0,
        )

        res = self.client.get('/api/nutrition-history/?days=10')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertIn('history', data)
        self.assertIn('targets', data)
        self.assertIn('program', data)
        self.assertEqual(len(data['history']), 10)

        # Today should be Day 10 (started 9 days ago)
        today_entry = data['history'][0]
        self.assertEqual(today_entry['date'], today.isoformat())
        self.assertEqual(today_entry['program_day_number'], 10)
        self.assertEqual(today_entry['total_calories'], 450)
        self.assertEqual(today_entry['total_protein'], 35.0)
        self.assertEqual(today_entry['water_consumed_ml'], 2000)
        self.assertTrue(today_entry['has_logged'])
        self.assertEqual(today_entry['meal_count'], 1)
        self.assertEqual(today_entry['meals'][0]['name'], 'Oatmeal & Protein')

        # Day with no food
        empty_entry = data['history'][1]
        self.assertFalse(empty_entry['has_logged'])
        self.assertEqual(empty_entry['total_calories'], 0)
        self.assertEqual(empty_entry['program_day_number'], 9)
