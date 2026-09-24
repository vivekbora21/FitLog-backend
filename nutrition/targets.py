"""
Derives calorie and macro targets from the user's profile instead of relying on
hand-typed numbers: Mifflin-St Jeor BMR -> activity-scaled TDEE -> goal adjustment.

Reference point (Diet Plan sheet): 31 y/o male, 77.76 kg, ~174.5 cm, moderate
activity -> BMR ~1,718 kcal, maintenance ~2,660 kcal, ~500 kcal deficit -> 2,160 kcal,
165 g protein (2.1 g/kg).
"""
from datetime import date

from progress.models import WeightEntry
from workouts.models import JourneyProgram
from .defaults import DEFAULT_MACRO_TARGETS, DEFAULT_LIFESTYLE_TARGETS
from .models import MacroTarget, TargetHistory, TargetValues

ACTIVITY_FACTORS = {
    'SEDENTARY': 1.2,
    'LIGHT': 1.375,
    'MODERATE': 1.55,
    'HIGH': 1.725,
    'ATHLETE': 1.9,
}

# An active journey's mode is the most specific statement of intent, so it wins
# over the coarser profile fitness_goal.
MODE_CALORIE_ADJUSTMENT = {
    'CUT': -500,
    'RECOMP': -250,
    'BULK': 300,
    'FOCUS': 0,
    'HABIT': 0,
}
GOAL_CALORIE_ADJUSTMENT = {
    'FAT_LOSS': -500,
    'HYPERTROPHY': 250,
    'STRENGTH': 250,
    'ENDURANCE': 0,
    'GENERAL_FITNESS': 0,
}

MODE_PROTEIN_G_PER_KG = {
    'CUT': 2.1,
    'RECOMP': 2.1,
    'BULK': 1.8,
    'FOCUS': 1.8,
    'HABIT': 1.6,
}
GOAL_PROTEIN_G_PER_KG = {
    'FAT_LOSS': 2.1,
    'HYPERTROPHY': 1.8,
    'STRENGTH': 1.8,
    'ENDURANCE': 1.6,
    'GENERAL_FITNESS': 1.6,
}

FAT_SHARE_OF_CALORIES = 0.25
# Never recommend eating below this, whatever the arithmetic says.
MIN_CALORIES = {'MALE': 1500, 'FEMALE': 1200}


def mifflin_st_jeor_bmr(weight_kg, height_cm, age_years, sex):
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age_years
    return base + 5 if sex == 'MALE' else base - 161


def _age_on(dob, today):
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def calculate_recommended_targets(user, today=None):
    """
    Returns a dict with the full derivation (so the UI can show where the number
    comes from), or {'available': False, 'missing': [...]} if the profile is incomplete.
    """
    today = today or date.today()
    profile = getattr(user, 'profile', None)

    latest_weight = WeightEntry.objects.filter(user=user).order_by('-date').first()
    weight_kg = latest_weight.weight_kg if latest_weight else (profile.weight_kg if profile else None)
    weight_source = 'latest weigh-in' if latest_weight else 'profile'

    missing = []
    if not weight_kg:
        missing.append('weight')
    if not profile or not profile.height_cm:
        missing.append('height_cm')
    if not profile or not profile.date_of_birth:
        missing.append('date_of_birth')
    if not profile or profile.sex not in ('MALE', 'FEMALE'):
        missing.append('sex')
    if missing:
        return {'available': False, 'missing': missing}

    age = _age_on(profile.date_of_birth, today)
    bmr = mifflin_st_jeor_bmr(weight_kg, profile.height_cm, age, profile.sex)
    activity_level = profile.activity_level if profile.activity_level in ACTIVITY_FACTORS else 'MODERATE'
    activity_factor = ACTIVITY_FACTORS[activity_level]
    tdee = bmr * activity_factor

    program = JourneyProgram.objects.filter(user=user, active=True).first()
    if program and program.mode in MODE_CALORIE_ADJUSTMENT:
        goal_source = f"{dict(JourneyProgram.MODE_CHOICES).get(program.mode, program.mode)} (active journey)"
        adjustment = MODE_CALORIE_ADJUSTMENT[program.mode]
        protein_per_kg = MODE_PROTEIN_G_PER_KG[program.mode]
    else:
        goal = profile.fitness_goal
        goal_source = f"{dict(profile.GOAL_CHOICES).get(goal, goal)} (profile goal)"
        adjustment = GOAL_CALORIE_ADJUSTMENT.get(goal, 0)
        protein_per_kg = GOAL_PROTEIN_G_PER_KG.get(goal, 1.6)

    calories = max(MIN_CALORIES[profile.sex], round((tdee + adjustment) / 10) * 10)
    protein_g = round(weight_kg * protein_per_kg)
    fat_g = round(calories * FAT_SHARE_OF_CALORIES / 9)
    carbs_g = max(0, round((calories - protein_g * 4 - fat_g * 9) / 4))

    return {
        'available': True,
        'inputs': {
            'weight_kg': round(weight_kg, 2),
            'weight_source': weight_source,
            'height_cm': profile.height_cm,
            'age_years': age,
            'sex': profile.sex,
            'activity_level': activity_level,
        },
        'bmr': round(bmr),
        'activity_factor': activity_factor,
        'tdee': round(tdee),
        'goal_source': goal_source,
        'calorie_adjustment': adjustment,
        'protein_g_per_kg': protein_per_kg,
        'daily_calories': calories,
        'protein_g': protein_g,
        'carbs_g': carbs_g,
        'fat_g': fat_g,
    }


def get_or_create_macro_target(user):
    """
    Like MacroTarget.objects.get_or_create, but a brand-new target starts from the
    profile-derived recommendation (when the profile is complete) instead of the
    model's generic defaults. Existing targets are never touched.
    """
    target = MacroTarget.objects.filter(user=user).first()
    if target:
        return target
    rec = calculate_recommended_targets(user)
    defaults = {}
    if rec['available']:
        defaults = {k: rec[k] for k in ('daily_calories', 'protein_g', 'carbs_g', 'fat_g')}
    target, _ = MacroTarget.objects.get_or_create(user=user, defaults=defaults)
    return target


# ---------------------------------------------------------------------------
# Member-editable targets: plan-derived values, edits, guardrails and history.
# ---------------------------------------------------------------------------

# Hard limits: values outside these are rejected. Everything else only warns.
TARGET_LIMITS = {
    'protein_g': (0, 400),
    'carbs_g': (0, 1000),
    'fat_g': (0, 300),
    'water_ml': (500, 8000),
    'daily_steps': (0, 50000),
    'sleep_hours': (4, 12),
    'weekly_workouts': (1, 14),
    'weekly_cardio_minutes': (0, 1500),
}
MAX_CALORIES = 6000
KCAL_PER_G = {'protein_g': 4, 'carbs_g': 4, 'fat_g': 9}


def plan_weekly_workouts(program):
    """Required (non-optional) sessions in the plan's first week; 5 without a plan."""
    if program and program.id:
        count = program.days.filter(day_number__lte=7, is_optional=False).count()
        if count:
            return count
    return 5


def plan_weekly_cardio(program, day=None):
    return program.cardio_target_for_day(day) if program else 120


def weekly_workouts_target(values, program):
    return values.weekly_workouts or plan_weekly_workouts(program)


def weekly_cardio_target(values, program, day=None):
    if values.weekly_cardio_minutes is not None:
        return values.weekly_cardio_minutes
    return plan_weekly_cardio(program, day)


def sleep_target_label(hours):
    """Keeps the workbook's Pillar 7 wording for the default target."""
    return '7.5–8.5h' if hours == DEFAULT_LIFESTYLE_TARGETS['sleep_hours'] else f"{hours:g}h"


def steps_target_label(steps):
    """Keeps the workbook's Pillar 9 wording for the default target."""
    return '8,000–10,000' if steps == DEFAULT_LIFESTYLE_TARGETS['daily_steps'] else f"{steps:,}"


class TargetTimeline:
    """Resolves which targets applied on a given day (see TargetHistory)."""

    def __init__(self, user):
        self.current = get_or_create_macro_target(user)
        self.entries = list(TargetHistory.objects.filter(user=user).order_by('effective_from'))

    def on(self, day):
        chosen = None
        for entry in self.entries:
            if entry.effective_from > day:
                break
            chosen = entry
        # Days before the first recorded change use the earliest known targets.
        return chosen or (self.entries[0] if self.entries else self.current)


def _calorie_floor(user):
    profile = getattr(user, 'profile', None)
    sex = profile.sex if profile and profile.sex in MIN_CALORIES else 'FEMALE'
    return MIN_CALORIES[sex]


def resolve_target_update(target, data):
    """
    Applies a partial edit without saving. Carbs are the balancing macro: when
    protein, fat or calories change and carbs weren't sent, carbs absorb the
    calorie difference so the macros keep adding up to the same total as before.

    Returns (values, adjustments, errors).
    """
    values = target.values()
    errors = {}
    sent = {}
    for field in TargetValues.FIELDS:
        if field not in data:
            continue
        raw = data[field]
        if raw in (None, '') and field in ('weekly_workouts', 'weekly_cardio_minutes'):
            sent[field] = None
            continue
        try:
            sent[field] = float(raw) if field == 'sleep_hours' else int(round(float(raw)))
        except (TypeError, ValueError):
            errors[field] = 'Enter a number.'

    floor = _calorie_floor(target.user)
    for field, value in sent.items():
        if value is None:
            continue
        low, high = (floor, MAX_CALORIES) if field == 'daily_calories' else TARGET_LIMITS[field]
        if not low <= value <= high:
            errors[field] = f"Must be between {low:,} and {high:,}." if field != 'sleep_hours' else f"Must be between {low} and {high} hours."
    if errors:
        return values, [], errors

    adjustments = []
    if 'carbs_g' not in sent:
        kcal_delta = sum((sent[f] - values[f]) * KCAL_PER_G[f] for f in ('protein_g', 'fat_g') if f in sent)
        if 'daily_calories' in sent:
            kcal_delta -= sent['daily_calories'] - values['daily_calories']
        if kcal_delta:
            new_carbs = round(values['carbs_g'] - kcal_delta / 4)
            if new_carbs < 0:
                errors['carbs_g'] = "Protein and fat already use up the calorie target; lower them or raise calories."
                return values, [], errors
            adjustments.append(
                f"Carbs adjusted from {values['carbs_g']} g to {new_carbs} g to keep the calorie target balanced."
            )
            sent['carbs_g'] = new_carbs

    values.update(sent)
    return values, adjustments, errors


def target_warnings(user, values, recommended=None):
    """Soft guardrails: the member can still save these."""
    warnings = []
    latest = WeightEntry.objects.filter(user=user).order_by('-date').first()
    profile = getattr(user, 'profile', None)
    weight_kg = latest.weight_kg if latest else (profile.weight_kg if profile else None)

    def warn(field, message):
        warnings.append({'field': field, 'message': message})

    if weight_kg:
        per_kg = values['protein_g'] / weight_kg
        if per_kg < 1.2:
            warn('protein_g', f"{per_kg:.1f} g/kg is low for training; 1.6–2.2 g/kg protects muscle.")
        elif per_kg > 2.5:
            warn('protein_g', f"{per_kg:.1f} g/kg is above the useful range (1.6–2.2 g/kg); the extra mostly displaces carbs.")

    calories = values['daily_calories']
    if calories and values['fat_g'] * 9 / calories < 0.2:
        warn('fat_g', "Fat under 20% of calories can affect hormones; 25% is a common floor.")
    macro_kcal = values['protein_g'] * 4 + values['carbs_g'] * 4 + values['fat_g'] * 9
    if calories and abs(macro_kcal - calories) / calories > 0.1:
        warn('daily_calories', f"Your macros add up to {macro_kcal:,} kcal, not {calories:,} kcal.")
    if recommended and recommended.get('available'):
        tdee = recommended['tdee']
        if calories < tdee - 1000:
            warn('daily_calories', f"That's {tdee - calories:,} kcal under your ~{tdee:,} kcal maintenance; deficits over 1,000 kcal risk muscle loss.")
        elif calories > tdee + 750:
            warn('daily_calories', f"That's {calories - tdee:,} kcal over your ~{tdee:,} kcal maintenance; most of the extra becomes fat.")

    if values['sleep_hours'] < 7:
        warn('sleep_hours', "Under 7h a night slows recovery and strength gains.")
    if values['water_ml'] < 2000:
        warn('water_ml', "Under 2 L a day is low for someone training.")
    if values['weekly_workouts'] and values['weekly_workouts'] > 6:
        warn('weekly_workouts', "More than 6 sessions a week leaves little time to recover.")
    return warnings


def suggested_targets(user, recommended=None, program=None):
    """What each target would be without the member's edits."""
    recommended = recommended if recommended is not None else calculate_recommended_targets(user)
    if program is None:
        program = JourneyProgram.objects.filter(user=user, active=True).first()
    suggested = {
        'water_ml': DEFAULT_MACRO_TARGETS['water_ml'],
        'daily_steps': DEFAULT_LIFESTYLE_TARGETS['daily_steps'],
        'sleep_hours': DEFAULT_LIFESTYLE_TARGETS['sleep_hours'],
        'weekly_workouts': plan_weekly_workouts(program),
        'weekly_cardio_minutes': plan_weekly_cardio(program),
    }
    if recommended.get('available'):
        suggested.update({k: recommended[k] for k in ('daily_calories', 'protein_g', 'carbs_g', 'fat_g')})
    return suggested


def targets_payload(user, values=None, adjustments=None):
    """Targets plus what the UI needs to edit them: suggestions, resolved plan values and warnings."""
    target = get_or_create_macro_target(user)
    values = values if values is not None else target.values()
    program = JourneyProgram.objects.filter(user=user, active=True).first()
    recommended = calculate_recommended_targets(user)
    return {
        'id': str(target.id),
        **values,
        'effective': {
            'weekly_workouts': values['weekly_workouts'] or plan_weekly_workouts(program),
            'weekly_cardio_minutes': (values['weekly_cardio_minutes']
                                      if values['weekly_cardio_minutes'] is not None else plan_weekly_cardio(program)),
        },
        'suggested': suggested_targets(user, recommended, program),
        'limits': {**TARGET_LIMITS, 'daily_calories': (_calorie_floor(user), MAX_CALORIES)},
        'warnings': target_warnings(user, values, recommended),
        'adjustments': adjustments or [],
    }
