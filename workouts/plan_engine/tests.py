"""Tests for the plan_engine package (spec section 10).

This module is plain ``unittest`` and imports nothing from Django. It is
importable and runnable completely standalone, e.g.:

    cd backend && python -m unittest workouts.plan_engine.tests -v

It is also discovered and run by ``python manage.py test workouts`` like
any other app test module.

Scope note: V-11 (CONSECUTIVE_DAYS), V-15 (BEGINNER_HIGH_FREQUENCY) and
V-16 (CUT_HIGH_FREQUENCY_RECOVERY) are implemented below (Phase 2) -- they
only need fields already on ``PlanInputs`` (training_weekdays, experience,
days_per_week, mode, pace), not actual split/schedule generation from
section 6. V-21 (NO_SUPPORTED_SPLIT) remains out of scope -- it genuinely
depends on the audit-gated split generator. V-17 does not apply (decision
D2: 18+ only).
"""

import math
import unittest

from . import config
from .domain import (
    Equipment,
    Experience,
    MacroOverride,
    Mode,
    PlanInputs,
    RecompDirection,
)
from .engine import compute_plan_targets
from .rounding import round_half_up
from .serialization import serialize_plan_targets


def make_inputs(**overrides):
    """Common profile per spec section 10: male, 30, 174cm, 76.3kg, 4
    days/week (activity factor 1.55). BMR 1705.5, TDEE 2643.525."""
    defaults = dict(
        mode=Mode.CUT,
        sex="male",
        age=30,
        height_cm=174,
        weight_kg=76.3,
        goal_weight_kg=None,
        duration_days=60,
        days_per_week=4,
        training_weekdays=[0, 1, 3, 5],
        experience=Experience.INTERMEDIATE,
        equipment=Equipment.FULL_GYM,
        recomp_direction=None,
        calorie_override=None,
        macro_override=None,
        override_for_mode=None,
        split_id=None,
    )
    defaults.update(overrides)
    return PlanInputs(**defaults)


def codes(result):
    return {m.code for m in result.messages}


def severity_of(result, code):
    for m in result.messages:
        if m.code == code:
            return m.severity
    return None


class RoundHalfUpTests(unittest.TestCase):
    """Case M: exact values from the spec, and the built-in round()
    contrast it calls out."""

    def test_case_m_exact_values(self):
        self.assertEqual(round_half_up(2.5), 3)
        self.assertEqual(round_half_up(1704.5), 1705)
        self.assertEqual(round_half_up(2645, step=10), 2650)

    def test_builtin_round_would_differ(self):
        # Spec: "Python's built-in round gives 2, 1704 and 2640".
        self.assertEqual(round(2.5), 2)
        self.assertEqual(round(1704.5), 1704)
        self.assertEqual(round(2645 / 10) * 10, 2640)

    def test_negative_and_non_half_values(self):
        self.assertEqual(round_half_up(-133.525), -134)
        self.assertEqual(round_half_up(3.4), 3)
        self.assertEqual(round_half_up(3.6), 4)

    def test_step_rounding(self):
        self.assertEqual(round_half_up(2091.69, step=10), 2090)
        self.assertEqual(round_half_up(2644.99, step=10), 2640)


class CaseATests(unittest.TestCase):
    """Case A: Cut, 60 days, goal 72.0."""

    def setUp(self):
        self.inputs = make_inputs(mode=Mode.CUT, goal_weight_kg=72.0, duration_days=60)
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_bmr_and_tdee(self):
        self.assertAlmostEqual(self.result.bmr, 1705.5, places=6)
        self.assertAlmostEqual(self.result.tdee, 2643.525, places=6)

    def test_target_and_delta(self):
        self.assertEqual(self.serialized["target_calories"], 2090)
        self.assertEqual(self.serialized["calorie_delta"], -554)

    def test_weekly_and_total_change(self):
        self.assertAlmostEqual(self.serialized["predicted_weekly_change_kg"], -0.503, places=3)
        self.assertAlmostEqual(self.serialized["predicted_total_change_kg"], -4.313, places=3)
        self.assertAlmostEqual(round(self.serialized["predicted_total_change_kg"], 1), -4.3)

    def test_end_weight(self):
        self.assertAlmostEqual(self.serialized["projected_end_weight_kg"], 71.987, places=3)
        self.assertAlmostEqual(round(self.serialized["projected_end_weight_kg"], 1), 72.0)

    def test_pace(self):
        self.assertAlmostEqual(self.serialized["weekly_change_pct_bodyweight"], 0.66, places=2)
        self.assertEqual(self.result.pace_status, "typical")

    def test_macros(self):
        m = self.serialized["macros"]
        self.assertEqual(m, {"protein_g": 153, "fat_g": 58, "carbs_g": 239})

    def test_no_messages_and_can_start(self):
        self.assertEqual(self.result.messages, [])
        self.assertTrue(self.result.can_start)


class CaseBTests(unittest.TestCase):
    """Case B: Cut, goal blank."""

    def test_blocked_and_no_pace_shown(self):
        inputs = make_inputs(mode=Mode.CUT, goal_weight_kg=None, duration_days=60)
        result = compute_plan_targets(inputs)
        self.assertFalse(result.can_start)
        self.assertIn("GOAL_WEIGHT_REQUIRED", codes(result))
        self.assertEqual(severity_of(result, "GOAL_WEIGHT_REQUIRED"), "block")
        # "no pace shown anywhere"
        self.assertIsNone(result.predicted_weekly_change_kg)
        self.assertIsNone(result.predicted_total_change_kg)
        self.assertIsNone(result.projected_end_weight_kg)
        self.assertIsNone(result.weekly_change_pct_bodyweight)
        self.assertIsNone(result.requested_weekly_change_pct)
        self.assertIsNone(result.days_needed)
        self.assertEqual(result.pace_status, "not_applicable")


class CaseCTests(unittest.TestCase):
    """Case C: Cut, 60 days, goal 68.0 -> aggressive but not blocked."""

    def setUp(self):
        self.inputs = make_inputs(mode=Mode.CUT, goal_weight_kg=68.0, duration_days=60)
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_values(self):
        self.assertEqual(self.serialized["target_calories"], 1580)
        self.assertAlmostEqual(self.serialized["predicted_weekly_change_kg"], -0.967, places=3)
        self.assertAlmostEqual(self.serialized["projected_end_weight_kg"], 68.013, places=3)
        self.assertAlmostEqual(self.serialized["weekly_change_pct_bodyweight"], 1.27, places=2)

    def test_pace_aggressive_warn_with_extend(self):
        self.assertEqual(self.result.pace_status, "aggressive")
        self.assertEqual(severity_of(self.result, "PACE_AGGRESSIVE"), "warn")
        msg = next(m for m in self.result.messages if m.code == "PACE_AGGRESSIVE")
        self.assertIn("extend_to_days", msg.params)

    def test_can_start_true(self):
        self.assertTrue(self.result.can_start)


class CaseDTests(unittest.TestCase):
    """Case D: Cut, 60 days, goal 65.0, D1 = block (the actual decision)."""

    def setUp(self):
        self.inputs = make_inputs(mode=Mode.CUT, goal_weight_kg=65.0, duration_days=60)
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_requested_pace(self):
        self.assertAlmostEqual(self.serialized["requested_weekly_change_pct"], 1.73, places=2)

    def test_blocked_with_extend_104(self):
        self.assertEqual(severity_of(self.result, "PACE_ABOVE_LIMIT"), "block")
        msg = next(m for m in self.result.messages if m.code == "PACE_ABOVE_LIMIT")
        self.assertEqual(msg.params["extend_to_days"], 104)
        self.assertFalse(self.result.can_start)


class CaseDPrimeTests(unittest.TestCase):
    """Case D': same as D, but exercising the D1 = warn branch.

    D1 is a config constant (PACE_HARD_LIMIT_MODE); the shipped decision is
    "block" (see config.py), so this test temporarily monkeypatches the
    constant to exercise the alternate, specified behaviour, then restores
    it -- this is the only way to cover this documented branch without
    shipping the "warn" option as the default.
    """

    def setUp(self):
        self._original_mode = config.PACE_HARD_LIMIT_MODE
        config.PACE_HARD_LIMIT_MODE = "warn"
        self.inputs = make_inputs(mode=Mode.CUT, goal_weight_kg=65.0, duration_days=60)
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def tearDown(self):
        config.PACE_HARD_LIMIT_MODE = self._original_mode

    def test_requested_pace_triggers_warn_not_block(self):
        self.assertAlmostEqual(self.serialized["requested_weekly_change_pct"], 1.73, places=2)
        self.assertEqual(severity_of(self.result, "PACE_ABOVE_LIMIT"), "warn")

    def test_clamped_to_floor_and_final_values(self):
        self.assertTrue(self.result.calories_clamped)
        self.assertEqual(self.serialized["target_calories"], 1500)
        self.assertEqual(self.serialized["calorie_delta"], -1144)
        self.assertAlmostEqual(self.serialized["predicted_weekly_change_kg"], -1.040, places=3)
        self.assertAlmostEqual(self.serialized["projected_end_weight_kg"], 67.389, places=3)
        self.assertAlmostEqual(self.serialized["weekly_change_pct_bodyweight"], 1.36, places=2)

    def test_macros(self):
        self.assertEqual(
            self.serialized["macros"], {"protein_g": 153, "fat_g": 42, "carbs_g": 128}
        )

    def test_messages_and_days_needed(self):
        self.assertIn("CALORIES_RAISED_TO_FLOOR", codes(self.result))
        self.assertIn("GOAL_NOT_REACHED_IN_TIME", codes(self.result))
        self.assertEqual(self.result.days_needed, 77)
        # V-08 must not fire alongside V-07 (same underlying pace issue).
        self.assertNotIn("PACE_AGGRESSIVE", codes(self.result))

    def test_can_start_true(self):
        self.assertTrue(self.result.can_start)

    def test_clamp_consistency_property(self):
        """Clamp-consistency property, explicitly for case D' (section 10):
        predicted fields/macros are derived fresh from the FINAL
        target_calories and full-precision tdee, never the requested goal.
        """
        tc = self.result.target_calories
        tdee = self.result.tdee
        weekly = (tc - tdee) * 7 / config.ENERGY_KCAL_PER_KG
        total = weekly * self.inputs.duration_days / 7
        end = self.inputs.weight_kg + total
        self.assertAlmostEqual(self.result.predicted_weekly_change_kg, weekly, places=9)
        self.assertAlmostEqual(self.result.predicted_total_change_kg, total, places=9)
        self.assertAlmostEqual(self.result.projected_end_weight_kg, end, places=9)


class CaseETests(unittest.TestCase):
    """Case E: female, 35, 165cm, 62kg, 3 days, Cut 56 days, goal 56.0."""

    def setUp(self):
        self.inputs = make_inputs(
            mode=Mode.CUT,
            sex="female",
            age=35,
            height_cm=165,
            weight_kg=62,
            goal_weight_kg=56.0,
            duration_days=56,
            days_per_week=3,
            training_weekdays=[0, 2, 4],
        )
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_bmr_and_tdee(self):
        self.assertAlmostEqual(self.result.bmr, 1315.25, places=6)
        self.assertEqual(self.serialized["tdee"], 1973)

    def test_clamped_to_female_floor(self):
        self.assertTrue(self.result.calories_clamped)
        self.assertEqual(self.serialized["target_calories"], 1200)
        self.assertIn("CALORIES_RAISED_TO_FLOOR", codes(self.result))

    def test_weekly_and_end_weight(self):
        self.assertAlmostEqual(self.serialized["predicted_weekly_change_kg"], -0.703, places=3)
        self.assertAlmostEqual(self.serialized["projected_end_weight_kg"], 56.379, places=3)
        self.assertAlmostEqual(round(self.serialized["projected_end_weight_kg"], 1), 56.4)

    def test_pace_aggressive(self):
        self.assertAlmostEqual(self.serialized["weekly_change_pct_bodyweight"], 1.13, places=2)
        self.assertEqual(self.result.pace_status, "aggressive")

    def test_goal_not_reached_and_days_needed(self):
        self.assertIn("GOAL_NOT_REACHED_IN_TIME", codes(self.result))
        self.assertEqual(self.result.days_needed, 60)

    def test_clamp_consistency_property(self):
        tc = self.result.target_calories
        tdee = self.result.tdee
        weekly = (tc - tdee) * 7 / config.ENERGY_KCAL_PER_KG
        total = weekly * self.inputs.duration_days / 7
        end = self.inputs.weight_kg + total
        self.assertAlmostEqual(self.result.predicted_weekly_change_kg, weekly, places=9)
        self.assertAlmostEqual(self.result.predicted_total_change_kg, total, places=9)
        self.assertAlmostEqual(self.result.projected_end_weight_kg, end, places=9)


class CaseFTests(unittest.TestCase):
    """Case F: Recomp, lean_out, no goal."""

    def setUp(self):
        self.inputs = make_inputs(
            mode=Mode.RECOMP,
            goal_weight_kg=None,
            recomp_direction=RecompDirection.LEAN_OUT,
        )
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_target_and_delta(self):
        self.assertEqual(self.serialized["target_calories"], 2510)
        self.assertEqual(self.serialized["calorie_delta"], -134)

    def test_precision_and_predicted_null(self):
        self.assertEqual(self.result.precision, "directional")
        self.assertIsNone(self.result.predicted_weekly_change_kg)
        self.assertIsNone(self.result.predicted_total_change_kg)
        self.assertIsNone(self.result.projected_end_weight_kg)
        self.assertIsNone(self.result.weekly_change_pct_bodyweight)
        self.assertIsNone(self.result.days_needed)
        self.assertEqual(self.result.pace_status, "not_applicable")

    def test_macros(self):
        self.assertEqual(
            self.serialized["macros"], {"protein_g": 153, "fat_g": 70, "carbs_g": 317}
        )


class CaseGTests(unittest.TestCase):
    """Case G: Focus, no goal."""

    def setUp(self):
        self.inputs = make_inputs(mode=Mode.FOCUS, goal_weight_kg=None)
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_target(self):
        self.assertEqual(self.serialized["target_calories"], 2640)

    def test_precision_and_predicted_null(self):
        self.assertEqual(self.result.precision, "maintenance")
        self.assertIsNone(self.result.predicted_weekly_change_kg)
        self.assertIsNone(self.result.projected_end_weight_kg)
        self.assertIsNone(self.result.days_needed)

    def test_macros(self):
        self.assertEqual(
            self.serialized["macros"], {"protein_g": 122, "fat_g": 73, "carbs_g": 374}
        )


class CaseGHabitTests(unittest.TestCase):
    """Habit twin of Case G: same profile/inputs as Case G (Focus, no goal)
    but mode=Habit. Habit shares Focus's formula exactly (same maintenance
    target, same precision, same null predicted fields, same protein g/kg),
    so every field must match Case G's result byte-for-byte except ``mode``
    itself (which must round-trip as Mode.HABIT, not silently become Focus)."""

    def setUp(self):
        self.focus_inputs = make_inputs(mode=Mode.FOCUS, goal_weight_kg=None)
        self.habit_inputs = make_inputs(mode=Mode.HABIT, goal_weight_kg=None)
        self.focus_result = compute_plan_targets(self.focus_inputs)
        self.habit_result = compute_plan_targets(self.habit_inputs)
        self.focus_serialized = serialize_plan_targets(self.focus_result)
        self.habit_serialized = serialize_plan_targets(self.habit_result)

    def test_mode_round_trips_as_habit_not_focus(self):
        self.assertEqual(self.habit_inputs.mode, Mode.HABIT)
        self.assertNotEqual(self.habit_inputs.mode, Mode.FOCUS)

    def test_target(self):
        self.assertEqual(self.habit_serialized["target_calories"], 2640)

    def test_precision_and_predicted_null(self):
        self.assertEqual(self.habit_result.precision, "maintenance")
        self.assertIsNone(self.habit_result.predicted_weekly_change_kg)
        self.assertIsNone(self.habit_result.projected_end_weight_kg)
        self.assertIsNone(self.habit_result.days_needed)

    def test_macros(self):
        self.assertEqual(
            self.habit_serialized["macros"], {"protein_g": 122, "fat_g": 73, "carbs_g": 374}
        )

    def test_identical_to_focus_except_mode_field(self):
        # Compare every serialized field except the fields that legitimately
        # differ only because `mode` itself differs downstream of the
        # engine (none currently do -- this is the numeric-identity check
        # the product owner asked for).
        for key in self.focus_serialized:
            self.assertEqual(
                self.habit_serialized[key],
                self.focus_serialized[key],
                msg=f"Habit and Focus diverged unexpectedly on {key!r}",
            )


class CaseHTests(unittest.TestCase):
    """Case H: Bulk, 90 days, goal 79.0."""

    def setUp(self):
        self.inputs = make_inputs(mode=Mode.BULK, goal_weight_kg=79.0, duration_days=90)
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_values(self):
        self.assertEqual(self.serialized["target_calories"], 2870)
        self.assertEqual(self.serialized["calorie_delta"], 226)
        self.assertAlmostEqual(self.serialized["predicted_weekly_change_kg"], 0.206, places=3)
        self.assertAlmostEqual(self.serialized["predicted_total_change_kg"], 2.647, places=3)
        self.assertAlmostEqual(round(self.serialized["predicted_total_change_kg"], 1), 2.6)
        self.assertAlmostEqual(self.serialized["projected_end_weight_kg"], 78.947, places=3)
        self.assertAlmostEqual(round(self.serialized["projected_end_weight_kg"], 1), 78.9)
        self.assertAlmostEqual(self.serialized["weekly_change_pct_bodyweight"], 0.27, places=2)
        self.assertEqual(self.result.pace_status, "typical")


class CaseITests(unittest.TestCase):
    """Case I: Case A with calorie_override = 2300."""

    def setUp(self):
        self.inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=2300,
            override_for_mode=Mode.CUT,
        )
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_values(self):
        self.assertEqual(self.serialized["target_calories"], 2300)
        self.assertAlmostEqual(self.serialized["predicted_weekly_change_kg"], -0.312, places=3)
        self.assertAlmostEqual(self.serialized["predicted_total_change_kg"], -2.677, places=3)
        self.assertAlmostEqual(round(self.serialized["predicted_total_change_kg"], 1), -2.7)
        self.assertAlmostEqual(self.serialized["projected_end_weight_kg"], 73.623, places=3)
        self.assertAlmostEqual(round(self.serialized["projected_end_weight_kg"], 1), 73.6)
        self.assertAlmostEqual(self.serialized["weekly_change_pct_bodyweight"], 0.41, places=2)
        self.assertEqual(self.result.pace_status, "typical")

    def test_macros(self):
        self.assertEqual(
            self.serialized["macros"], {"protein_g": 153, "fat_g": 64, "carbs_g": 278}
        )

    def test_goal_not_reached_and_days_needed(self):
        self.assertIn("GOAL_NOT_REACHED_IN_TIME", codes(self.result))
        self.assertEqual(self.result.days_needed, 97)

    def test_override_source_and_no_v07(self):
        self.assertEqual(self.result.override_source, "calories")
        self.assertNotIn("PACE_ABOVE_LIMIT", codes(self.result))


class CaseJTests(unittest.TestCase):
    """Case J: Case A, goal 80 (wrong direction for a Cut)."""

    def test_blocked_goal_direction_invalid(self):
        inputs = make_inputs(mode=Mode.CUT, goal_weight_kg=80.0, duration_days=60)
        result = compute_plan_targets(inputs)
        self.assertFalse(result.can_start)
        self.assertIn("GOAL_DIRECTION_INVALID", codes(result))
        self.assertEqual(severity_of(result, "GOAL_DIRECTION_INVALID"), "block")


class CaseKTests(unittest.TestCase):
    """Case K: Case A, goal 55.0 (height 174) -> BMI too low."""

    def test_blocked_goal_bmi_too_low(self):
        inputs = make_inputs(mode=Mode.CUT, goal_weight_kg=55.0, duration_days=60)
        result = compute_plan_targets(inputs)
        self.assertFalse(result.can_start)
        self.assertIn("GOAL_BMI_TOO_LOW", codes(result))
        msg = next(m for m in result.messages if m.code == "GOAL_BMI_TOO_LOW")
        self.assertAlmostEqual(msg.params["min_goal_weight_kg"], 56.0, places=1)


class CaseLTests(unittest.TestCase):
    """Case L: Case A with calorie_override = 1400 (below the male floor)."""

    def test_blocked_override_invalid(self):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=1400,
            override_for_mode=Mode.CUT,
        )
        result = compute_plan_targets(inputs)
        self.assertFalse(result.can_start)
        self.assertIn("OVERRIDE_INVALID", codes(result))
        self.assertEqual(severity_of(result, "OVERRIDE_INVALID"), "block")


class CaseN1N2N3Tests(unittest.TestCase):
    """N1/N2/N3: direction-check for days_needed."""

    def test_n1_override_near_tdee(self):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=2644,
            override_for_mode=Mode.CUT,
        )
        result = compute_plan_targets(inputs)
        serialized = serialize_plan_targets(result)
        self.assertAlmostEqual(serialized["predicted_weekly_change_kg"], 0.000, places=3)
        self.assertIsNone(result.days_needed)
        self.assertIn("TARGET_NOT_MOVING_TOWARD_GOAL", codes(result))
        self.assertEqual(severity_of(result, "TARGET_NOT_MOVING_TOWARD_GOAL"), "warn")

    def test_n2_surplus_on_a_cut_moves_away(self):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=2900,
            override_for_mode=Mode.CUT,
        )
        result = compute_plan_targets(inputs)
        serialized = serialize_plan_targets(result)
        self.assertAlmostEqual(serialized["predicted_weekly_change_kg"], 0.233, places=3)
        self.assertAlmostEqual(serialized["projected_end_weight_kg"], 78.299, places=3)
        self.assertIsNone(result.days_needed)
        self.assertIn("TARGET_NOT_MOVING_TOWARD_GOAL", codes(result))
        self.assertIn("GOAL_NOT_REACHED_IN_TIME", codes(result))

    def test_n3_deficit_on_a_bulk_moves_away(self):
        inputs = make_inputs(
            mode=Mode.BULK,
            goal_weight_kg=79.0,
            duration_days=90,
            calorie_override=2400,
            override_for_mode=Mode.BULK,
        )
        result = compute_plan_targets(inputs)
        serialized = serialize_plan_targets(result)
        self.assertAlmostEqual(serialized["predicted_weekly_change_kg"], -0.221, places=3)
        self.assertAlmostEqual(serialized["projected_end_weight_kg"], 73.454, places=3)
        self.assertIsNone(result.days_needed)
        self.assertIn("TARGET_NOT_MOVING_TOWARD_GOAL", codes(result))


class CaseOTests(unittest.TestCase):
    """Case O: Case A with a macro override."""

    def setUp(self):
        self.inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            macro_override=MacroOverride(protein_g=160, fat_g=61, carbs_g=250),
            override_for_mode=Mode.CUT,
        )
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_override_source_and_exact_calories(self):
        self.assertEqual(self.result.override_source, "macros")
        self.assertEqual(self.serialized["target_calories"], 2189)

    def test_macro_preservation(self):
        # The engine never replaces edited macros with recalculated ones.
        self.assertEqual(
            self.serialized["macros"], {"protein_g": 160, "fat_g": 61, "carbs_g": 250}
        )
        self.assertEqual(
            self.result.target_calories,
            4 * 160 + 4 * 250 + 9 * 61,
        )

    def test_predicted_values(self):
        self.assertAlmostEqual(self.serialized["predicted_weekly_change_kg"], -0.413, places=3)
        self.assertAlmostEqual(self.serialized["projected_end_weight_kg"], 72.758, places=3)
        self.assertAlmostEqual(self.serialized["weekly_change_pct_bodyweight"], 0.54, places=2)
        self.assertEqual(self.result.pace_status, "typical")

    def test_suggested_values(self):
        self.assertEqual(self.serialized["suggested_calories"], 2090)
        self.assertEqual(
            self.serialized["suggested_macros"],
            {"protein_g": 153, "fat_g": 58, "carbs_g": 239},
        )

    def test_days_needed_and_message(self):
        self.assertIn("GOAL_NOT_REACHED_IN_TIME", codes(self.result))
        self.assertEqual(self.result.days_needed, 73)


class CaseQTests(unittest.TestCase):
    """Case Q: Case A override made for Cut, then mode changed to Focus."""

    def setUp(self):
        self.inputs = make_inputs(
            mode=Mode.FOCUS,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=2300,
            override_for_mode=Mode.CUT,
        )
        self.result = compute_plan_targets(self.inputs)
        self.serialized = serialize_plan_targets(self.result)

    def test_maintenance_target_and_override_cleared(self):
        self.assertEqual(self.serialized["target_calories"], 2640)
        self.assertEqual(self.result.precision, "maintenance")
        self.assertIsNone(self.result.override_source)
        self.assertIsNone(self.result.suggested_calories)
        self.assertIsNone(self.result.suggested_macros)

    def test_predicted_fields_null(self):
        self.assertIsNone(self.result.predicted_weekly_change_kg)
        self.assertIsNone(self.result.projected_end_weight_kg)
        self.assertIsNone(self.result.days_needed)

    def test_override_cleared_info_message(self):
        self.assertIn("OVERRIDE_CLEARED_MODE_CHANGED", codes(self.result))
        self.assertEqual(severity_of(self.result, "OVERRIDE_CLEARED_MODE_CHANGED"), "info")


class CaseRTests(unittest.TestCase):
    """Case R: Cut inputs (goal 72.0, override 2300 for Cut), mode changed
    to Bulk. The goal is kept (not edited by the engine) and is now
    invalid for Bulk."""

    def setUp(self):
        self.inputs = make_inputs(
            mode=Mode.BULK,
            goal_weight_kg=72.0,
            duration_days=90,
            calorie_override=2300,
            override_for_mode=Mode.CUT,
        )
        self.result = compute_plan_targets(self.inputs)

    def test_override_ignored(self):
        self.assertIn("OVERRIDE_CLEARED_MODE_CHANGED", codes(self.result))
        self.assertIsNone(self.result.override_source)

    def test_goal_kept_but_now_invalid(self):
        self.assertEqual(self.inputs.goal_weight_kg, 72.0)
        self.assertIn("GOAL_DIRECTION_INVALID", codes(self.result))
        self.assertFalse(self.result.can_start)


class CaseSTests(unittest.TestCase):
    """Case S: calorie_override present, override_for_mode = null."""

    def test_blocked_override_mode_required(self):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=2300,
            override_for_mode=None,
        )
        result = compute_plan_targets(inputs)
        self.assertIn("OVERRIDE_MODE_REQUIRED", codes(result))
        self.assertEqual(severity_of(result, "OVERRIDE_MODE_REQUIRED"), "block")
        self.assertIsNone(result.override_source)
        self.assertFalse(result.can_start)
        # override not applied: falls back to the default Case A target.
        self.assertEqual(result.target_calories, 2090)


class CaseTTests(unittest.TestCase):
    """Case T: both overrides present -> OVERRIDE_CONFLICT."""

    def test_blocked_override_conflict(self):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=2300,
            macro_override=MacroOverride(protein_g=160, fat_g=61, carbs_g=250),
            override_for_mode=Mode.CUT,
        )
        result = compute_plan_targets(inputs)
        self.assertIn("OVERRIDE_CONFLICT", codes(result))
        self.assertEqual(severity_of(result, "OVERRIDE_CONFLICT"), "block")
        self.assertIsNone(result.override_source)
        self.assertFalse(result.can_start)
        self.assertEqual(result.target_calories, 2090)


class CaseUTests(unittest.TestCase):
    """Case U: calorie_override for Bulk, current mode is Cut -> stale,
    ignored, suggested targets recomputed for Cut."""

    def test_stale_override_ignored(self):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=2300,
            override_for_mode=Mode.BULK,
        )
        result = compute_plan_targets(inputs)
        self.assertIn("OVERRIDE_CLEARED_MODE_CHANGED", codes(result))
        self.assertEqual(severity_of(result, "OVERRIDE_CLEARED_MODE_CHANGED"), "info")
        self.assertIsNone(result.override_source)
        # recomputed for Cut, i.e. the normal Case A default target.
        self.assertEqual(result.target_calories, 2090)


class V18BoundaryTests(unittest.TestCase):
    """V-18 boundary tests (Case A profile, Cut, 60 days, goal 72.0)."""

    def _result(self, calorie_override):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=calorie_override,
            override_for_mode=Mode.CUT,
        )
        return compute_plan_targets(inputs)

    def test_2588_moves_toward_goal_no_v18(self):
        # Spec table says "days_needed is a number" for this row, but at
        # this rate (-0.0505 kg/week) reaching the 4.3 kg goal takes 597
        # days -- which the 4.5 365-day cap nulls independently of V-18.
        # That is a documented judgment call (see the implementation
        # report): V-18 must not fire here (the rate is >= 0.05 kg/week
        # and moving toward the goal), which is the actually-unambiguous
        # part of this boundary case; we do not assert days_needed's
        # nullness/value either way since the table and the 4.5 formula
        # disagree for this specific combination.
        result = self._result(2588)
        self.assertAlmostEqual(result.predicted_weekly_change_kg, -0.0505, places=4)
        self.assertNotIn("TARGET_NOT_MOVING_TOWARD_GOAL", codes(result))

    def test_2589_below_threshold_v18_fires(self):
        result = self._result(2589)
        self.assertAlmostEqual(result.predicted_weekly_change_kg, -0.0496, places=4)
        self.assertIn("TARGET_NOT_MOVING_TOWARD_GOAL", codes(result))
        self.assertIsNone(result.days_needed)

    def test_2644_about_zero_v18_fires(self):
        result = self._result(2644)
        self.assertIn("TARGET_NOT_MOVING_TOWARD_GOAL", codes(result))
        self.assertIsNone(result.days_needed)

    def test_2900_moves_away_v18_fires(self):
        result = self._result(2900)
        self.assertIn("TARGET_NOT_MOVING_TOWARD_GOAL", codes(result))
        self.assertIsNone(result.days_needed)


class V19BoundaryTests(unittest.TestCase):
    """V-19 boundary tests (Case A profile: weight 76.3 kg)."""

    def _result(self, protein_g, fat_g, carbs_g):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            macro_override=MacroOverride(protein_g=protein_g, fat_g=fat_g, carbs_g=carbs_g),
            override_for_mode=Mode.CUT,
        )
        return compute_plan_targets(inputs)

    def test_protein_91_warns(self):
        result = self._result(91, 60, 250)
        self.assertIn("MACROS_UNUSUAL", codes(result))

    def test_protein_92_no_warn(self):
        result = self._result(92, 60, 250)
        self.assertNotIn("MACROS_UNUSUAL", codes(result))

    def test_protein_228_no_warn(self):
        result = self._result(228, 60, 250)
        self.assertNotIn("MACROS_UNUSUAL", codes(result))

    def test_protein_229_warns(self):
        result = self._result(229, 60, 250)
        self.assertIn("MACROS_UNUSUAL", codes(result))

    def test_fat_38_warns(self):
        result = self._result(150, 38, 300)
        self.assertIn("MACROS_UNUSUAL", codes(result))

    def test_fat_39_no_warn(self):
        result = self._result(150, 39, 300)
        self.assertNotIn("MACROS_UNUSUAL", codes(result))


class PropertyTests(unittest.TestCase):
    """Property tests over a fixed, deterministic sample of valid inputs
    (the ``hypothesis`` library is not installed in this environment --
    see the implementation report)."""

    def _sample_inputs(self):
        samples = []
        for mode in (Mode.CUT, Mode.BULK, Mode.RECOMP, Mode.FOCUS):
            for sex, weight, height, age in (
                ("male", 76.3, 174, 30),
                ("female", 62.0, 165, 35),
                ("male", 95.0, 190, 45),
                ("female", 55.0, 158, 22),
            ):
                for days_per_week in (3, 4, 5, 6):
                    goal = None
                    if mode == Mode.CUT:
                        goal = weight - 6.0
                    elif mode == Mode.BULK:
                        goal = weight + 6.0
                    samples.append(
                        make_inputs(
                            mode=mode,
                            sex=sex,
                            weight_kg=weight,
                            height_cm=height,
                            age=age,
                            goal_weight_kg=goal,
                            duration_days=60,
                            days_per_week=days_per_week,
                            training_weekdays=list(range(days_per_week)),
                        )
                    )
        return samples

    def test_macro_calories_within_tolerance(self):
        for inputs in self._sample_inputs():
            result = compute_plan_targets(inputs)
            if result.target_calories is None or result.macros is None:
                continue
            m = result.macros
            macro_kcal = 4 * m.protein_g + 4 * m.carbs_g + 9 * m.fat_g
            self.assertLessEqual(
                abs(macro_kcal - result.target_calories),
                config.MACRO_CALORIE_TOLERANCE_KCAL,
                msg=f"inputs={inputs}",
            )

    def test_total_change_consistency(self):
        for inputs in self._sample_inputs():
            result = compute_plan_targets(inputs)
            if result.predicted_weekly_change_kg is None:
                continue
            expected_total = result.predicted_weekly_change_kg * inputs.duration_days / 7
            self.assertAlmostEqual(
                result.predicted_total_change_kg, expected_total, delta=0.05
            )

    def test_determinism(self):
        for inputs in self._sample_inputs():
            r1 = compute_plan_targets(inputs)
            r2 = compute_plan_targets(inputs)
            self.assertEqual(serialize_plan_targets(r1), serialize_plan_targets(r2))

    def test_preview_equals_saved(self):
        # "Preview" and "saved plan" both call compute_plan_targets() then
        # serialize_plan_targets(); calling the pipeline twice must be
        # byte-for-byte identical.
        for inputs in self._sample_inputs():
            preview = serialize_plan_targets(compute_plan_targets(inputs))
            saved = serialize_plan_targets(compute_plan_targets(inputs))
            self.assertEqual(preview, saved)

    def test_pace_never_exactly_zero_when_goal_differs(self):
        for inputs in self._sample_inputs():
            if inputs.mode not in (Mode.CUT, Mode.BULK):
                continue
            if inputs.goal_weight_kg is None:
                continue
            if inputs.goal_weight_kg == inputs.weight_kg:
                continue
            result = compute_plan_targets(inputs)
            if result.weekly_change_pct_bodyweight is None:
                continue
            self.assertNotEqual(round(result.weekly_change_pct_bodyweight, 2), 0.00)

    def test_clamp_consistency_whenever_clamped_or_overridden(self):
        extra_cases = [
            make_inputs(mode=Mode.CUT, goal_weight_kg=65.0, duration_days=60),  # D' territory
            make_inputs(
                mode=Mode.CUT,
                sex="female",
                age=35,
                height_cm=165,
                weight_kg=62,
                goal_weight_kg=56.0,
                duration_days=56,
                days_per_week=3,
                training_weekdays=[0, 2, 4],
            ),  # case E
            make_inputs(
                mode=Mode.CUT,
                goal_weight_kg=72.0,
                duration_days=60,
                calorie_override=2300,
                override_for_mode=Mode.CUT,
            ),  # case I
        ]
        for inputs in self._sample_inputs() + extra_cases:
            result = compute_plan_targets(inputs)
            if not (result.calories_clamped or result.override_source is not None):
                continue
            if result.target_calories is None or result.precision != "calorie_projected":
                continue
            tdee = result.tdee
            tc = result.target_calories
            weekly = (tc - tdee) * 7 / config.ENERGY_KCAL_PER_KG
            total = weekly * inputs.duration_days / 7
            end = inputs.weight_kg + total
            self.assertAlmostEqual(result.predicted_weekly_change_kg, weekly, places=9)
            self.assertAlmostEqual(result.predicted_total_change_kg, total, places=9)
            self.assertAlmostEqual(result.projected_end_weight_kg, end, places=9)

    def test_macro_preservation_for_overrides(self):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            macro_override=MacroOverride(protein_g=160, fat_g=61, carbs_g=250),
            override_for_mode=Mode.CUT,
        )
        result = compute_plan_targets(inputs)
        self.assertEqual(result.macros.protein_g, 160)
        self.assertEqual(result.macros.fat_g, 61)
        self.assertEqual(result.macros.carbs_g, 250)
        self.assertEqual(result.target_calories, 4 * 160 + 4 * 250 + 9 * 61)

    def test_days_needed_direction_check(self):
        # N1: near-TDEE override -> null. N2: surplus on a Cut -> null.
        # N3: deficit on a Bulk -> null.
        for mode, goal, duration, override, override_mode in (
            (Mode.CUT, 72.0, 60, 2644, Mode.CUT),
            (Mode.CUT, 72.0, 60, 2900, Mode.CUT),
            (Mode.BULK, 79.0, 90, 2400, Mode.BULK),
        ):
            inputs = make_inputs(
                mode=mode,
                goal_weight_kg=goal,
                duration_days=duration,
                calorie_override=override,
                override_for_mode=override_mode,
            )
            result = compute_plan_targets(inputs)
            self.assertIsNone(result.days_needed)


class OverrideValidationStructureTests(unittest.TestCase):
    """Extra coverage for V-20/V-22/V-23 combinations not already covered
    by cases Q/R/S/T/U above."""

    def test_conflict_takes_priority_over_missing_mode(self):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            calorie_override=2300,
            macro_override=MacroOverride(protein_g=160, fat_g=61, carbs_g=250),
            override_for_mode=None,
        )
        result = compute_plan_targets(inputs)
        self.assertIn("OVERRIDE_CONFLICT", codes(result))
        self.assertNotIn("OVERRIDE_MODE_REQUIRED", codes(result))

    def test_macro_override_requires_mode_too(self):
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            macro_override=MacroOverride(protein_g=160, fat_g=61, carbs_g=250),
            override_for_mode=None,
        )
        result = compute_plan_targets(inputs)
        self.assertIn("OVERRIDE_MODE_REQUIRED", codes(result))
        self.assertIsNone(result.override_source)


class FocusGoalSuggestsTests(unittest.TestCase):
    """V-14 FOCUS_GOAL_SUGGESTS_CUT_OR_BULK (4.3)."""

    def test_focus_goal_far_from_current_suggests_switch(self):
        inputs = make_inputs(mode=Mode.FOCUS, goal_weight_kg=70.0)  # ~8.3% away from 76.3
        result = compute_plan_targets(inputs)
        self.assertIn("FOCUS_GOAL_SUGGESTS_CUT_OR_BULK", codes(result))
        self.assertEqual(severity_of(result, "FOCUS_GOAL_SUGGESTS_CUT_OR_BULK"), "info")

    def test_focus_goal_close_to_current_no_message(self):
        inputs = make_inputs(mode=Mode.FOCUS, goal_weight_kg=76.5)  # well under 2%
        result = compute_plan_targets(inputs)
        self.assertNotIn("FOCUS_GOAL_SUGGESTS_CUT_OR_BULK", codes(result))


class RecompOverrideLargeTests(unittest.TestCase):
    """V-13 RECOMP_OVERRIDE_LARGE."""

    def test_large_recomp_override_warns(self):
        inputs = make_inputs(
            mode=Mode.RECOMP,
            goal_weight_kg=None,
            calorie_override=3200,  # > 15% above TDEE 2643.525
            override_for_mode=Mode.RECOMP,
        )
        result = compute_plan_targets(inputs)
        self.assertIn("RECOMP_OVERRIDE_LARGE", codes(result))
        self.assertEqual(severity_of(result, "RECOMP_OVERRIDE_LARGE"), "warn")

    def test_small_recomp_override_no_warn(self):
        inputs = make_inputs(
            mode=Mode.RECOMP,
            goal_weight_kg=None,
            calorie_override=2600,
            override_for_mode=Mode.RECOMP,
        )
        result = compute_plan_targets(inputs)
        self.assertNotIn("RECOMP_OVERRIDE_LARGE", codes(result))


class ConsecutiveDaysTests(unittest.TestCase):
    """V-11 CONSECUTIVE_DAYS (6.1): run > 2 for 3-4 days/week, > 3 for 5,
    never for 6."""

    def test_default_4day_spread_no_warning(self):
        # Mon/Tue/Thu/Sat -- longest run is 2 (Mon-Tue), not > 2.
        inputs = make_inputs(days_per_week=4, training_weekdays=[0, 1, 3, 5])
        result = compute_plan_targets(inputs)
        self.assertNotIn("CONSECUTIVE_DAYS", codes(result))

    def test_4day_run_of_3_warns(self):
        # Mon/Tue/Wed/Sat -- run of 3 > limit of 2.
        inputs = make_inputs(days_per_week=4, training_weekdays=[0, 1, 2, 5])
        result = compute_plan_targets(inputs)
        self.assertIn("CONSECUTIVE_DAYS", codes(result))
        self.assertEqual(severity_of(result, "CONSECUTIVE_DAYS"), "warn")

    def test_default_5day_spread_run_of_3_no_warning(self):
        # Mon/Tue/Thu/Fri/Sat -- longest run is 3, not > 3.
        inputs = make_inputs(
            days_per_week=5, training_weekdays=[0, 1, 3, 4, 5]
        )
        result = compute_plan_targets(inputs)
        self.assertNotIn("CONSECUTIVE_DAYS", codes(result))

    def test_5day_run_of_4_warns(self):
        # Mon/Tue/Wed/Thu/Sat -- run of 4 > limit of 3.
        inputs = make_inputs(
            days_per_week=5, training_weekdays=[0, 1, 2, 3, 5]
        )
        result = compute_plan_targets(inputs)
        self.assertIn("CONSECUTIVE_DAYS", codes(result))

    def test_6day_run_of_6_never_warns(self):
        # Mon-Sat, run of 6 -- rule never fires at 6 days/week.
        inputs = make_inputs(
            days_per_week=6, training_weekdays=[0, 1, 2, 3, 4, 5]
        )
        result = compute_plan_targets(inputs)
        self.assertNotIn("CONSECUTIVE_DAYS", codes(result))

    def test_wraparound_run_counts_across_week_boundary(self):
        # Fri/Sat/Sun/Tue (days_per_week=4) -- Fri-Sat-Sun is a circular run
        # of 3, which must be detected even though it wraps past index 6.
        inputs = make_inputs(days_per_week=4, training_weekdays=[4, 5, 6, 1])
        result = compute_plan_targets(inputs)
        self.assertIn("CONSECUTIVE_DAYS", codes(result))


class BeginnerHighFrequencyTests(unittest.TestCase):
    """V-15 BEGINNER_HIGH_FREQUENCY: beginner with 5-6 days/week."""

    def test_beginner_5_days_warns_info(self):
        inputs = make_inputs(
            experience=Experience.BEGINNER,
            days_per_week=5,
            training_weekdays=[0, 1, 3, 4, 5],
        )
        result = compute_plan_targets(inputs)
        self.assertIn("BEGINNER_HIGH_FREQUENCY", codes(result))
        self.assertEqual(severity_of(result, "BEGINNER_HIGH_FREQUENCY"), "info")

    def test_beginner_6_days_warns_info(self):
        inputs = make_inputs(
            experience=Experience.BEGINNER,
            days_per_week=6,
            training_weekdays=[0, 1, 2, 3, 4, 5],
        )
        result = compute_plan_targets(inputs)
        self.assertIn("BEGINNER_HIGH_FREQUENCY", codes(result))

    def test_beginner_4_days_no_message(self):
        inputs = make_inputs(experience=Experience.BEGINNER, days_per_week=4)
        result = compute_plan_targets(inputs)
        self.assertNotIn("BEGINNER_HIGH_FREQUENCY", codes(result))

    def test_intermediate_6_days_no_message(self):
        inputs = make_inputs(
            experience=Experience.INTERMEDIATE,
            days_per_week=6,
            training_weekdays=[0, 1, 2, 3, 4, 5],
        )
        result = compute_plan_targets(inputs)
        self.assertNotIn("BEGINNER_HIGH_FREQUENCY", codes(result))


class CutHighFrequencyRecoveryTests(unittest.TestCase):
    """V-16 CUT_HIGH_FREQUENCY_RECOVERY: Cut, 6 days/week, aggressive final
    pace."""

    def test_cut_6_days_aggressive_pace_warns(self):
        # Same goal/duration as case C (aggressive at 1.27%/wk); the final
        # pace is independent of activity factor when the floor isn't hit,
        # since calories exactly meet the requested delta either way.
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=68.0,
            duration_days=60,
            days_per_week=6,
            training_weekdays=[0, 1, 2, 3, 4, 5],
        )
        result = compute_plan_targets(inputs)
        self.assertEqual(result.pace_status, "aggressive")
        self.assertIn("CUT_HIGH_FREQUENCY_RECOVERY", codes(result))
        self.assertEqual(severity_of(result, "CUT_HIGH_FREQUENCY_RECOVERY"), "warn")

    def test_cut_4_days_aggressive_pace_no_recovery_message(self):
        # Same aggressive pace, but only 4 days/week -- rule shouldn't fire.
        inputs = make_inputs(mode=Mode.CUT, goal_weight_kg=68.0, duration_days=60)
        result = compute_plan_targets(inputs)
        self.assertEqual(result.pace_status, "aggressive")
        self.assertNotIn("CUT_HIGH_FREQUENCY_RECOVERY", codes(result))

    def test_cut_6_days_typical_pace_no_recovery_message(self):
        # Case A's goal (typical pace, not aggressive) at 6 days/week.
        inputs = make_inputs(
            mode=Mode.CUT,
            goal_weight_kg=72.0,
            duration_days=60,
            days_per_week=6,
            training_weekdays=[0, 1, 2, 3, 4, 5],
        )
        result = compute_plan_targets(inputs)
        self.assertEqual(result.pace_status, "typical")
        self.assertNotIn("CUT_HIGH_FREQUENCY_RECOVERY", codes(result))

    def test_bulk_6_days_aggressive_pace_no_recovery_message(self):
        # Rule is Cut-specific; Bulk at 6 days/week + aggressive must not fire.
        inputs = make_inputs(
            mode=Mode.BULK,
            goal_weight_kg=85.0,
            duration_days=90,
            days_per_week=6,
            training_weekdays=[0, 1, 2, 3, 4, 5],
        )
        result = compute_plan_targets(inputs)
        self.assertEqual(result.pace_status, "aggressive")
        self.assertNotIn("CUT_HIGH_FREQUENCY_RECOVERY", codes(result))


if __name__ == "__main__":
    unittest.main()
