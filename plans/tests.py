from datetime import date, timedelta
from types import SimpleNamespace
from django.test import TestCase
from rest_framework.test import APIClient
from users.models import User
from workouts.models import JourneyProgram, ProgramDay
from .models import Blueprint, TrainingSplit
from .services.plan_generator import (
    EXPERIENCE_VOLUME_RANGES, MAJOR_MUSCLE_GROUPS, VOLUME_OUTSIDE_RANGE_CODE,
    calculate_targets, exercise_names_in_workout_templates, generate_roadmap,
)
from .services.exercise_lookup import muscle_group_by_exercise_name
from .split_approval import (
    DAYS_TO_SPLIT_SLUGS, EQUIPMENT_LEVELS, SPLIT_APPROVAL,
    approved_combinations, approved_slugs_for, is_split_approved,
)


def make_blueprint_stub(mode, duration_days=60, days_per_week=4):
    return SimpleNamespace(
        mode=mode,
        default_duration_days=duration_days,
        default_days_per_week=days_per_week,
        # generate_roadmap (via plan_generator.resolve_workout_templates)
        # falls back to this attribute whenever a test doesn't pass its own
        # `training_split=`; a plain SimpleNamespace needs it defined
        # explicitly, unlike the real Blueprint model (which defines the
        # field with a null default). Pre-existing gap in this fixture --
        # exactly the "unrelated SimpleNamespace fixture bug" the task
        # brief's baseline note refers to (plans.tests.GenerateRoadmapStubTests'
        # 7 pre-existing errors); fixed here since every test in this pass
        # that touches generate_roadmap's (edited) workout-template
        # resolution now depends on this fixture working.
        default_training_split=None,
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
    """`activity_level` now drives the engine's real TDEE multiplier
    (plan_engine.config.ACTIVITY_FACTOR_BY_LEVEL) instead of a cosmetic
    label derived from days_per_week -- the previous
    `activity_level_from_days_per_week` bucketing is gone; two users with
    the same days_per_week but different real activity levels must now get
    different TDEE/calories."""

    def _tdee(self, activity_level):
        result = calculate_targets(
            weight_kg=80, height_cm=180, age_years=30, sex='MALE',
            days_per_week=4, mode='FOCUS', duration_days=30,
            activity_level=activity_level,
        )
        return result['tdee']

    def test_activity_level_changes_tdee_at_fixed_training_frequency(self):
        sedentary = self._tdee('SEDENTARY')
        moderate = self._tdee('MODERATE')
        athlete = self._tdee('ATHLETE')
        self.assertLess(sedentary, moderate)
        self.assertLess(moderate, athlete)

    def test_default_activity_level_is_moderate(self):
        self.assertEqual(self._tdee(None), self._tdee('MODERATE'))

    def test_moderate_four_days_matches_pre_fix_sample_case(self):
        # Spec v1.6's worked example (male, 4 days/week, BMR 1705.5) expects
        # activity_factor 1.55 / tdee ~2643.5 -- MODERATE's factor is 1.55,
        # so the default case is unchanged by this fix. `tdee` here is
        # already serialized/rounded to an int (2643.525 -> 2644).
        result = calculate_targets(
            weight_kg=76.3, height_cm=174, age_years=30, sex='MALE',
            days_per_week=4, mode='FOCUS', duration_days=30,
            activity_level='MODERATE',
        )
        self.assertEqual(result['tdee'], 2644)


class CalculateTargetsTests(TestCase):
    """`calculate_targets` is now a thin wrapper around the plan_engine
    (spec v1.6 section 4) -- see `plans/services/engine_adapter.py`. Every
    assertion below that used to encode plan_generator's own (older, now
    retired) constants has been updated to the spec-correct values; see the
    implementation report for the itemized before/after list. Cut/Bulk also
    now require an explicit `goal_weight_kg` to get a numeric target at all
    (spec V-05 GOAL_WEIGHT_REQUIRED) -- fixtures that omitted it have had
    one added.
    """
    base_kwargs = dict(weight_kg=80, height_cm=178, age_years=30, sex='MALE', days_per_week=4, duration_days=60)

    def test_cut_produces_deficit_and_protein(self):
        # 6kg loss over 60 days (~0.7 kg/week, ~0.88%/week) -- a goal weight
        # is now mandatory for Cut to get a numeric target at all.
        result = calculate_targets(mode='CUT', goal_weight_kg=74, **self.base_kwargs)
        self.assertLess(result['daily_calories'], result['tdee'])
        # protein: 2.2 g/kg (old) -> 2.0 g/kg (spec 4.7, Cut/Recomp).
        self.assertEqual(result['protein_g'], 160)
        self.assertLess(result['weekly_rate_kg'], 0)
        self.assertEqual(result['warnings'], [])
        self.assertTrue(result['can_start'])

    def test_bulk_produces_surplus(self):
        # 3kg gain over 60 days (~0.35 kg/week, ~0.44%/week, within Bulk's
        # typical band) -- a goal weight is now mandatory for Bulk too.
        # The old flat "+275 kcal surplus" formula is gone: Bulk's surplus
        # is now derived from goal/duration like Cut's deficit (spec 4.3).
        result = calculate_targets(mode='BULK', goal_weight_kg=83, **self.base_kwargs)
        self.assertGreater(result['daily_calories'], result['tdee'])
        # protein: 1.8 g/kg, unchanged old -> new for Bulk.
        self.assertEqual(result['protein_g'], 144)
        self.assertGreater(result['weekly_rate_kg'], 0)

    def test_recomp_small_deficit(self):
        # Recomp no longer predicts a numeric weekly rate at all (old: a
        # flat -0.15 kg/week default). Spec 4.3 makes Recomp "directional"
        # precision -- a fixed -5% of TDEE deficit (default Lean Out
        # direction), with no weight-change prediction (predicted_weekly_
        # change_kg stays null; see plan_engine/engine.py).
        result = calculate_targets(mode='RECOMP', **self.base_kwargs)
        self.assertLess(result['daily_calories'], result['tdee'])
        self.assertIsNone(result['weekly_rate_kg'])
        self.assertEqual(result['precision'], 'directional')

    def test_focus_maintenance(self):
        result = calculate_targets(mode='FOCUS', **self.base_kwargs)
        self.assertEqual(result['daily_calories'], round(result['tdee']))
        # Maintenance precision predicts no weight change at all (old: an
        # explicit 0.0 kg/week); now null, like Recomp/Habit.
        self.assertIsNone(result['weekly_rate_kg'])
        self.assertEqual(result['precision'], 'maintenance')

    def test_habit_maintenance(self):
        result = calculate_targets(mode='HABIT', **self.base_kwargs)
        self.assertEqual(result['daily_calories'], round(result['tdee']))
        # protein: 1.8 g/kg (old) -> 1.6 g/kg (spec 4.7 gives Habit no value
        # of its own; product-owner decision: use Focus's value, since
        # Habit is computed identically to Focus).
        self.assertEqual(result['protein_g'], 128)

    def test_unsafe_pacing_blocks_and_floors_calories(self):
        # 20kg loss over 60 days (~2.33 kg/week, ~2.92%/week) is far beyond
        # Cut's hard pace limit (1.5%/week, spec 4.6). The old behavior
        # silently clamped the implied rate to a flat 1.0 kg/week cap; the
        # engine instead still computes a target from the full requested
        # rate (validation is advisory, spec 4/5), floors the resulting
        # (very low) calories to the safe minimum, and reports
        # `can_start = False` with a block-severity `PACE_ABOVE_LIMIT`
        # message plus a `CALORIES_RAISED_TO_FLOOR` warning.
        result = calculate_targets(mode='CUT', weight_kg=80, height_cm=178, age_years=30, sex='MALE',
                                    days_per_week=4, duration_days=60, goal_weight_kg=60)
        self.assertFalse(result['can_start'])
        codes = {m['code'] for m in result['messages']}
        self.assertIn('PACE_ABOVE_LIMIT', codes)
        self.assertIn('CALORIES_RAISED_TO_FLOOR', codes)
        self.assertEqual(result['daily_calories'], 1500)
        self.assertTrue(any('floor' in w.lower() for w in result['warnings']))

    def test_calorie_floor_enforced_for_small_female(self):
        # Very small bodyweight + aggressive cut should hit the calorie floor.
        result = calculate_targets(mode='CUT', weight_kg=45, height_cm=150, age_years=25, sex='FEMALE',
                                    days_per_week=3, duration_days=60, goal_weight_kg=40)
        self.assertGreaterEqual(result['daily_calories'], 1200)
        self.assertTrue(any('floor' in w.lower() for w in result['warnings']))


class GenerateRoadmapStubTests(TestCase):
    # A fixed Monday (spec v1.6 6.6: day_number 1 is scheduled on this real
    # calendar date). Pinning it keeps every test in this class
    # deterministic -- without it, generate_roadmap's new default (the first
    # selected training weekday on/after the real "today") would make which
    # day_number lands on which weekday vary by the date the suite runs,
    # and several tests below assert exact day_number <-> rest/training
    # correspondences that only hold when day 1 is a Monday (ordinal 1).
    MONDAY = date(2024, 1, 1)

    def user_inputs(self, **overrides):
        base = dict(
            duration_days=60, days_per_week=4, weekdays=[1, 3, 5, 6],
            current_weight_kg=80, goal_weight_kg=75, height_cm=178, age=30, sex='MALE',
            start_date=self.MONDAY,
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

    def test_within_typical_range_feasibility(self):
        # Spec v1.6 section 9 copy rule: never "safe" -- the status label
        # (and message) read "within_typical_range"/"within the typical
        # range" instead; same classification as before, reworded.
        blueprint = make_blueprint_stub('RECOMP')
        roadmap = generate_roadmap(blueprint, self.user_inputs(current_weight_kg=80, goal_weight_kg=79, duration_days=60))
        self.assertEqual(roadmap['feasibility']['status'], 'within_typical_range')
        self.assertNotIn('safe', roadmap['feasibility']['message'].lower())

    def test_fallback_weekday_uses_blueprint_frequency(self):
        blueprint = make_blueprint_stub('HABIT')
        roadmap = generate_roadmap(blueprint, self.user_inputs(weekdays=[], duration_days=7))
        # blueprint template has non-empty day_1, day_3, day_5 -> 3 training days.
        rest_flags = [d['is_rest'] for d in roadmap['days']]
        self.assertEqual(rest_flags, [False, True, False, True, False, True, True])

    def test_chosen_weekdays_beyond_blueprint_split_count_still_get_a_workout(self):
        # The stub blueprint only defines 3 real splits (day_1/day_3/day_5), but the
        # member asked for 4 training days a week. Every chosen training day must still
        # carry a real workout (cycling through the blueprint's splits), not a gap.
        blueprint = make_blueprint_stub('CUT')
        roadmap = generate_roadmap(
            blueprint, self.user_inputs(duration_days=7, days_per_week=4, weekdays=[1, 2, 3, 6])
        )
        by_day = {d['day_number']: d for d in roadmap['days']}
        for day_number in (1, 2, 3, 6):
            self.assertFalse(by_day[day_number]['is_rest'])
            self.assertIsNotNone(by_day[day_number]['workout'])
        for day_number in (4, 5, 7):
            self.assertTrue(by_day[day_number]['is_rest'])


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
            goal_weight_kg=75, height_cm=178, age=30, sex='MALE', start_date=date(2024, 1, 1),
        ))
        self.assertEqual(len(roadmap['days']), 60)
        self.assertEqual(roadmap['meal_template'], blueprint.meal_templates)
        # Spec v1.6 section 6.5: a 60-day plan -> phase boundaries 18/42/60 exactly.
        self.assertEqual(
            [(p['name'], p['start_day'], p['end_day']) for p in roadmap['phases']],
            [('Foundation', 1, 18), ('Build', 19, 42), ('Peak', 43, 60)],
        )


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

    def test_equipment_level_defaults_to_full_gym_unchanged_behavior(self):
        # A caller that never sends equipment_level at all (every existing
        # caller, pre-this-change) must see no behavior change: full_gym is
        # approved for every split in the catalog today.
        response = self.client.post('/api/plans/preview/', self.valid_payload(), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn('code', response.data)

    # --- Gap 1: overrides reachable via HTTP (spec v1.6 section 4.8) -------

    def test_calorie_override_changes_target_calories_in_preview(self):
        baseline = self.client.post('/api/plans/preview/', self.valid_payload(), format='json')
        self.assertEqual(baseline.status_code, 200, baseline.data)
        self.assertNotEqual(baseline.data['engine']['target_calories'], 2300)

        response = self.client.post(
            '/api/plans/preview/',
            self.valid_payload(calorie_override=2300, override_for_mode='CUT'),
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        engine = response.data['engine']
        self.assertEqual(engine['target_calories'], 2300)
        self.assertEqual(engine['override_source'], 'calories')
        self.assertIsNotNone(engine['suggested_calories'])
        self.assertNotEqual(engine['suggested_calories'], 2300)

    def test_macro_override_preserves_exact_grams(self):
        response = self.client.post(
            '/api/plans/preview/',
            self.valid_payload(
                macro_override={'protein_g': 160, 'fat_g': 61, 'carbs_g': 250},
                override_for_mode='CUT',
            ),
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        engine = response.data['engine']
        self.assertEqual(engine['override_source'], 'macros')
        self.assertEqual(engine['target_protein_g'], 160)
        self.assertEqual(engine['target_fat_g'], 61)
        self.assertEqual(engine['target_carbs_g'], 250)
        # 4.8: target_calories is the exact macro sum (4P + 4C + 9F), not
        # rounded to the nearest 10 like the non-override path.
        self.assertEqual(engine['target_calories'], 4 * 160 + 4 * 250 + 9 * 61)
        self.assertIsNotNone(engine['suggested_macros'])

    def test_override_conflict_blocks_preview_and_create_with_422(self):
        payload = self.valid_payload(
            calorie_override=2300,
            macro_override={'protein_g': 160, 'fat_g': 61, 'carbs_g': 250},
            override_for_mode='CUT',
        )
        preview = self.client.post('/api/plans/preview/', payload, format='json')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data['engine']['can_start'])
        preview_codes = {m['code'] for m in preview.data['engine']['messages']}
        self.assertIn('OVERRIDE_CONFLICT', preview_codes)

        create = self.client.post('/api/plans/', payload, format='json')
        self.assertEqual(create.status_code, 422, create.data)
        self.assertEqual(create.data['code'], 'OVERRIDE_CONFLICT')
        self.assertFalse(create.data['can_start'])
        self.assertEqual(JourneyProgram.objects.filter(user=self.user).count(), 0)

    def test_override_mode_required_blocks_preview_and_create_with_422(self):
        payload = self.valid_payload(calorie_override=2300)  # no override_for_mode
        preview = self.client.post('/api/plans/preview/', payload, format='json')
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data['engine']['can_start'])
        preview_codes = {m['code'] for m in preview.data['engine']['messages']}
        self.assertIn('OVERRIDE_MODE_REQUIRED', preview_codes)

        create = self.client.post('/api/plans/', payload, format='json')
        self.assertEqual(create.status_code, 422, create.data)
        self.assertEqual(create.data['code'], 'OVERRIDE_MODE_REQUIRED')
        self.assertEqual(JourneyProgram.objects.filter(user=self.user).count(), 0)

    def test_create_persists_calorie_override_onto_journey_program(self):
        payload = self.valid_payload(calorie_override=2300, override_for_mode='CUT')
        response = self.client.post('/api/plans/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        program = JourneyProgram.objects.get(user=self.user, active=True)
        self.assertEqual(program.calorie_override, 2300)
        self.assertIsNone(program.macro_override_protein_g)
        self.assertEqual(program.target_calories, 2300)

    def test_create_persists_macro_override_onto_journey_program(self):
        payload = self.valid_payload(
            macro_override={'protein_g': 160, 'fat_g': 61, 'carbs_g': 250},
            override_for_mode='CUT',
        )
        response = self.client.post('/api/plans/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        program = JourneyProgram.objects.get(user=self.user, active=True)
        self.assertIsNone(program.calorie_override)
        self.assertEqual(program.macro_override_protein_g, 160)
        self.assertEqual(program.macro_override_fat_g, 61)
        self.assertEqual(program.macro_override_carbs_g, 250)

    # --- Gap 2: experience/equipment reach the engine (spec v1.6 6.2, V-15) -

    def test_beginner_high_frequency_message_reaches_http_preview(self):
        # Before this pass, engine_adapter.build_plan_inputs hardcoded
        # Experience.INTERMEDIATE regardless of the request, so
        # BEGINNER_HIGH_FREQUENCY (V-15, beginner + 5-6 days/week) could
        # never fire through this endpoint no matter what the client sent.
        payload = self.valid_payload(
            duration_days=60, days_per_week=6, weekdays=[1, 2, 3, 4, 5, 6],
            experience='BEGINNER',
        )
        response = self.client.post('/api/plans/preview/', payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        codes = {m['code'] for m in response.data['engine']['messages']}
        self.assertIn('BEGINNER_HIGH_FREQUENCY', codes)

    def test_intermediate_high_frequency_does_not_get_beginner_message(self):
        payload = self.valid_payload(
            duration_days=60, days_per_week=6, weekdays=[1, 2, 3, 4, 5, 6],
            experience='INTERMEDIATE',
        )
        response = self.client.post('/api/plans/preview/', payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        codes = {m['code'] for m in response.data['engine']['messages']}
        self.assertNotIn('BEGINNER_HIGH_FREQUENCY', codes)

    # --- Gap 3: recomp_direction reaches the engine (spec v1.6 4.3) --------

    def test_recomp_direction_changes_calorie_target(self):
        base = dict(
            blueprint_slug='recomp-45', duration_days=45, days_per_week=4,
            weekdays=[1, 2, 4, 6], current_weight_kg=76.3, height_cm=174,
            age=30, sex='MALE',
        )
        lean_out = self.client.post(
            '/api/plans/preview/', {**base, 'recomp_direction': 'lean_out'}, format='json'
        )
        lean_gain = self.client.post(
            '/api/plans/preview/', {**base, 'recomp_direction': 'lean_gain'}, format='json'
        )
        self.assertEqual(lean_out.status_code, 200, lean_out.data)
        self.assertEqual(lean_gain.status_code, 200, lean_gain.data)
        self.assertNotEqual(
            lean_out.data['engine']['target_calories'], lean_gain.data['engine']['target_calories']
        )
        # lean_gain is a 5% surplus over TDEE (4.3), lean_out a 5% deficit --
        # the engine must not have silently defaulted both to lean_out.
        self.assertGreater(
            lean_gain.data['engine']['target_calories'], lean_out.data['engine']['target_calories']
        )

    # --- Gap 4: full PlanTargets shape forwarded to the client (spec 7.1) --

    def test_preview_engine_metadata_carries_full_plan_targets_shape(self):
        response = self.client.post('/api/plans/preview/', self.valid_payload(), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        engine = response.data['engine']
        for key in (
            'bmr', 'tdee', 'calorie_delta', 'predicted_total_change_kg',
            'projected_end_weight_kg', 'weekly_change_pct_bodyweight',
            'requested_weekly_change_pct', 'days_needed', 'override_source',
            'suggested_calories', 'suggested_macros',
        ):
            self.assertIn(key, engine)
        self.assertIsNotNone(engine['bmr'])
        self.assertIsNotNone(engine['tdee'])
        self.assertIsNotNone(engine['calorie_delta'])
        self.assertIsNotNone(engine['predicted_total_change_kg'])
        self.assertIsNotNone(engine['projected_end_weight_kg'])
        self.assertIsNotNone(engine['weekly_change_pct_bodyweight'])
        self.assertIsNotNone(engine['requested_weekly_change_pct'])
        # A Cut plan with a goal weight reachable within the window should
        # show a concrete "N days needed" the Review screen can render.
        self.assertIsNotNone(engine['days_needed'])
        self.assertIsNone(engine['override_source'])


class PlanOptionsApiTests(TestCase):
    """`/api/plans/options/`: "choose from multiple" -- one full preview per
    approved (days_per_week, split) combination, instead of `preview`'s
    single first-match blueprint/split."""

    def setUp(self):
        self.user = User.objects.create_user(email='options@example.com', username='optionsuser', password='testpassword123')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        from django.core.management import call_command
        call_command('seed_blueprints')
        call_command('seed_training_splits')

    def valid_payload(self, **overrides):
        payload = dict(
            mode='CUT', duration_days=60, current_weight_kg=85, goal_weight_kg=80,
            height_cm=180, age=28, sex='MALE',
        )
        payload.update(overrides)
        return payload

    def test_full_gym_returns_one_option_per_approved_days_per_week(self):
        response = self.client.post('/api/plans/options/', self.valid_payload(), format='json')
        self.assertEqual(response.status_code, 200, response.data)
        options = response.data['options']
        # full_gym approves one split each at 3/4/5/6 days/week (split_approval.py).
        self.assertEqual({o['days_per_week'] for o in options}, {3, 4, 5, 6})
        self.assertEqual({o['split_slug'] for o in options}, {
            'full-body', 'upper-lower', 'bro-split', 'push-pull-legs',
        })
        for option in options:
            self.assertIn('summary', option)
            self.assertIn('engine', option)

    def test_minimal_equipment_excludes_bro_split(self):
        response = self.client.post(
            '/api/plans/options/', self.valid_payload(equipment_level='minimal'), format='json'
        )
        self.assertEqual(response.status_code, 200, response.data)
        slugs = {o['split_slug'] for o in response.data['options']}
        # bro-split is full_gym-only (split_approval.py decision 2).
        self.assertNotIn('bro-split', slugs)
        self.assertEqual(slugs, {'full-body', 'upper-lower', 'push-pull-legs'})

    def test_missing_goal_weight_for_cut_is_rejected(self):
        payload = self.valid_payload()
        del payload['goal_weight_kg']
        response = self.client.post('/api/plans/options/', payload, format='json')
        self.assertEqual(response.status_code, 400)

    def test_options_do_not_persist_anything(self):
        self.client.post('/api/plans/options/', self.valid_payload(), format='json')
        self.assertEqual(JourneyProgram.objects.count(), 0)


class SplitApprovalConfigTests(TestCase):
    """Spec v1.6 section 6.7 bullet 2: SPLIT_APPROVAL is the single reviewed
    release-gate config. These pin down its actual contents so a future
    change to plans/split_approval.py is a deliberate, visible edit."""

    def test_full_gym_approved_for_every_seeded_split(self):
        for days, slugs in DAYS_TO_SPLIT_SLUGS.items():
            for slug in slugs:
                self.assertTrue(
                    is_split_approved(slug, 'full_gym'),
                    f"{slug} ({days}d) should be approved at full_gym",
                )

    def test_bro_split_is_full_gym_only(self):
        self.assertTrue(is_split_approved('bro-split', 'full_gym'))
        self.assertFalse(is_split_approved('bro-split', 'home_basic'))
        self.assertFalse(is_split_approved('bro-split', 'minimal'))

    def test_other_three_splits_approved_everywhere_after_catalog_fix(self):
        for slug in ('full-body', 'upper-lower', 'push-pull-legs'):
            for level in EQUIPMENT_LEVELS:
                self.assertTrue(
                    is_split_approved(slug, level),
                    f"{slug} should be approved at {level} after the catalog gap-fill",
                )

    def test_full_body_4x_has_no_approved_combination_anywhere(self):
        # No seeded TrainingSplit row exists for it at all (out of scope for
        # this pass) -- it must never show up as approved.
        for level in EQUIPMENT_LEVELS:
            self.assertFalse(is_split_approved('full-body-4x', level))
        self.assertFalse(any(
            combo['split_slug'] == 'full-body-4x' for combo in approved_combinations()
        ))

    def test_unknown_combination_fails_closed(self):
        self.assertFalse(is_split_approved('some-made-up-split', 'full_gym'))
        self.assertFalse(is_split_approved('full-body', 'some-made-up-level'))

    def test_approved_slugs_for_matches_split_approval_table(self):
        for days in range(3, 7):
            for level in EQUIPMENT_LEVELS:
                expected = [
                    slug for slug in DAYS_TO_SPLIT_SLUGS.get(days, [])
                    if SPLIT_APPROVAL.get((slug, level), False)
                ]
                self.assertEqual(approved_slugs_for(days, level), expected)

    def test_approved_combinations_count_matches_expectation(self):
        # 3 splits approved at all 3 levels (full-body, upper-lower,
        # push-pull-legs) + bro-split approved at 1 level (full_gym only).
        self.assertEqual(len(approved_combinations()), 3 * 3 + 1)


class SplitApprovalApiTests(TestCase):
    """Spec v1.6 section 6.7 bullets 3-4 / acceptance 11.3: V-21
    NO_SUPPORTED_SPLIT and the release-gate enumeration test."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='splitgate@example.com', username='splitgate', password='testpassword123'
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        from django.core.management import call_command
        call_command('seed_blueprints')
        call_command('seed_training_splits')

    def valid_payload(self, **overrides):
        payload = dict(
            blueprint_slug='cut-60', duration_days=60, days_per_week=4, weekdays=[1, 2, 4, 6],
            current_weight_kg=85, goal_weight_kg=80, height_cm=180, age=28, sex='MALE',
        )
        payload.update(overrides)
        return payload

    def test_explicit_unapproved_split_blocks_preview_with_v21(self):
        payload = self.valid_payload(
            days_per_week=5, weekdays=[1, 2, 3, 4, 6], split_slug='bro-split', equipment_level='minimal'
        )
        response = self.client.post('/api/plans/preview/', payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['can_start'])
        self.assertEqual(response.data['code'], 'NO_SUPPORTED_SPLIT')
        self.assertIn('supported_combinations', response.data)
        self.assertGreater(len(response.data['supported_combinations']), 0)
        # Every combination the error names back must itself be approved.
        for combo in response.data['supported_combinations']:
            self.assertTrue(is_split_approved(combo['split_slug'], combo['equipment_level']))

    def test_explicit_unapproved_split_blocks_create_with_422(self):
        payload = self.valid_payload(
            days_per_week=5, weekdays=[1, 2, 3, 4, 6], split_slug='bro-split', equipment_level='home_basic'
        )
        response = self.client.post('/api/plans/', payload, format='json')
        self.assertEqual(response.status_code, 422, response.data)
        self.assertEqual(response.data['code'], 'NO_SUPPORTED_SPLIT')
        self.assertEqual(JourneyProgram.objects.count(), 0)

    def test_implicit_combination_with_no_approved_split_also_blocks(self):
        # No split_slug given at all -- the only 5-day split in the catalog
        # (bro-split) isn't approved at minimal, and there is no other
        # 5-day split to fall back to, so this combination must still block.
        payload = self.valid_payload(days_per_week=5, weekdays=[1, 2, 3, 4, 6], equipment_level='minimal')
        payload.pop('split_slug', None)
        response = self.client.post('/api/plans/preview/', payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['can_start'])
        self.assertEqual(response.data['code'], 'NO_SUPPORTED_SPLIT')

    def test_approved_split_is_not_blocked(self):
        payload = self.valid_payload(
            days_per_week=4, split_slug='upper-lower', equipment_level='minimal'
        )
        response = self.client.post('/api/plans/preview/', payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn('code', response.data)
        self.assertEqual(response.data['summary']['training_split'], 'upper-lower')

    def test_approved_split_can_be_created(self):
        payload = self.valid_payload(
            days_per_week=4, split_slug='upper-lower', equipment_level='home_basic'
        )
        response = self.client.post('/api/plans/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(JourneyProgram.objects.filter(user=self.user, active=True).count(), 1)

    def test_enumeration_every_days_and_equipment_combination(self):
        """Spec acceptance 11.3 / 6.7 bullet 4: enumerate every (days-per-week
        3-6, equipment-level) combination this release might be asked for,
        and assert the API only ever returns or accepts an approved split
        for it -- never an unapproved one, and never a silent 500/other
        failure in place of the V-21 code."""
        for days in range(3, 7):
            for level in EQUIPMENT_LEVELS:
                candidate_slugs = DAYS_TO_SPLIT_SLUGS.get(days, [])
                slug = candidate_slugs[0] if candidate_slugs else 'no-such-split'
                payload = self.valid_payload(
                    days_per_week=days, split_slug=slug, equipment_level=level,
                    weekdays=list(range(1, days + 1)),
                )
                with self.subTest(days=days, equipment_level=level, split_slug=slug):
                    response = self.client.post('/api/plans/preview/', payload, format='json')
                    self.assertEqual(response.status_code, 200, response.data)
                    approved = is_split_approved(slug, level)
                    if approved:
                        self.assertNotIn(
                            'code', response.data,
                            f"{slug}/{level} is approved but the API blocked it",
                        )
                        self.assertEqual(response.data['summary']['training_split'], slug)
                    else:
                        self.assertEqual(
                            response.data.get('code'), 'NO_SUPPORTED_SPLIT',
                            f"{slug}/{level} is NOT approved but the API let it through",
                        )
                        self.assertFalse(response.data['can_start'])


class RealWeekdayAndDateTests(TestCase):
    """Spec v1.6 section 6.6 / acceptance 11.3 ("Week 1 shows real weekdays
    and dates"): generate_roadmap anchors day_number=1 to a real calendar
    date and schedules every day onto its *actual* weekday, instead of the
    old synthetic `((day_number - 1) % 7) + 1` cycle, which had no
    relationship to any real start date at all."""

    def user_inputs(self, **overrides):
        base = dict(
            duration_days=60, days_per_week=4, weekdays=[1, 3, 5, 6],
            current_weight_kg=80, goal_weight_kg=75, height_cm=178, age=30, sex='MALE',
        )
        base.update(overrides)
        return base

    def test_default_start_date_snaps_to_first_training_weekday_on_or_after_today(self):
        blueprint = make_blueprint_stub('CUT')
        # "today" is a Wednesday (ordinal 3); training weekdays are Tue/Thu
        # (ordinal 2/4) -- neither is today, so the default start_date must
        # snap forward to the very next training weekday: Thursday.
        wednesday = date(2026, 10, 14)
        self.assertEqual(wednesday.weekday() + 1, 3)
        roadmap = generate_roadmap(
            blueprint,
            self.user_inputs(weekdays=[2, 4], days_per_week=2, duration_days=14, today=wednesday),
        )
        expected_anchor = date(2026, 10, 15)  # the following Thursday
        self.assertEqual(expected_anchor.weekday() + 1, 4)
        self.assertEqual(roadmap['summary']['start_date'], expected_anchor)
        self.assertEqual(roadmap['days'][0]['date'], expected_anchor)
        self.assertFalse(roadmap['days'][0]['is_rest'])

    def test_default_start_date_stays_put_when_today_is_already_a_training_day(self):
        blueprint = make_blueprint_stub('CUT')
        monday = date(2024, 1, 1)
        roadmap = generate_roadmap(
            blueprint,
            self.user_inputs(weekdays=[1, 3, 5], days_per_week=3, duration_days=7, today=monday),
        )
        self.assertEqual(roadmap['summary']['start_date'], monday)

    def test_explicit_mid_week_start_gives_a_shorter_first_week(self):
        blueprint = make_blueprint_stub('CUT')
        # Explicit start_date on a Wednesday, training Mon/Wed/Fri: day 1 is
        # itself mid-week (no Monday precedes it in this plan at all) --
        # exactly the "shorter first week" the spec calls out.
        wednesday = date(2026, 10, 14)
        roadmap = generate_roadmap(
            blueprint,
            self.user_inputs(weekdays=[1, 3, 5], days_per_week=3, duration_days=14, start_date=wednesday),
        )
        days = roadmap['days']
        self.assertEqual(days[0]['date'], wednesday)
        self.assertFalse(days[0]['is_rest'])   # Wed itself trains
        self.assertTrue(days[1]['is_rest'])    # Thu rests
        self.assertFalse(days[2]['is_rest'])   # Fri trains
        self.assertTrue(days[3]['is_rest'])    # Sat rests
        self.assertTrue(days[4]['is_rest'])    # Sun rests
        self.assertFalse(days[5]['is_rest'])   # Mon trains (first full week day)
        first_partial_stretch_training_days = sum(1 for d in days[:5] if not d['is_rest'])
        self.assertEqual(first_partial_stretch_training_days, 2)

    def test_last_week_may_be_partial_without_crashing(self):
        blueprint = make_blueprint_stub('CUT')
        monday = date(2024, 1, 1)
        # 10 days from a Monday ends mid-week (Wednesday) -- the last
        # stretch is partial (only Mon/Tue/Wed of what would be a full week).
        roadmap = generate_roadmap(
            blueprint,
            self.user_inputs(weekdays=[1, 3, 5], days_per_week=3, duration_days=10, start_date=monday),
        )
        self.assertEqual(len(roadmap['days']), 10)
        last_day = roadmap['days'][-1]
        expected_last_date = monday + timedelta(days=9)
        self.assertEqual(last_day['date'], expected_last_date)
        self.assertEqual(last_day['day_number'], 10)
        self.assertEqual(roadmap['phases'][-1]['end_day'], 10)
        self.assertTrue(all(p['end_day'] >= p['start_day'] for p in roadmap['phases']))

    def test_labels_carry_real_weekday_and_date(self):
        blueprint = make_blueprint_stub('CUT')
        monday = date(2024, 1, 1)
        roadmap = generate_roadmap(
            blueprint,
            self.user_inputs(weekdays=[1, 3, 5, 6], duration_days=7, start_date=monday),
        )
        first_day = roadmap['days'][0]
        self.assertEqual(first_day['weekday'], 'Mon')
        self.assertTrue(first_day['label'].startswith('Mon 1 Jan'))
        self.assertIn(':', first_day['label'])

    def test_dates_are_sequential_calendar_days_not_a_synthetic_cycle(self):
        blueprint = make_blueprint_stub('CUT')
        monday = date(2024, 1, 1)
        roadmap = generate_roadmap(
            blueprint,
            self.user_inputs(weekdays=[1, 3, 5, 6], duration_days=10, start_date=monday),
        )
        for day in roadmap['days']:
            self.assertEqual(day['date'], monday + timedelta(days=day['day_number'] - 1))


class PhaseBoundaryTests(TestCase):
    """Spec v1.6 section 6.5: `foundation_end = round_half_up(0.30 *
    duration_days)`, `build_end = round_half_up(0.70 * duration_days)`,
    computed directly from the plan's own requested duration -- not scaled
    proportionally from the blueprint's own default-duration phases, and
    never Python's banker's-rounding `round()`."""

    def user_inputs(self, **overrides):
        base = dict(
            duration_days=60, days_per_week=4, weekdays=[1, 3, 5, 6],
            current_weight_kg=80, goal_weight_kg=75, height_cm=178, age=30, sex='MALE',
            start_date=date(2024, 1, 1),
        )
        base.update(overrides)
        return base

    def test_60_day_plan_boundaries_are_18_and_42(self):
        blueprint = make_blueprint_stub('CUT')
        roadmap = generate_roadmap(blueprint, self.user_inputs(duration_days=60))
        self.assertEqual(
            [(p['start_day'], p['end_day']) for p in roadmap['phases']],
            [(1, 18), (19, 42), (43, 60)],
        )

    def test_45_day_plan_boundaries_use_round_half_up(self):
        # round_half_up(0.30*45) = round_half_up(13.5) = 14 (ties away from
        # zero); round_half_up(0.70*45) = round_half_up(31.5) = 32 -- a case
        # Python's round() (banker's rounding) would get wrong (13, 32).
        blueprint = make_blueprint_stub('CUT', duration_days=45)
        roadmap = generate_roadmap(blueprint, self.user_inputs(duration_days=45))
        self.assertEqual(
            [(p['start_day'], p['end_day']) for p in roadmap['phases']],
            [(1, 14), (15, 32), (33, 45)],
        )

    def test_phase_boundaries_use_the_requested_duration_not_the_blueprint_default(self):
        # The stub blueprint's own `phases` are computed for its 60-day
        # default (18/42/60); requesting a 10-day plan must give 10-day-
        # correct boundaries, not a naive scale-down of the stale ones.
        blueprint = make_blueprint_stub('CUT')  # default_duration_days=60 inside the stub
        roadmap = generate_roadmap(blueprint, self.user_inputs(duration_days=10))
        self.assertEqual(
            [(p['start_day'], p['end_day']) for p in roadmap['phases']],
            [(1, 3), (4, 7), (8, 10)],
        )

    def test_short_duration_phases_are_never_negative_length(self):
        blueprint = make_blueprint_stub('CUT')
        roadmap = generate_roadmap(blueprint, self.user_inputs(duration_days=7))
        for phase in roadmap['phases']:
            self.assertGreaterEqual(phase['end_day'], phase['start_day'])
        self.assertEqual(roadmap['phases'][-1]['end_day'], 7)

    def test_phases_carry_a_plain_description(self):
        blueprint = make_blueprint_stub('CUT')
        roadmap = generate_roadmap(blueprint, self.user_inputs(duration_days=60))
        for phase in roadmap['phases']:
            self.assertTrue(phase['description'])


class ExerciseLookupTests(TestCase):
    """`.exercise_lookup` is the one place that bridges the real Exercise
    catalog into `generate_roadmap`'s (otherwise pure) volume check."""

    def setUp(self):
        from django.core.management import call_command
        call_command('seed_exercises')

    def test_resolves_known_catalog_names(self):
        names = exercise_names_in_workout_templates({
            'day_1': [{'exercise_name': 'Barbell Back Squat', 'sets': 4}],
            'day_2': [],
        })
        self.assertEqual(names, {'Barbell Back Squat'})
        mapping = muscle_group_by_exercise_name(names)
        self.assertEqual(mapping.get('Barbell Back Squat'), 'Quadriceps')

    def test_unknown_name_is_simply_absent_not_an_error(self):
        mapping = muscle_group_by_exercise_name({'Not A Real Exercise'})
        self.assertEqual(mapping, {})

    def test_empty_input_short_circuits(self):
        self.assertEqual(muscle_group_by_exercise_name(set()), {})


class VolumeCheckTests(TestCase):
    """Spec v1.6 section 6.4: detect-and-warn only (no auto-fix). Uses a
    controlled fake muscle_group_by_exercise mapping, independent of the
    real Exercise catalog, to pin down the range-comparison logic itself;
    the real-catalog, DB-backed sweep across every approved split lives in
    VolumeCheckEnumerationTests (acceptance 11.3)."""

    MUSCLE_MAP = {
        'Chest Press': 'Chest', 'Chest Fly': 'Chest',
        'Back Row': 'Back', 'Back Pulldown': 'Back',
        'Shoulder Press': 'Shoulders', 'Shoulder Raise': 'Shoulders',
    }

    def _blueprint(self):
        def ex(name, sets):
            return {'exercise_name': name, 'sets': sets, 'reps': '8-10', 'rpe': 7.5,
                    'rest_seconds': 90, 'progression_rule': ''}

        return SimpleNamespace(
            mode='CUT',
            default_duration_days=21,
            default_days_per_week=3,
            default_training_split=None,
            phases=[
                {'name': 'Foundation', 'start_day': 1, 'end_day': 6},
                {'name': 'Build', 'start_day': 7, 'end_day': 15},
                {'name': 'Peak', 'start_day': 16, 'end_day': 21},
            ],
            workout_templates={
                'day_1': [ex('Chest Press', 4), ex('Back Row', 5)],
                'day_2': [],
                'day_3': [ex('Chest Fly', 3), ex('Shoulder Press', 7)],
                'day_4': [],
                'day_5': [ex('Back Pulldown', 5), ex('Shoulder Raise', 6)],
                'day_6': [],
                'day_7': [],
            },
            meal_templates={},
        )

    def _roadmap(self, experience, muscle_map=MUSCLE_MAP):
        blueprint = self._blueprint()
        user_inputs = dict(
            duration_days=21, days_per_week=3, weekdays=[1, 3, 5],
            current_weight_kg=80, goal_weight_kg=78, height_cm=178, age=30, sex='MALE',
            start_date=date(2024, 1, 1), experience=experience,
        )
        return generate_roadmap(blueprint, user_inputs, muscle_group_by_exercise=muscle_map)

    def test_below_minimum_is_flagged(self):
        # Chest: 4 + 3 = 7 sets/week, below the Beginner minimum of 8.
        roadmap = self._roadmap('BEGINNER')
        self.assertEqual(roadmap['volume']['weekly_sets_by_muscle_group']['Chest'], 7)
        flagged = {m['params']['muscle_group']: m for m in roadmap['volume']['messages']}
        self.assertIn('Chest', flagged)
        self.assertEqual(flagged['Chest']['code'], VOLUME_OUTSIDE_RANGE_CODE)
        self.assertEqual(flagged['Chest']['severity'], 'info')
        self.assertTrue(any('Chest' in w for w in roadmap['warnings']))

    def test_within_range_is_not_flagged(self):
        # Back: 5 + 5 = 10 sets/week, inside the Beginner range (8-12).
        roadmap = self._roadmap('BEGINNER')
        self.assertEqual(roadmap['volume']['weekly_sets_by_muscle_group']['Back'], 10)
        flagged_groups = {m['params']['muscle_group'] for m in roadmap['volume']['messages']}
        self.assertNotIn('Back', flagged_groups)

    def test_above_maximum_is_flagged(self):
        # Shoulders: 7 + 6 = 13 sets/week, above the Beginner maximum of 12.
        roadmap = self._roadmap('BEGINNER')
        self.assertEqual(roadmap['volume']['weekly_sets_by_muscle_group']['Shoulders'], 13)
        flagged_groups = {m['params']['muscle_group'] for m in roadmap['volume']['messages']}
        self.assertIn('Shoulders', flagged_groups)

    def test_same_schedule_is_in_range_for_a_wider_experience_tier(self):
        # The same 13 Shoulders sets/week is inside the Advanced range (12-20).
        roadmap = self._roadmap('ADVANCED')
        flagged_groups = {m['params']['muscle_group'] for m in roadmap['volume']['messages']}
        self.assertNotIn('Shoulders', flagged_groups)

    def test_missing_muscle_group_lookup_flags_rather_than_crashes(self):
        # No muscle_group_by_exercise supplied at all (e.g. a caller that
        # hasn't wired up the exercise catalog yet) -- every programmed
        # group resolves to 0 sets and is flagged; it must never crash.
        blueprint = self._blueprint()
        user_inputs = dict(
            duration_days=21, days_per_week=3, weekdays=[1, 3, 5],
            current_weight_kg=80, goal_weight_kg=78, height_cm=178, age=30, sex='MALE',
            start_date=date(2024, 1, 1),
        )
        roadmap = generate_roadmap(blueprint, user_inputs)
        self.assertEqual(roadmap['volume']['weekly_sets_by_muscle_group'], {})
        self.assertEqual(len(roadmap['volume']['messages']), len(MAJOR_MUSCLE_GROUPS))


class VolumeCheckEnumerationTests(TestCase):
    """Spec v1.6 acceptance 11.3: for every (days 3-6, experience,
    equipment) combination keyed through the SPLIT_APPROVAL release gate,
    the generated plan either stays inside the 6.4 volume ranges for every
    muscle group or emits an info VOLUME_OUTSIDE_RANGE message -- it must
    never silently produce an out-of-range result with no message.
    Combinations with no approved split (NO_SUPPORTED_SPLIT, V-21) are
    skipped here; they already have dedicated coverage in
    SplitApprovalApiTests."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='volumecheck@example.com', username='volumecheck', password='testpassword123'
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        from django.core.management import call_command
        call_command('seed_exercises')
        call_command('seed_blueprints')
        call_command('seed_training_splits')

    def test_every_approved_combination_is_in_range_or_flagged(self):
        experiences = ('BEGINNER', 'INTERMEDIATE', 'ADVANCED')
        equipment_levels = ('full_gym', 'home_basic', 'minimal')
        in_range_count = 0
        flagged_count = 0
        approved_pairs = 0
        skipped_pairs = 0

        for days in range(3, 7):
            slugs = DAYS_TO_SPLIT_SLUGS.get(days, [])
            for slug in slugs:
                for level in equipment_levels:
                    if not is_split_approved(slug, level):
                        skipped_pairs += 1
                        continue
                    approved_pairs += 1
                    for experience in experiences:
                        payload = dict(
                            mode='CUT', duration_days=90, days_per_week=days,
                            weekdays=list(range(1, days + 1)), split_slug=slug,
                            equipment_level=level, experience=experience,
                            current_weight_kg=85, goal_weight_kg=80, height_cm=180,
                            age=28, sex='MALE',
                        )
                        with self.subTest(days=days, split=slug, equipment=level, experience=experience):
                            response = self.client.post('/api/plans/preview/', payload, format='json')
                            self.assertEqual(response.status_code, 200, response.data)
                            self.assertNotIn('code', response.data)  # approved -> never V-21
                            volume = response.data['volume']
                            self.assertEqual(volume['experience'], experience)
                            low, high = EXPERIENCE_VOLUME_RANGES[experience]
                            totals = volume['weekly_sets_by_muscle_group']
                            messages = volume['messages']
                            flagged_groups = {m['params']['muscle_group'] for m in messages}
                            for group in MAJOR_MUSCLE_GROUPS:
                                sets = totals.get(group, 0)
                                if not (low <= sets <= high):
                                    self.assertIn(
                                        group, flagged_groups,
                                        f"{slug}/{level}/{experience}: {group} has {sets} sets "
                                        f"(range {low}-{high}) but no VOLUME_OUTSIDE_RANGE message",
                                    )
                            for message in messages:
                                self.assertEqual(message['code'], VOLUME_OUTSIDE_RANGE_CODE)
                                self.assertEqual(message['severity'], 'info')
                            if messages:
                                flagged_count += 1
                            else:
                                in_range_count += 1

        # bro-split (5 days/week) is approved only at full_gym -- its
        # home_basic/minimal pairs are the only unapproved ones today.
        self.assertEqual(skipped_pairs, 2)
        self.assertEqual(approved_pairs, 10)
        self.assertEqual(in_range_count + flagged_count, approved_pairs * len(experiences))
