"""
Pure functions for the guided plan builder: no database access here at all.
Callers (views) fetch the Blueprint model instance and pass plain data in;
these functions only read attributes off that object and off user_inputs.
The one piece of DB-sourced data the volume check (6.4) needs -- exercise
name -> muscle group -- is likewise resolved by the caller (see
`.exercise_lookup`) and passed in as a plain dict; this module never
imports `exercises.models` itself.

Calorie/macro/pace target calculation itself (what used to be this module's
own `calculate_targets` formula, using older constants than spec v1.6
section 4) now lives entirely in `workouts.plan_engine` -- see
`.engine_adapter`, which this module delegates to. `calculate_targets` is
kept as a thin, same-signature wrapper (plans/tests.py and other callers
still call it directly), and the day-by-day roadmap/phase/split-assignment
logic below (section 6 territory) is unchanged except where noted (real
weekdays/dates -- 6.6, phase boundary math -- 6.5, and the volume check --
6.4, added in this pass).
"""
from datetime import timedelta

from django.utils import timezone as django_timezone

from workouts.plan_engine import config as plan_config
from workouts.plan_engine.config import CALORIE_FLOOR_KCAL
from workouts.plan_engine.rounding import round_half_up

from . import engine_adapter

RATE_CAP_KG_PER_WEEK = 1.0

# --- 6.6 real weekdays/dates ------------------------------------------------
# Python's `date.weekday()` is 0=Mon..6=Sun; plans/' own `weekdays` request
# field (and the ordinal convention generate_roadmap has always used
# internally for "which weekday is this") is 1=Mon..7=Sun -- so `ordinal =
# date.weekday() + 1` throughout this module.
WEEKDAY_ABBR = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']  # index 0=Mon

# --- 6.5 phases --------------------------------------------------------------
# One-sentence plain descriptions for the UI (spec 6.5). The seeded
# Blueprint catalog's own `phases` JSON only ever carries name/start_day/
# end_day (see `seed_blueprints.py`), so there is no existing descriptive
# text to preserve -- these are new, generic-but-accurate fallbacks, keyed
# by phase *name* so a blueprint that already supplies its own
# `description` per phase (future content) is used instead (see
# `_phase_boundaries` below).
PHASE_DESCRIPTIONS = {
    'Foundation': 'Build consistent technique and work capacity before the heavier work ahead.',
    'Build': 'Progressively increase training demands as your base adapts.',
    'Peak': 'Push intensity and effort as the plan reaches its final stretch.',
}
DEFAULT_PHASE_DESCRIPTION = 'A phase of this training plan.'

# --- 6.4 volume check ---------------------------------------------------------
# Weekly hard sets per muscle group by experience (spec 6.4; tunable
# defaults -- "recommend a qualified coach review them", not re-litigated
# here). Kept as a standalone config dict, not inline in the check logic.
EXPERIENCE_VOLUME_RANGES = {
    'BEGINNER': (8, 12),
    'INTERMEDIATE': (10, 16),
    'ADVANCED': (12, 20),
}
DEFAULT_EXPERIENCE = 'INTERMEDIATE'

# The same 10 "major" muscle groups the exercise-library audit
# (FITLOG_EXERCISE_AUDIT_v1.md section 1) used for its >=2-exercises gate --
# the ones a typical split would carry a dedicated weekly set target for.
# Traps, Forearms and Cardio are intentionally excluded for the same reason
# the audit excluded them (incidental volume / not a strength-set target).
MAJOR_MUSCLE_GROUPS = (
    'Chest', 'Back', 'Shoulders', 'Quadriceps', 'Hamstrings',
    'Glutes', 'Biceps', 'Triceps', 'Calves', 'Core',
)
VOLUME_OUTSIDE_RANGE_CODE = 'VOLUME_OUTSIDE_RANGE'

# 0.75x the mode's typical safe cap; used only to classify the roadmap's
# display-level "feasibility" label/message (`_assess_feasibility` below).
# This is a separate, simpler heuristic from the engine's own pace bands/
# messages (plan_engine.config.PACE_BANDS_PCT, V-07/PACE_ABOVE_LIMIT) --
# intentionally left as-is; see the implementation report.
MODE_SAFE_THRESHOLD_KG_PER_WEEK = {
    'CUT': 0.75,
    'BULK': 0.75,
    'RECOMP': 0.35,
    'FOCUS': 0.05,
    'HABIT': 0.05,
}

# Direction of weight change implied by each mode (CUT loses, BULK gains, RECOMP trends
# down slightly, FOCUS/HABIT hold steady). Mirrors (without duplicating the inequality
# checks of) `_goal_direction_valid` in workouts.plan_engine.engine, which only validates
# a *given* goal's direction -- there's no existing forward "suggest a goal" helper there.
MODE_GOAL_DIRECTION = {
    'CUT': -1,
    'BULK': 1,
    'RECOMP': -1,
    'FOCUS': 0,
    'HABIT': 0,
}


def recommend_goal_weight(*, mode, current_weight_kg, height_cm, duration_days):
    """Return a conservative, BMI-aware first goal.

    A duration-based pace alone can produce an unsafe suggestion for long
    plans (for example, a year of cutting at 0.75 kg/week). Keep the initial
    recommendation to at most 10% of starting weight and never below the
    standard adult BMI floor. Users can reassess with a clinician after this
    first milestone.
    """
    weeks = duration_days / 7
    pace_delta = MODE_SAFE_THRESHOLD_KG_PER_WEEK[mode] * weeks
    if MODE_GOAL_DIRECTION[mode] < 0:
        max_initial_change = current_weight_kg * 0.10
        delta = min(pace_delta, max_initial_change)
        bmi_floor = plan_config.MIN_GOAL_BMI * (height_cm / 100) ** 2
        return round(max(current_weight_kg - delta, bmi_floor), 1)
    if MODE_GOAL_DIRECTION[mode] > 0:
        delta = min(pace_delta, current_weight_kg * 0.10)
        return round(current_weight_kg + delta, 1)
    return round(current_weight_kg, 1)


def calculate_targets(*, weight_kg, height_cm, age_years, sex, days_per_week, mode,
                       duration_days, goal_weight_kg=None, weekdays=None, activity_level=None):
    """Thin wrapper around the plan_engine (spec v1.6 section 4) -- see
    `.engine_adapter.legacy_shaped_targets` for the exact field mapping.

    `activity_level` (SEDENTARY/LIGHT/MODERATE/HIGH/ATHLETE, matching
    `users.UserProfile.activity_level`) now drives the engine's real TDEE
    multiplier (`plan_engine.config.ACTIVITY_FACTOR_BY_LEVEL`). Previously
    this function returned a cosmetic LIGHT/MODERATE/HIGH/ATHLETE label
    derived purely from `days_per_week` (`activity_level_from_days_per_week`,
    now removed) while the actual TDEE used a *different*, days_per_week-only
    table -- the two never agreed with the real activity level a user might
    report elsewhere in the app (e.g. `nutrition.targets`). Defaults to
    MODERATE when omitted, same as the engine itself.
    """
    _, _, serialized = engine_adapter.compute_mode_targets(
        mode=mode, weight_kg=weight_kg, height_cm=height_cm, age_years=age_years,
        sex=sex, days_per_week=days_per_week, duration_days=duration_days,
        goal_weight_kg=goal_weight_kg, weekdays=weekdays, activity_level=activity_level,
    )
    result = engine_adapter.legacy_shaped_targets(serialized)
    result['activity_level'] = (activity_level or 'MODERATE').upper()
    return result


def _rest_day_targets(training_targets, sex):
    floor = CALORIE_FLOOR_KCAL[str(sex).lower()]
    rest_calories = max(floor, round(training_targets['daily_calories'] * 0.9))
    protein_g = training_targets['protein_g']
    fat_g = training_targets['fat_g']
    carbs_g = max(0, round((rest_calories - protein_g * 4 - fat_g * 9) / 4))
    return {
        'daily_calories': rest_calories,
        'protein_g': protein_g,
        'carbs_g': carbs_g,
        'fat_g': fat_g,
    }


def _assess_feasibility(mode, current_weight_kg, goal_weight_kg, duration_days, warnings):
    if goal_weight_kg is None or not duration_days:
        implied_rate = 0.0
    else:
        weeks = duration_days / 7
        implied_rate = (goal_weight_kg - current_weight_kg) / weeks if weeks else 0.0

    floor_forced = any('floor' in w.lower() for w in warnings)
    safe_threshold = MODE_SAFE_THRESHOLD_KG_PER_WEEK[mode]

    if abs(implied_rate) > RATE_CAP_KG_PER_WEEK or floor_forced:
        status = 'unrealistic'
        message = (
            f"The requested pace ({implied_rate:.2f} kg/week) is not realistic for {mode} mode "
            f"over {duration_days} days."
        )
    elif abs(implied_rate) > safe_threshold:
        status = 'aggressive'
        message = (
            f"The requested pace ({implied_rate:.2f} kg/week) is aggressive for {mode} mode; "
            "proceed with caution and monitor recovery."
        )
    else:
        # Spec v1.6 section 9 copy rule: never "safe" -- "within the typical
        # range" and "estimate" instead. `status` itself is part of that
        # copy (surfaced verbatim as `roadmap.feasibility.status`), not just
        # `message`, so the label changes too; the threshold/classification
        # logic above is unchanged.
        status = 'within_typical_range'
        message = (
            f"The requested pace ({implied_rate:.2f} kg/week) is within the typical range for {mode} mode. "
            "This is an estimate."
        )

    return {'status': status, 'message': message}


def _even_boundaries(phase_count, duration_days):
    """Fallback for a blueprint that defines a phase count other than the
    spec's usual 3 (Foundation/Build/Peak) -- split `duration_days` as
    evenly as round_half_up allows, guaranteeing a strictly increasing,
    in-range sequence of end days."""
    boundaries = []
    previous = 0
    for i in range(1, phase_count + 1):
        end_day = round_half_up(duration_days * i / phase_count)
        end_day = max(previous + 1, min(end_day, duration_days - (phase_count - i)))
        boundaries.append(end_day)
        previous = end_day
    boundaries[-1] = duration_days
    return boundaries


def _phase_boundaries(phases, duration_days):
    """Spec v1.6 section 6.5: `foundation_end = round_half_up(0.30 *
    duration_days)`, `build_end = round_half_up(0.70 * duration_days)` --
    computed directly from the plan's own requested `duration_days` (never
    proportionally scaled from the blueprint's own default-duration
    boundaries, and never Python's banker's-rounding `round()`; see
    `workouts.plan_engine.rounding.round_half_up`).

    Phase *names* (and descriptive text, where a blueprint already supplies
    its own) still come from `phases` -- only the day-boundary math and any
    missing description are replaced/filled in here.
    """
    if not phases:
        return [{
            'name': 'Full Program', 'start_day': 1, 'end_day': duration_days,
            'description': DEFAULT_PHASE_DESCRIPTION,
        }]

    if len(phases) == 3:
        # Computed as `duration_days * 3 / 10` / `* 7 / 10` (integer
        # multiply, then a single true-divide), NOT `0.30 * duration_days` /
        # `0.70 * duration_days`: multiplying by the float literals 0.30/
        # 0.70 first picks up IEEE754 binary rounding error for many
        # duration_days values (e.g. 0.70 * 45 == 31.499999999999996, not
        # 31.5), which round_half_up then faithfully rounds DOWN to a wrong
        # 31 instead of the spec's intended 32. `duration_days * 7` is an
        # exact integer, and a single true-divide by 10 is correctly
        # rounded, so this form always matches the exact (Decimal) value of
        # 0.30/0.70 * duration_days -- verified for every duration_days in
        # 7..365.
        foundation_end = round_half_up(duration_days * 3 / 10)
        build_end = round_half_up(duration_days * 7 / 10)
        # Guard rails for very short durations so no phase ever ends up
        # zero-length or past duration_days (spec 6.6: "handle ... without
        # crashing or producing a negative-length week" applies equally
        # here to phases).
        foundation_end = max(1, min(foundation_end, duration_days - 2))
        build_end = max(foundation_end + 1, min(build_end, duration_days - 1))
        end_days = [foundation_end, build_end, duration_days]
    else:
        end_days = _even_boundaries(len(phases), duration_days)

    scaled = []
    running_start = 1
    for phase, end_day in zip(phases, end_days):
        name = phase.get('name', 'Phase')
        scaled.append({
            'name': name,
            'start_day': running_start,
            'end_day': end_day,
            'description': phase.get('description') or PHASE_DESCRIPTIONS.get(name, DEFAULT_PHASE_DESCRIPTION),
        })
        running_start = end_day + 1
    return scaled


def _phase_name_for_day(scaled_phases, day_number):
    for phase in scaled_phases:
        if phase['start_day'] <= day_number <= phase['end_day']:
            return phase['name']
    return scaled_phases[-1]['name'] if scaled_phases else ''


def resolve_workout_templates(blueprint, training_split=None):
    """The split's `workout_templates` (or the blueprint's own fallback
    content when no `TrainingSplit` is attached) plus which object it came
    from -- shared by `generate_roadmap` and by `views.py`, which needs the
    same templates to collect exercise names for the muscle-group lookup
    (see `.exercise_lookup`) before calling `generate_roadmap`."""
    split_source = training_split or blueprint.default_training_split
    workout_templates = (split_source.workout_templates if split_source else blueprint.workout_templates) or {}
    return split_source, workout_templates


def exercise_names_in_workout_templates(workout_templates):
    """Every distinct `exercise_name` referenced anywhere in a
    `workout_templates` dict (pure; no DB access -- see `.exercise_lookup`
    for the caller that turns this into a muscle-group mapping)."""
    names = set()
    for day_exercises in (workout_templates or {}).values():
        for entry in day_exercises or []:
            name = entry.get('exercise_name')
            if name:
                names.add(name)
    return names


def _resolve_anchor_date(explicit_start_date, training_weekdays, today=None):
    """Spec v1.6 section 6.6: the engine takes an injected `start_date`;
    when none is given, default to the first selected training weekday on
    or after today. `today` is itself injectable (callers pass plain data
    in; the one caller that needs a real "today" -- `views.py` -- gets it
    from `django.utils.timezone.localdate()`, which already resolves
    against the request's active timezone via `core.middleware.
    TimezoneMiddleware`, so no new timezone mechanism is introduced here).
    """
    if explicit_start_date is not None:
        return explicit_start_date

    reference = today if today is not None else django_timezone.localdate()
    if not training_weekdays:
        return reference

    weekday_set = set(training_weekdays)
    for offset in range(7):
        candidate = reference + timedelta(days=offset)
        if (candidate.weekday() + 1) in weekday_set:  # ordinal: 1=Mon..7=Sun
            return candidate
    return reference  # unreachable while training_weekdays is non-empty


def _weekly_volume_by_muscle_group(workout_by_weekday, muscle_group_by_exercise):
    """Total weekly hard sets per muscle group actually scheduled, summed
    across one full week of `workout_by_weekday` (one list of exercise
    picks per distinct real training weekday -- see `generate_roadmap`).
    Cardio entries and exercises the lookup can't resolve to a muscle group
    (an unknown name, or no `muscle_group_by_exercise` supplied at all)
    contribute no volume rather than raising -- see `.exercise_lookup`."""
    totals = {}
    lookup = muscle_group_by_exercise or {}
    for day_exercises in (workout_by_weekday or {}).values():
        for entry in day_exercises or []:
            if entry.get('is_cardio'):
                continue
            muscle_group = lookup.get(entry.get('exercise_name'))
            if not muscle_group:
                continue
            totals[muscle_group] = totals.get(muscle_group, 0) + (entry.get('sets') or 0)
    return totals


def _volume_check(workout_by_weekday, muscle_group_by_exercise, experience):
    """Spec v1.6 section 6.4: compare weekly hard sets per muscle group
    against the experience-tiered range (`EXPERIENCE_VOLUME_RANGES`).
    Detect-and-warn only, matching the spec's own fallback ("If the days
    available make it impossible, emit info VOLUME_OUTSIDE_RANGE naming the
    group") -- no auto-fix/auto-balance (accessory add/remove) is
    implemented; that's explicitly out of scope for this pass."""
    totals = _weekly_volume_by_muscle_group(workout_by_weekday, muscle_group_by_exercise)
    low, high = EXPERIENCE_VOLUME_RANGES.get(experience, EXPERIENCE_VOLUME_RANGES[DEFAULT_EXPERIENCE])
    messages = []
    for muscle_group in MAJOR_MUSCLE_GROUPS:
        weekly_sets = totals.get(muscle_group, 0)
        if weekly_sets < low or weekly_sets > high:
            messages.append({
                'code': VOLUME_OUTSIDE_RANGE_CODE,
                'severity': 'info',
                'params': {
                    'muscle_group': muscle_group,
                    'weekly_sets': weekly_sets,
                    'min_sets': low,
                    'max_sets': high,
                    'experience': experience,
                },
            })
    return totals, messages


def generate_roadmap(blueprint, user_inputs, training_split=None, muscle_group_by_exercise=None):
    duration_days = user_inputs['duration_days']
    days_per_week = user_inputs['days_per_week']
    weekdays = user_inputs.get('weekdays') or []
    current_weight_kg = user_inputs['current_weight_kg']
    goal_weight_kg = user_inputs.get('goal_weight_kg')
    height_cm = user_inputs['height_cm']
    age = user_inputs['age']
    sex = user_inputs['sex']
    experience = (user_inputs.get('experience') or DEFAULT_EXPERIENCE).upper()
    mode = blueprint.mode

    engine_inputs, _engine_targets, engine_serialized = engine_adapter.compute_mode_targets(
        mode=mode,
        weight_kg=current_weight_kg,
        height_cm=height_cm,
        age_years=age,
        sex=sex,
        days_per_week=days_per_week,
        duration_days=duration_days,
        goal_weight_kg=goal_weight_kg,
        weekdays=weekdays,
        # Spec v1.6 sections 4.3/4.8/6.2: previously dropped on the floor at
        # this call site -- `experience` is already computed above (shared
        # with the 6.4 volume check); the rest come straight from the
        # request (`user_inputs`, i.e. the serializer's validated_data).
        experience=experience,
        equipment=user_inputs.get('equipment_level'),
        activity_level=user_inputs.get('activity_level'),
        recomp_direction=user_inputs.get('recomp_direction'),
        calorie_override=user_inputs.get('calorie_override'),
        macro_override=user_inputs.get('macro_override'),
        override_for_mode=user_inputs.get('override_for_mode'),
    )
    training_targets = engine_adapter.legacy_shaped_targets(engine_serialized)
    warnings = list(training_targets['warnings'])

    training_day_targets = {
        'daily_calories': training_targets['daily_calories'],
        'protein_g': training_targets['protein_g'],
        'carbs_g': training_targets['carbs_g'],
        'fat_g': training_targets['fat_g'],
    }
    rest_day_targets = _rest_day_targets(training_targets, sex)

    feasibility = _assess_feasibility(mode, current_weight_kg, goal_weight_kg, duration_days, warnings)
    if feasibility['status'] != 'within_typical_range':
        warnings.append(feasibility['message'])

    scaled_phases = _phase_boundaries(blueprint.phases, duration_days)

    split_source, workout_templates = resolve_workout_templates(blueprint, training_split)
    # The blueprint's day_1..day_7 keys are just an ordered list of its own workout
    # splits, not literal calendar weekdays. When the member picks a different weekday
    # set (or a different days_per_week) than the blueprint's own default, matching by
    # weekday number would leave some chosen training days without any of the
    # blueprint's real content. Instead, spread the blueprint's actual non-empty splits
    # across whichever weekdays are training days, cycling if there are more training
    # days than splits.
    ordered_splits = [workout_templates[f'day_{i}'] for i in range(1, 8) if workout_templates.get(f'day_{i}')]

    if weekdays:
        training_weekdays = sorted(set(weekdays))
    else:
        training_weekdays = [i for i in range(1, 8) if workout_templates.get(f'day_{i}')]
    training_weekdays_set = set(training_weekdays)

    workout_by_weekday = {
        wd: ordered_splits[idx % len(ordered_splits)]
        for idx, wd in enumerate(training_weekdays)
    } if ordered_splits else {}

    volume_totals, volume_messages = _volume_check(workout_by_weekday, muscle_group_by_exercise, experience)
    for message in volume_messages:
        params = message['params']
        warnings.append(
            f"{params['muscle_group']} gets {params['weekly_sets']} hard sets/week on this schedule, "
            f"outside the {params['experience'].title()} range of {params['min_sets']}-{params['max_sets']}."
        )

    # 6.6: real weekdays and dates. `start_date` is injected (spec wording)
    # via user_inputs; when absent, default to the first selected training
    # weekday on or after "today" (also injectable via user_inputs['today'],
    # used by tests -- the real caller, views.py, never sets it and gets
    # django.utils.timezone.localdate() instead).
    anchor_date = _resolve_anchor_date(
        user_inputs.get('start_date'), training_weekdays, today=user_inputs.get('today')
    )

    days = []
    for day_number in range(1, duration_days + 1):
        current_date = anchor_date + timedelta(days=day_number - 1)
        weekday_ordinal = current_date.weekday() + 1  # 1=Mon..7=Sun
        is_training = weekday_ordinal in training_weekdays_set
        is_rest = not is_training
        workout = None if is_rest else workout_by_weekday.get(weekday_ordinal)
        phase_name = _phase_name_for_day(scaled_phases, day_number)
        targets = rest_day_targets if is_rest else training_day_targets

        weekday_abbr = WEEKDAY_ABBR[current_date.weekday()]
        date_label = f"{weekday_abbr} {current_date.day} {current_date.strftime('%b')}"
        session_name = 'Rest Day' if is_rest else phase_name
        label = f"{date_label}: {session_name}"

        if goal_weight_kg is not None and duration_days > 1:
            frac = (day_number - 1) / (duration_days - 1)
            expected_weight_kg = current_weight_kg + (goal_weight_kg - current_weight_kg) * frac
        else:
            expected_weight_kg = current_weight_kg

        days.append({
            'day_number': day_number,
            'date': current_date,
            'weekday': weekday_abbr,
            'label': label,
            'phase': phase_name,
            'is_rest': is_rest,
            'workout': workout,
            'targets': targets,
            'expected_weight_kg': round(expected_weight_kg, 2),
        })

    summary = {
        'duration_days': duration_days,
        'workouts_per_week': days_per_week,
        'start_date': anchor_date,
        'start_weight_kg': current_weight_kg,
        'goal_weight_kg': goal_weight_kg,
        'daily_calories': training_targets['daily_calories'],
        'weekly_rate_kg': training_targets['weekly_rate_kg'],
        'training_split': split_source.slug if split_source else None,
    }

    return {
        'summary': summary,
        'feasibility': feasibility,
        'phases': scaled_phases,
        'days': days,
        'meal_template': blueprint.meal_templates,
        'targets': {'training_day': training_day_targets, 'rest_day': rest_day_targets},
        'warnings': warnings,
        # Additive (spec v1.6 section 6.4): weekly hard sets per muscle
        # group actually scheduled, plus the structured VOLUME_OUTSIDE_RANGE
        # messages (also folded into `warnings` above as readable text).
        'volume': {
            'experience': experience,
            'weekly_sets_by_muscle_group': volume_totals,
            'messages': volume_messages,
        },
        # Additive (spec v1.6 section 7.1): the full engine inputs/outputs,
        # not read by any pre-existing roadmap consumer -- only by the
        # JourneyProgram-creation path in views.py, which persists this onto
        # the migration-0013 fields.
        'engine': engine_adapter.engine_metadata_for_storage(engine_inputs, engine_serialized),
    }
