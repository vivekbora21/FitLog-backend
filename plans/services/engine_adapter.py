"""Adapter between the ``plans/`` app and ``workouts.plan_engine``.

``plans/`` has its own conventions that predate the engine: mode is an
upper-case string ('CUT'/'BULK'/'RECOMP'/'FOCUS'/'HABIT' -- see
``workouts.models.JourneyProgram.MODE_CHOICES``), sex is 'MALE'/'FEMALE',
and ``weekdays`` is an optional 1..7 list. This module is the single place
that translates those into ``workouts.plan_engine.domain.PlanInputs``, calls
``compute_plan_targets``, and maps the result back onto the shapes
``plans/`` already expects.

This is the ONLY calorie/macro/pace/validation computation in ``plans/`` --
``plan_generator.calculate_targets`` is now a thin wrapper around
``compute_mode_targets`` below (see its docstring), and ``generate_roadmap``
calls this module directly for the richer engine metadata it stores on a
newly-created ``JourneyProgram`` (spec v1.6 section 7.1).
"""

import dataclasses

from workouts.plan_engine.domain import (
    Equipment, Experience, MacroOverride, Mode, PlanInputs, RecompDirection,
)
from workouts.plan_engine.engine import compute_plan_targets
from workouts.plan_engine.serialization import serialize_plan_targets

MODE_MAP = {
    'CUT': Mode.CUT,
    'BULK': Mode.BULK,
    'RECOMP': Mode.RECOMP,
    'FOCUS': Mode.FOCUS,
    'HABIT': Mode.HABIT,
}

# Fallback defaults when a caller doesn't supply a real experience/equipment
# value (e.g. an older/partial request, or a direct `calculate_targets()`
# caller that predates these fields). plans/' request serializers DO collect
# both (spec v1.6 section 6.2: `experience`, `equipment_level`) and
# `build_plan_inputs` below maps the real submitted value through to the
# engine whenever one is given -- it is no longer hardcoded regardless of
# the request. This matters beyond the section-6 schedule rules: V-15
# BEGINNER_HIGH_FREQUENCY (section 4/5 validation, computed inside
# `compute_plan_targets` itself) can only ever fire for a real
# `Experience.BEGINNER` value, so silently defaulting to INTERMEDIATE here
# would have made V-15 unreachable through this adapter.
_DEFAULT_EXPERIENCE = Experience.INTERMEDIATE
_DEFAULT_EQUIPMENT = Equipment.FULL_GYM

# Human-readable text for the subset of engine message codes most likely to
# reach a plans/ caller through the legacy `warnings: List[str]` shape.
# Anything not listed here still gets a readable fallback (see
# `_message_text`) instead of being silently dropped.
_MESSAGE_TEMPLATES = {
    'GOAL_WEIGHT_REQUIRED': 'A goal weight is required for this mode.',
    'GOAL_DIRECTION_INVALID': 'The goal weight is not in the right direction for this mode.',
    'GOAL_BMI_TOO_LOW': 'The goal weight is below a healthy BMI floor for a Cut.',
    # Spec v1.6 section 9 copy rules: never "safe"; these are estimates
    # against a typical-range/limit, not a safety judgement.
    'PACE_ABOVE_LIMIT': 'The requested pace is beyond the supported limit for this mode.',
    'PACE_AGGRESSIVE': 'The requested pace is aggressive; proceed with caution.',
    'CALORIES_RAISED_TO_FLOOR': (
        'Calculated calories were below the minimum floor and were raised to that minimum.'
    ),
    'MACROS_TIGHT': 'Carbohydrates were constrained to stay above the floor; macros are tight.',
    'MACROS_UNUSUAL': 'The resulting macro split is outside the usual range.',
    'TARGET_NOT_MOVING_TOWARD_GOAL': 'At this pace the plan is not moving toward the goal weight.',
    'RECOMP_OVERRIDE_LARGE': 'The calorie target is a large deviation from maintenance for this mode.',
    'OVERRIDE_INVALID': 'The requested calorie/macro override is invalid.',
    'PROFILE_OUT_OF_RANGE': 'One or more profile values (age/height/weight) are out of the supported range.',
    'DURATION_INVALID': 'The plan duration is invalid.',
    'DAYS_PER_WEEK_INVALID': 'The selected training days per week is invalid.',
    'TRAINING_DAYS_MISMATCH': 'The number of selected training days does not match days_per_week.',
}


def _engine_sex(sex):
    return 'male' if str(sex).upper() == 'MALE' else 'female'


def _engine_experience(experience):
    """plans/' `experience` is submitted upper-case ('BEGINNER' etc, spec
    v1.6 section 6.2); the engine's `Experience` enum values are lower-case.
    `None`/unrecognised -> `_DEFAULT_EXPERIENCE` (INTERMEDIATE), same
    fallback plans/ itself already uses elsewhere (see
    `plan_generator.DEFAULT_EXPERIENCE`)."""
    if isinstance(experience, Experience):
        return experience
    if not experience:
        return _DEFAULT_EXPERIENCE
    try:
        return Experience(str(experience).lower())
    except ValueError:
        return _DEFAULT_EXPERIENCE


def _engine_equipment(equipment_level):
    """plans/' `equipment_level` (spec v1.6 section 6.2/6.7, see
    `plans/split_approval.EQUIPMENT_LEVELS`) already matches the engine's
    `Equipment` enum values exactly (lower snake_case), so this is mostly a
    defensive `None`/unrecognised -> `_DEFAULT_EQUIPMENT` (full gym) fallback."""
    if isinstance(equipment_level, Equipment):
        return equipment_level
    if not equipment_level:
        return _DEFAULT_EQUIPMENT
    try:
        return Equipment(str(equipment_level).lower())
    except ValueError:
        return _DEFAULT_EQUIPMENT


def _engine_recomp_direction(recomp_direction):
    """`None` when not RECOMP or not supplied -- `compute_plan_targets`
    itself defaults a RECOMP with no direction to `DEFAULT_RECOMP_DIRECTION`
    (4.3); this adapter only needs to translate a real submitted value."""
    if recomp_direction is None or isinstance(recomp_direction, RecompDirection):
        return recomp_direction
    return RecompDirection(str(recomp_direction).lower())


def _engine_override_for_mode(override_for_mode):
    if override_for_mode is None or isinstance(override_for_mode, Mode):
        return override_for_mode
    return MODE_MAP[override_for_mode]


def _engine_macro_override(macro_override):
    """Accepts the plain dict `MacroOverrideSerializer.validated_data`
    produces (`{'protein_g': .., 'fat_g': .., 'carbs_g': ..}`) -- or an
    already-built `MacroOverride`, for callers that construct one directly
    -- and returns the `MacroOverride` dataclass the engine's `PlanInputs`
    requires (it reads `.protein_g` etc as attributes, not dict keys)."""
    if macro_override is None or isinstance(macro_override, MacroOverride):
        return macro_override
    return MacroOverride(
        protein_g=macro_override['protein_g'],
        fat_g=macro_override['fat_g'],
        carbs_g=macro_override['carbs_g'],
    )


#: 6.1 default training-day spread, used as the placeholder below when the
#: caller has no real weekday selection -- a naive contiguous range (e.g.
#: [0, 1, 2, 3]) would spuriously trip V-11 CONSECUTIVE_DAYS, which is a
#: real validation rule since Phase 2, not just a length check.
_DEFAULT_SPREAD_BY_DAYS_PER_WEEK = {
    3: [0, 2, 4],        # Mon/Wed/Fri
    4: [0, 1, 3, 5],     # Mon/Tue/Thu/Sat
    5: [0, 1, 3, 4, 5],  # Mon/Tue/Thu/Fri/Sat
    6: [0, 1, 2, 3, 4, 5],  # Mon-Sat
}


def _engine_training_weekdays(weekdays, days_per_week):
    """plans/' `weekdays` (optional, 1..7, and not a literal calendar
    weekday -- see plan_generator.generate_roadmap's own comment on this)
    mapped to the engine's 0..6, length == days_per_week convention.

    The engine checks this list's *length* against `days_per_week` (V-03
    TRAINING_DAYS_MISMATCH, advisory-only) and, since Phase 2, its longest
    *consecutive run* (V-11 CONSECUTIVE_DAYS) -- so when the caller omitted
    `weekdays` (generate_roadmap falls back to the blueprint's own pattern
    in that case), the placeholder must use the spec's own 6.1 default
    spread rather than an arbitrary contiguous range, or it would fabricate
    a warning the real (unknown) schedule may not deserve.
    """
    if weekdays and len(weekdays) == days_per_week:
        return sorted((d - 1) % 7 for d in weekdays)
    return _DEFAULT_SPREAD_BY_DAYS_PER_WEEK.get(days_per_week, list(range(days_per_week)))


def _message_text(message):
    template = _MESSAGE_TEMPLATES.get(message['code'])
    if template:
        return template
    return message['code'].replace('_', ' ').title() + '.'


def build_plan_inputs(*, mode, weight_kg, height_cm, age_years, sex, days_per_week,
                       duration_days, goal_weight_kg=None, weekdays=None,
                       experience=None, equipment=None,
                       recomp_direction=None, calorie_override=None,
                       macro_override=None, override_for_mode=None, split_id=None):
    """Builds a `PlanInputs` from the plain kwargs `plans/` has on hand."""
    return PlanInputs(
        mode=MODE_MAP[mode],
        sex=_engine_sex(sex),
        age=age_years,
        height_cm=height_cm,
        weight_kg=weight_kg,
        goal_weight_kg=goal_weight_kg,
        duration_days=duration_days,
        days_per_week=days_per_week,
        training_weekdays=_engine_training_weekdays(weekdays, days_per_week),
        experience=_engine_experience(experience),
        equipment=_engine_equipment(equipment),
        recomp_direction=_engine_recomp_direction(recomp_direction),
        calorie_override=calorie_override,
        macro_override=_engine_macro_override(macro_override),
        override_for_mode=_engine_override_for_mode(override_for_mode),
        split_id=split_id,
    )


def compute_mode_targets(*, mode, weight_kg, height_cm, age_years, sex, days_per_week,
                          duration_days, goal_weight_kg=None, weekdays=None, **override_kwargs):
    """Single entry point: builds `PlanInputs`, runs the engine, and returns
    `(inputs, targets, serialized)` -- the dataclass inputs (for audit
    storage), the raw `PlanTargets` dataclass, and its serialized dict
    (spec 4.9), respectively."""
    inputs = build_plan_inputs(
        mode=mode, weight_kg=weight_kg, height_cm=height_cm, age_years=age_years,
        sex=sex, days_per_week=days_per_week, duration_days=duration_days,
        goal_weight_kg=goal_weight_kg, weekdays=weekdays, **override_kwargs,
    )
    targets = compute_plan_targets(inputs)
    serialized = serialize_plan_targets(targets)
    return inputs, targets, serialized


def legacy_shaped_targets(serialized):
    """Maps `serialize_plan_targets()`'s dict onto the shape
    `plan_generator.calculate_targets()` has always returned, so the
    existing day-by-day roadmap-building code in `generate_roadmap` doesn't
    need to change its field names. Richer spec v1.6 fields that have no
    equivalent in the old shape are added additively (not documented by the
    pre-engine code, but harmless for any caller that only reads the
    original keys).

    Falls back to zeroed macros/calories (rather than `None`) when the
    engine could not compute a target at all (e.g. Cut/Bulk with a missing
    goal and no override -- `can_start` is then `False` and `messages`
    carries the `block` reason) so day-by-day arithmetic downstream
    (rest-day calories, carb-from-calories) never crashes on `None`.
    """
    macros = serialized['macros'] or {'protein_g': 0, 'fat_g': 0, 'carbs_g': 0}
    warnings = [
        _message_text(m) for m in serialized['messages'] if m['severity'] in ('block', 'warn')
    ]
    return {
        'tdee': serialized['tdee'],
        'bmr': serialized['bmr'],
        'daily_calories': serialized['target_calories'] if serialized['target_calories'] is not None else 0,
        'protein_g': macros['protein_g'],
        'carbs_g': macros['carbs_g'],
        'fat_g': macros['fat_g'],
        'weekly_rate_kg': serialized['predicted_weekly_change_kg'],
        'warnings': warnings,
        # --- Additive: spec v1.6 PlanTargets fields with no legacy equivalent ---
        'engine_version': serialized['engine_version'],
        'can_start': serialized['can_start'],
        'activity_factor': serialized['activity_factor'],
        'precision': serialized['precision'],
        'pace_status': serialized['pace_status'],
        'calories_clamped': serialized['calories_clamped'],
        'target_protein_g': macros['protein_g'],
        'target_fat_g': macros['fat_g'],
        'target_carbs_g': macros['carbs_g'],
        'messages': serialized['messages'],
    }


def engine_metadata_for_storage(inputs: PlanInputs, serialized: dict) -> dict:
    """The engine output views.py persists onto a new JourneyProgram's
    migration-0013 fields, and returns to the client as the roadmap's
    `engine` sub-object (spec v1.6 section 7.1).

    `serialized` is always `serialization.serialize_plan_targets()`'s own
    output (passed straight through from `compute_mode_targets` -- see its
    docstring), so every value already carries the correct 4.9
    rounding/serialization; this function only selects and relabels keys,
    never re-derives or re-rounds a number itself. It now forwards the full
    `PlanTargets` shape (not just the subset the original, pre-wizard-UI
    roadmap needed) so the client can render spec section 8's full Review
    screen -- pace bar percentage, "why this plan"/"N days needed" line,
    and the suggested-vs-override comparison."""
    macros = serialized['macros'] or {}
    return {
        'inputs': dataclasses.asdict(inputs),
        'engine_version': serialized['engine_version'],
        'can_start': serialized['can_start'],
        'bmr': serialized['bmr'],
        'tdee': serialized['tdee'],
        'activity_factor': serialized['activity_factor'],
        'precision': serialized['precision'],
        'calorie_delta': serialized['calorie_delta'],
        'predicted_weekly_change_kg': serialized['predicted_weekly_change_kg'],
        'predicted_total_change_kg': serialized['predicted_total_change_kg'],
        'projected_end_weight_kg': serialized['projected_end_weight_kg'],
        'weekly_change_pct_bodyweight': serialized['weekly_change_pct_bodyweight'],
        'requested_weekly_change_pct': serialized['requested_weekly_change_pct'],
        'days_needed': serialized['days_needed'],
        'pace_status': serialized['pace_status'],
        'calories_clamped': serialized['calories_clamped'],
        'target_calories': serialized['target_calories'],
        'target_protein_g': macros.get('protein_g'),
        'target_fat_g': macros.get('fat_g'),
        'target_carbs_g': macros.get('carbs_g'),
        'override_source': serialized['override_source'],
        'suggested_calories': serialized['suggested_calories'],
        'suggested_macros': serialized['suggested_macros'],
        'messages': serialized['messages'],
    }
