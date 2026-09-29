"""
Pure functions for the guided plan builder: no database access here at all.
Callers (views) fetch the Blueprint model instance and pass plain data in;
these functions only read attributes off that object and off user_inputs.
"""
from nutrition.targets import mifflin_st_jeor_bmr, ACTIVITY_FACTORS, MIN_CALORIES

KCAL_PER_KG_FAT = 7700
BULK_SURPLUS_KCAL = 275
RATE_CAP_KG_PER_WEEK = 1.0

MODE_DEFAULT_WEEKLY_RATE = {
    'CUT': -0.5,
    'BULK': 0.3,
    'RECOMP': -0.15,
    'FOCUS': 0.0,
    'HABIT': 0.0,
}

MODE_PROTEIN_G_PER_KG = {
    'CUT': 2.2,
    'RECOMP': 2.2,
    'FOCUS': 2.0,
    'BULK': 1.8,
    'HABIT': 1.8,
}

FAT_G_PER_KG = 0.9

# 0.75x the mode's typical safe cap; used to classify feasibility.
MODE_SAFE_THRESHOLD_KG_PER_WEEK = {
    'CUT': 0.75,
    'BULK': 0.75,
    'RECOMP': 0.35,
    'FOCUS': 0.05,
    'HABIT': 0.05,
}


def activity_level_from_days_per_week(days_per_week):
    if days_per_week <= 2:
        return 'LIGHT'
    if days_per_week <= 4:
        return 'MODERATE'
    if days_per_week <= 6:
        return 'HIGH'
    return 'ATHLETE'


def calculate_targets(*, weight_kg, height_cm, age_years, sex, days_per_week, mode,
                       duration_days, goal_weight_kg=None):
    warnings = []
    bmr = mifflin_st_jeor_bmr(weight_kg, height_cm, age_years, sex)
    activity_level = activity_level_from_days_per_week(days_per_week)
    tdee = bmr * ACTIVITY_FACTORS[activity_level]

    weekly_rate_kg = 0.0
    if mode in ('CUT', 'BULK', 'RECOMP'):
        default_rate = MODE_DEFAULT_WEEKLY_RATE[mode]
        if goal_weight_kg is not None and duration_days:
            weeks = duration_days / 7
            weekly_rate_kg = (goal_weight_kg - weight_kg) / weeks if weeks else default_rate
        else:
            weekly_rate_kg = default_rate

        if abs(weekly_rate_kg) > RATE_CAP_KG_PER_WEEK:
            warnings.append(
                f"Requested pacing of {weekly_rate_kg:.2f} kg/week was clamped to "
                f"{RATE_CAP_KG_PER_WEEK if weekly_rate_kg > 0 else -RATE_CAP_KG_PER_WEEK} kg/week for safety."
            )
            weekly_rate_kg = RATE_CAP_KG_PER_WEEK if weekly_rate_kg > 0 else -RATE_CAP_KG_PER_WEEK

        if mode == 'CUT' and weekly_rate_kg < 0 and abs(weekly_rate_kg) > 0.01 * weight_kg:
            warnings.append(
                f"Requested weekly loss ({abs(weekly_rate_kg):.2f} kg) exceeds 1% of bodyweight "
                f"per week ({0.01 * weight_kg:.2f} kg)."
            )

    if mode in ('CUT', 'RECOMP'):
        daily_deficit = weekly_rate_kg * KCAL_PER_KG_FAT / 7
        calories = tdee + daily_deficit
    elif mode == 'BULK':
        calories = tdee + BULK_SURPLUS_KCAL
    else:
        calories = tdee

    floor = MIN_CALORIES[sex]
    if calories < floor:
        warnings.append(
            f"Calculated calories ({round(calories)}) were below the safe floor; raised to {floor}."
        )
        calories = floor

    protein_g = round(MODE_PROTEIN_G_PER_KG[mode] * weight_kg)
    fat_g = round(FAT_G_PER_KG * weight_kg)
    carbs_g = max(0, round((calories - protein_g * 4 - fat_g * 9) / 4))

    return {
        'tdee': round(tdee),
        'bmr': round(bmr),
        'activity_level': activity_level,
        'daily_calories': round(calories),
        'protein_g': protein_g,
        'carbs_g': carbs_g,
        'fat_g': fat_g,
        'weekly_rate_kg': round(weekly_rate_kg, 3),
        'warnings': warnings,
    }


def _rest_day_targets(training_targets, sex):
    rest_calories = max(MIN_CALORIES[sex], round(training_targets['daily_calories'] * 0.9))
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
            f"The requested pace ({implied_rate:.2f} kg/week) is not realistic or safe for {mode} mode "
            f"over {duration_days} days."
        )
    elif abs(implied_rate) > safe_threshold:
        status = 'aggressive'
        message = (
            f"The requested pace ({implied_rate:.2f} kg/week) is aggressive for {mode} mode; "
            "proceed with caution and monitor recovery."
        )
    else:
        status = 'safe'
        message = f"The requested pace ({implied_rate:.2f} kg/week) is within safe limits for {mode} mode."

    return {'status': status, 'message': message}


def _scale_phases(phases, default_duration_days, duration_days):
    if not phases or not default_duration_days:
        return [{'name': 'Full Program', 'start_day': 1, 'end_day': duration_days}]

    ratio = duration_days / default_duration_days
    scaled = []
    running_start = 1
    n = len(phases)
    for i, phase in enumerate(phases):
        if i == n - 1:
            end_day = duration_days
        else:
            end_day = max(running_start, min(round(phase['end_day'] * ratio), duration_days - (n - i - 1)))
        scaled.append({'name': phase['name'], 'start_day': running_start, 'end_day': end_day})
        running_start = end_day + 1
    return scaled


def _phase_name_for_day(scaled_phases, day_number):
    for phase in scaled_phases:
        if phase['start_day'] <= day_number <= phase['end_day']:
            return phase['name']
    return scaled_phases[-1]['name'] if scaled_phases else ''


def generate_roadmap(blueprint, user_inputs):
    duration_days = user_inputs['duration_days']
    days_per_week = user_inputs['days_per_week']
    weekdays = user_inputs.get('weekdays') or []
    current_weight_kg = user_inputs['current_weight_kg']
    goal_weight_kg = user_inputs.get('goal_weight_kg')
    height_cm = user_inputs['height_cm']
    age = user_inputs['age']
    sex = user_inputs['sex']
    mode = blueprint.mode

    training_targets = calculate_targets(
        weight_kg=current_weight_kg,
        height_cm=height_cm,
        age_years=age,
        sex=sex,
        days_per_week=days_per_week,
        mode=mode,
        duration_days=duration_days,
        goal_weight_kg=goal_weight_kg,
    )
    warnings = list(training_targets['warnings'])

    training_day_targets = {
        'daily_calories': training_targets['daily_calories'],
        'protein_g': training_targets['protein_g'],
        'carbs_g': training_targets['carbs_g'],
        'fat_g': training_targets['fat_g'],
    }
    rest_day_targets = _rest_day_targets(training_targets, sex)

    feasibility = _assess_feasibility(mode, current_weight_kg, goal_weight_kg, duration_days, warnings)
    if feasibility['status'] != 'safe':
        warnings.append(feasibility['message'])

    scaled_phases = _scale_phases(blueprint.phases, blueprint.default_duration_days, duration_days)

    weekday_set = set(weekdays) if weekdays else None
    workout_templates = blueprint.workout_templates or {}

    def is_training_weekday(weekday):
        if weekday_set is not None:
            return weekday in weekday_set
        return bool(workout_templates.get(f'day_{weekday}'))

    days = []
    for day_number in range(1, duration_days + 1):
        weekday = ((day_number - 1) % 7) + 1
        is_training = is_training_weekday(weekday)
        is_rest = not is_training
        workout = None if is_rest else workout_templates.get(f'day_{weekday}')
        phase_name = _phase_name_for_day(scaled_phases, day_number)
        targets = rest_day_targets if is_rest else training_day_targets

        if goal_weight_kg is not None and duration_days > 1:
            frac = (day_number - 1) / (duration_days - 1)
            expected_weight_kg = current_weight_kg + (goal_weight_kg - current_weight_kg) * frac
        else:
            expected_weight_kg = current_weight_kg

        days.append({
            'day_number': day_number,
            'phase': phase_name,
            'is_rest': is_rest,
            'workout': workout,
            'targets': targets,
            'expected_weight_kg': round(expected_weight_kg, 2),
        })

    summary = {
        'duration_days': duration_days,
        'workouts_per_week': days_per_week,
        'start_weight_kg': current_weight_kg,
        'goal_weight_kg': goal_weight_kg,
        'daily_calories': training_targets['daily_calories'],
        'weekly_rate_kg': training_targets['weekly_rate_kg'],
    }

    return {
        'summary': summary,
        'feasibility': feasibility,
        'phases': scaled_phases,
        'days': days,
        'meal_template': blueprint.meal_templates,
        'targets': {'training_day': training_day_targets, 'rest_day': rest_day_targets},
        'warnings': warnings,
    }
