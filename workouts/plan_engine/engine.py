"""Calculation + validation engine (spec sections 4 and 5, scoped per the
product owner's decisions for this pass -- see the module docstring in
``__init__.py`` and the implementation report for exactly which validation
rules are implemented).

``compute_plan_targets`` is the single public entry point. It is a pure
function: same ``PlanInputs`` in, same ``PlanTargets`` out, no I/O, no
wall-clock access.

Design note (judgment call, documented in the implementation report):
Validation is advisory, not a circuit breaker -- the engine computes every
field that is mathematically well-defined from the given inputs regardless
of whether a ``block`` message also fires for those inputs (e.g. a Cut with
an invalid goal direction still gets a computed ``target_calories`` so the
preview can show "what would happen"). The only fields that are genuinely
*undefined* (and therefore ``None``) are the ones whose formula itself
requires a missing input -- chiefly: Cut/Bulk calorie targets with no goal
weight and no override (4.3's formula needs the goal to derive
``daily_delta``), and the goal-dependent pace fields
(``requested_weekly_change_pct``, ``days_needed``) when there is no goal.
"""

import math

from . import config
from .domain import (
    Experience,
    Macros,
    MacroOverride,
    Message,
    Mode,
    PlanInputs,
    PlanTargets,
)
from .rounding import round_half_up


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _bmr(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + 5 if sex == "male" else base - 161


def _activity_factor(activity_level) -> float:
    table = config.ACTIVITY_FACTOR_BY_LEVEL
    key = activity_level.value if hasattr(activity_level, "value") else str(activity_level)
    # Defensive fallback for an unrecognised value: MODERATE, the same
    # default PlanInputs.activity_level itself falls back to.
    return table.get(key, table["MODERATE"])


def _pace_band(mode: Mode) -> dict:
    return config.PACE_BANDS_PCT[mode]


def _pace_status(mode: Mode, final_pct: float) -> str:
    band = _pace_band(mode)
    if final_pct < band["gentle_max"]:
        return "gentle"
    if final_pct <= band["typical_max"]:
        return "typical"
    return "aggressive"


def _extend_to_days(mode: Mode, weight_kg: float, delta_kg: float):
    """V-07/V-08 'Extend to N days' action. ``delta_kg`` is (goal - weight)."""
    band = _pace_band(mode)
    upper_typical_kg_per_week = band["typical_max"] / 100 * weight_kg
    if upper_typical_kg_per_week <= 0:
        return None
    return math.ceil(abs(delta_kg) / upper_typical_kg_per_week * 7)


def _longest_consecutive_run(weekdays) -> int:
    """Longest run of consecutive training weekdays (6.1), treating the week
    as circular (e.g. Sat+Sun+Mon is a run of 3, not two separate runs of 1
    and 2), since the schedule repeats every week."""
    days = sorted(set(weekdays))
    n = len(days)
    if n == 0:
        return 0
    if n == 7:
        return 7
    extended = days + [d + 7 for d in days]
    best = current = 1
    for i in range(1, len(extended)):
        if extended[i] == extended[i - 1] + 1:
            current += 1
        else:
            current = 1
        best = max(best, current)
    return min(best, n)


def _goal_direction_valid(mode: Mode, goal_weight_kg: float, weight_kg: float) -> bool:
    if mode == Mode.CUT:
        return goal_weight_kg <= weight_kg - config.GOAL_MIN_DELTA_KG
    if mode == Mode.BULK:
        return goal_weight_kg >= weight_kg + config.GOAL_MIN_DELTA_KG
    return True


def _macros_for(mode: Mode, weight_kg: float, target_calories: float):
    """4.7 macro computation with the carb-floor fallback cascade.

    Returns ``(Macros, macros_tight: bool)``.
    """
    protein_g_per_kg = config.PROTEIN_G_PER_KG_BY_MODE[mode]
    protein_g = round_half_up(protein_g_per_kg * weight_kg)
    fat_g = round_half_up(config.FAT_PCT_OF_TARGET_CALORIES * target_calories / 9)

    def carbs_for(p, f):
        return round_half_up((target_calories - 4 * p - 9 * f) / 4)

    carbs_g = carbs_for(protein_g, fat_g)
    macros_tight = False

    if carbs_g < config.CARB_FLOOR_G:
        floor_fat_g = round_half_up(config.FAT_FLOOR_G_PER_KG * weight_kg)
        if floor_fat_g < fat_g:
            fat_g = floor_fat_g
            carbs_g = carbs_for(protein_g, fat_g)

    if carbs_g < config.CARB_FLOOR_G:
        floor_protein_g = round_half_up(config.PROTEIN_FLOOR_G_PER_KG * weight_kg)
        if floor_protein_g < protein_g:
            protein_g = floor_protein_g
            carbs_g = carbs_for(protein_g, fat_g)

    if carbs_g < config.CARB_FLOOR_G:
        macros_tight = True
        carbs_g = max(carbs_g, 0)

    return Macros(protein_g=protein_g, fat_g=fat_g, carbs_g=carbs_g), macros_tight


def _macros_unusual(protein_g: int, fat_g: int, weight_kg: float) -> bool:
    protein_per_kg = protein_g / weight_kg
    fat_per_kg = fat_g / weight_kg
    return (
        protein_per_kg < config.MACROS_UNUSUAL_PROTEIN_MIN_G_PER_KG
        or protein_per_kg > config.MACROS_UNUSUAL_PROTEIN_MAX_G_PER_KG
        or fat_per_kg < config.MACROS_UNUSUAL_FAT_MIN_G_PER_KG
    )


def _apply_floor_and_round(raw_target, sex):
    """4.4 + 4.5 steps 2-3 (non-override path only). Returns
    ``(target_calories, calories_clamped, hit_floor)``."""
    floor = config.CALORIE_FLOOR_KCAL[sex]
    hit_floor = raw_target < floor
    floored = floor if hit_floor else raw_target
    return round_half_up(floored, step=10), hit_floor, hit_floor


def compute_plan_targets(inputs: PlanInputs) -> PlanTargets:
    messages = []

    def add(code, severity, **params):
        messages.append(Message(code=code, severity=severity, params=params))

    mode = inputs.mode
    sex = inputs.sex
    weight = inputs.weight_kg
    height = inputs.height_cm
    age = inputs.age
    duration_days = inputs.duration_days
    days_per_week = inputs.days_per_week
    goal = inputs.goal_weight_kg

    # ---------------------------------------------------------------
    # V-01 .. V-04: field-level validation. These never block downstream
    # computation (they just gate ``can_start``) except where noted.
    # ---------------------------------------------------------------
    if not (
        config.MIN_WEIGHT_KG <= weight <= config.MAX_WEIGHT_KG
        and config.MIN_HEIGHT_CM <= height <= config.MAX_HEIGHT_CM
        and config.MIN_AGE <= age <= config.MAX_AGE
    ):
        add("PROFILE_OUT_OF_RANGE", "block")

    if not (
        isinstance(duration_days, int)
        and config.MIN_DURATION_DAYS <= duration_days <= config.MAX_DURATION_DAYS
    ):
        add("DURATION_INVALID", "block")

    if not (
        isinstance(days_per_week, int)
        and config.MIN_DAYS_PER_WEEK <= days_per_week <= config.MAX_DAYS_PER_WEEK
    ):
        add("DAYS_PER_WEEK_INVALID", "block")

    if len(inputs.training_weekdays) != days_per_week:
        add(
            "TRAINING_DAYS_MISMATCH",
            "block",
            selected=len(inputs.training_weekdays),
            required=days_per_week,
        )

    # Defensive guard for the division below; does not change DURATION_INVALID.
    safe_duration_days = duration_days if duration_days and duration_days > 0 else 1

    # ---------------------------------------------------------------
    # V-11 CONSECUTIVE_DAYS (6.1) and V-15 BEGINNER_HIGH_FREQUENCY. Pure
    # inputs-level checks, independent of the calorie/pace calculation.
    # ---------------------------------------------------------------
    if config.MIN_DAYS_PER_WEEK <= days_per_week <= config.MAX_DAYS_PER_WEEK:
        limit = config.CONSECUTIVE_DAY_RUN_LIMIT_BY_DAYS_PER_WEEK.get(days_per_week)
        if limit is not None:
            run = _longest_consecutive_run(inputs.training_weekdays)
            if run > limit:
                add("CONSECUTIVE_DAYS", "warn", run=run, limit=limit)

    if (
        inputs.experience == Experience.BEGINNER
        and days_per_week in config.BEGINNER_HIGH_FREQUENCY_DAYS_PER_WEEK
    ):
        add("BEGINNER_HIGH_FREQUENCY", "info")

    # ---------------------------------------------------------------
    # 4.8 / 4.10 overrides: V-22 (OVERRIDE_MODE_REQUIRED),
    # V-23 (OVERRIDE_CONFLICT), V-20 (OVERRIDE_CLEARED_MODE_CHANGED).
    # ---------------------------------------------------------------
    has_calorie_override = inputs.calorie_override is not None
    has_macro_override = inputs.macro_override is not None
    override_applicable = False
    override_source = None

    if has_calorie_override and has_macro_override:
        add("OVERRIDE_CONFLICT", "block")
    elif has_calorie_override or has_macro_override:
        if inputs.override_for_mode is None:
            add("OVERRIDE_MODE_REQUIRED", "block")
        elif inputs.override_for_mode != mode:
            add("OVERRIDE_CLEARED_MODE_CHANGED", "info")
        else:
            override_applicable = True
            override_source = "calories" if has_calorie_override else "macros"

    # ---------------------------------------------------------------
    # 4.1 BMR / TDEE
    # ---------------------------------------------------------------
    bmr = _bmr(sex, weight, height, age)
    activity_factor = _activity_factor(inputs.activity_level)
    tdee = bmr * activity_factor

    # ---------------------------------------------------------------
    # Precision per mode (4.3)
    # ---------------------------------------------------------------
    if mode in (Mode.CUT, Mode.BULK):
        precision = "calorie_projected"
    elif mode == Mode.RECOMP:
        precision = "directional"
    else:
        precision = "maintenance"

    recomp_direction = inputs.recomp_direction if mode == Mode.RECOMP else None
    if mode == Mode.RECOMP and recomp_direction is None:
        recomp_direction = config.DEFAULT_RECOMP_DIRECTION

    # ---------------------------------------------------------------
    # 4.3 raw target calories + requested pace (independent of override --
    # also used to compute "suggested" values while an override is active).
    # ---------------------------------------------------------------
    requested_weekly_change_kg = None
    requested_weekly_change_pct = None
    raw_target = None

    if mode in (Mode.CUT, Mode.BULK):
        if goal is None:
            add("GOAL_WEIGHT_REQUIRED", "block")
        else:
            requested_weekly_change_kg = (goal - weight) / (safe_duration_days / 7)
            requested_weekly_change_pct = abs(requested_weekly_change_kg) / weight * 100
            daily_delta = requested_weekly_change_kg * config.ENERGY_KCAL_PER_KG / 7
            raw_target = tdee + daily_delta

            if not _goal_direction_valid(mode, goal, weight):
                add("GOAL_DIRECTION_INVALID", "block")

            if mode == Mode.CUT:
                min_goal_for_bmi = config.MIN_GOAL_BMI * (height / 100) ** 2
                if goal < min_goal_for_bmi:
                    add(
                        "GOAL_BMI_TOO_LOW",
                        "block",
                        min_goal_weight_kg=round(min_goal_for_bmi, 1),
                    )
    elif mode == Mode.RECOMP:
        direction_factor = config.RECOMP_DIRECTION_FACTOR[recomp_direction]
        raw_target = tdee * (1 + direction_factor)
    else:  # FOCUS
        raw_target = tdee
        if goal is not None and weight and abs(goal - weight) / weight >= config.FOCUS_GOAL_SUGGEST_PCT:
            add("FOCUS_GOAL_SUGGESTS_CUT_OR_BULK", "info")

    # ---------------------------------------------------------------
    # V-07: hard limit on the REQUESTED pace (fresh goal+duration only --
    # suppressed while an override is active; V-12 covers that case instead).
    # ---------------------------------------------------------------
    if (
        mode in (Mode.CUT, Mode.BULK)
        and requested_weekly_change_pct is not None
        and not override_applicable
    ):
        band = _pace_band(mode)
        if requested_weekly_change_pct > band["hard_limit"]:
            severity = "block" if config.PACE_HARD_LIMIT_MODE == "block" else "warn"
            params = {}
            n = _extend_to_days(mode, weight, goal - weight)
            if n is not None and n <= config.MAX_DURATION_DAYS:
                params["extend_to_days"] = n
            add("PACE_ABOVE_LIMIT", severity, **params)

    # ---------------------------------------------------------------
    # "Default" (non-override) target_calories pipeline -- 4.4 floor + 4.5
    # steps 2-3. Used as the actual target_calories when there is no
    # override, and as ``suggested_calories`` when there is one.
    # ---------------------------------------------------------------
    default_target_calories = None
    default_calories_clamped = False
    if raw_target is not None:
        default_target_calories, default_calories_clamped, hit_floor = _apply_floor_and_round(
            raw_target, sex
        )
        if not override_applicable and hit_floor:
            add("CALORIES_RAISED_TO_FLOOR", "warn")

    # ---------------------------------------------------------------
    # 4.8: resolve the actual target_calories.
    # ---------------------------------------------------------------
    calories_clamped = False
    suggested_calories = None
    suggested_macros = None

    if override_applicable and override_source == "calories":
        target_calories = inputs.calorie_override
        suggested_calories = default_target_calories
    elif override_applicable and override_source == "macros":
        mo: MacroOverride = inputs.macro_override
        target_calories = 4 * mo.protein_g + 4 * mo.carbs_g + 9 * mo.fat_g
        suggested_calories = default_target_calories
    else:
        target_calories = default_target_calories
        calories_clamped = default_calories_clamped

    if suggested_calories is not None:
        suggested_macros, _ = _macros_for(mode, weight, suggested_calories)

    # ---------------------------------------------------------------
    # 4.5 step 4: derive everything else from the FINAL target_calories and
    # the full-precision tdee. Never re-derive from the goal.
    # ---------------------------------------------------------------
    macros = None
    calorie_delta = None
    predicted_weekly_change_kg = None
    predicted_total_change_kg = None
    projected_end_weight_kg = None
    weekly_change_pct_bodyweight = None
    days_needed = None
    pace_status = "not_applicable"

    if target_calories is not None:
        calorie_delta = target_calories - tdee

        if override_applicable and override_source == "macros":
            mo = inputs.macro_override
            macros = Macros(protein_g=mo.protein_g, fat_g=mo.fat_g, carbs_g=mo.carbs_g)
        else:
            macros, macros_tight = _macros_for(mode, weight, target_calories)
            if macros_tight:
                add("MACROS_TIGHT", "warn")

        if precision == "calorie_projected":
            weekly_change_kg = (target_calories - tdee) * 7 / config.ENERGY_KCAL_PER_KG
            total_change_kg = weekly_change_kg * safe_duration_days / 7
            end_weight_kg = weight + total_change_kg
            pct = abs(weekly_change_kg) / weight * 100

            predicted_weekly_change_kg = weekly_change_kg
            predicted_total_change_kg = total_change_kg
            projected_end_weight_kg = end_weight_kg
            weekly_change_pct_bodyweight = pct
            pace_status = _pace_status(mode, pct)

            # V-16 CUT_HIGH_FREQUENCY_RECOVERY.
            if mode == Mode.CUT and days_per_week == 6 and pace_status == "aggressive":
                add("CUT_HIGH_FREQUENCY_RECOVERY", "warn")

            band = _pace_band(mode)
            v07_fired = any(m.code == "PACE_ABOVE_LIMIT" for m in messages)
            if not v07_fired and pct > band["typical_max"]:
                params = {}
                if goal is not None:
                    n = _extend_to_days(mode, weight, goal - weight)
                    if n is not None and n <= config.MAX_DURATION_DAYS:
                        params["extend_to_days"] = n
                add("PACE_AGGRESSIVE", "warn", **params)

            # V-12 (override clause): same hard limit applied to the FINAL
            # pace when an override is active.
            floor = config.CALORIE_FLOOR_KCAL[sex]
            override_floor_violated = override_applicable and target_calories < floor
            if override_applicable and override_floor_violated:
                add("OVERRIDE_INVALID", "block", reason="below_floor")
            elif override_applicable and pct > band["hard_limit"]:
                severity = "block" if config.PACE_HARD_LIMIT_MODE == "block" else "warn"
                add("OVERRIDE_INVALID", severity, reason="pace_above_limit")

            # days_needed / V-18 (goal-dependent; null-safe per 4.5/4.6).
            #
            # NOTE: V-18 tracks only "moves away from the goal, or moves
            # toward it slower than 0.05 kg/week" (4.5's first two
            # conditions). The separate 365-day cap (4.5's third
            # condition) can ALSO null out days_needed even while the plan
            # is moving toward the goal at an adequate rate -- that case
            # must NOT raise V-18 (it is a distinct, unflagged outcome:
            # "will get there, just not within a year"). The two must not
            # be conflated.
            if goal is not None:
                moves_toward_goal = weekly_change_kg != 0 and _sign(weekly_change_kg) == _sign(
                    goal - weight
                )
                rate_adequate = (
                    moves_toward_goal
                    and abs(weekly_change_kg) >= config.DAYS_NEEDED_MIN_WEEKLY_RATE_KG
                )
                if rate_adequate:
                    n_days = math.ceil(abs(goal - weight) / abs(weekly_change_kg) * 7)
                    if n_days <= config.DAYS_NEEDED_MAX_DAYS:
                        days_needed = n_days
                else:
                    add("TARGET_NOT_MOVING_TOWARD_GOAL", "warn")

                if abs(end_weight_kg - goal) > config.GOAL_NOT_REACHED_TOLERANCE_KG:
                    add(
                        "GOAL_NOT_REACHED_IN_TIME",
                        "info",
                        projected_end_weight_kg=end_weight_kg,
                    )
        else:
            # Recomp / Focus: V-13 RECOMP_OVERRIDE_LARGE.
            if tdee and abs(calorie_delta) / tdee > config.RECOMP_OVERRIDE_LARGE_PCT:
                add("RECOMP_OVERRIDE_LARGE", "warn")

            if override_applicable:
                floor = config.CALORIE_FLOOR_KCAL[sex]
                if target_calories < floor:
                    add("OVERRIDE_INVALID", "block", reason="below_floor")

        # V-12 calorie-override floor check (always-block clause), applies
        # regardless of mode/precision.
        if override_applicable and override_source == "calories":
            floor = config.CALORIE_FLOOR_KCAL[sex]
            already_flagged = any(m.code == "OVERRIDE_INVALID" for m in messages)
            if not already_flagged and inputs.calorie_override < floor:
                add("OVERRIDE_INVALID", "block", reason="below_floor")

        # V-19 MACROS_UNUSUAL + macro-override sanity (negative grams,
        # calorie-sum floor).
        if override_applicable and override_source == "macros":
            mo = inputs.macro_override
            if mo.protein_g < 0 or mo.fat_g < 0 or mo.carbs_g < 0:
                add("OVERRIDE_INVALID", "block", reason="negative_macro")
            else:
                floor = config.CALORIE_FLOOR_KCAL[sex]
                already_flagged = any(m.code == "OVERRIDE_INVALID" for m in messages)
                if not already_flagged and target_calories < floor:
                    add("OVERRIDE_INVALID", "block", reason="below_floor")
                if _macros_unusual(mo.protein_g, mo.fat_g, weight):
                    add("MACROS_UNUSUAL", "warn")

    can_start = not any(m.severity == "block" for m in messages)

    return PlanTargets(
        engine_version=config.ENGINE_VERSION,
        can_start=can_start,
        bmr=bmr,
        activity_factor=activity_factor,
        tdee=tdee,
        target_calories=target_calories,
        calorie_delta=calorie_delta,
        macros=macros,
        precision=precision,
        predicted_weekly_change_kg=predicted_weekly_change_kg,
        predicted_total_change_kg=predicted_total_change_kg,
        projected_end_weight_kg=projected_end_weight_kg,
        weekly_change_pct_bodyweight=weekly_change_pct_bodyweight,
        requested_weekly_change_pct=requested_weekly_change_pct,
        days_needed=days_needed,
        override_source=override_source,
        suggested_calories=suggested_calories,
        suggested_macros=suggested_macros,
        pace_status=pace_status,
        calories_clamped=calories_clamped,
        messages=messages,
    )
