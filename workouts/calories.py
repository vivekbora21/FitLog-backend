"""Cardio calorie estimation from the logged workout itself.

Mirrors mobile/src/features/workout/cardioCalories.ts — keep the two in sync.

Picks the most specific model the logged data allows:
  1. Average heart rate + age + sex -> Keytel et al. (2005) HR equation.
  2. Treadmill / walk / run with a speed -> ACSM metabolic equations, which
     account for both speed and incline.
  3. Otherwise -> MET x body weight x time, with MET scaled by intensity zone.
"""
from datetime import date

# Fallback MET per modality at a moderate (Zone 2) effort, for exercises without a catalog MET.
MODALITY_MET = {
    'WALK_RUN': 6.0,
    'CYCLING': 6.8,
    'ROWING': 7.0,
    'ELLIPTICAL': 5.0,
    'STAIR': 9.0,
    'JUMP_ROPE': 11.8,
    'OTHER': 5.0,
}

# Scales a moderate-effort MET to the selected intensity zone. Ordered most
# intense first, so e.g. "HIIT / Max" matches before anything milder.
INTENSITY_MULTIPLIERS = [
    ('hiit', 1.45),
    ('max', 1.45),
    ('zone 5', 1.45),
    ('zone 4', 1.35),
    ('zone 3', 1.2),
    ('tempo', 1.2),
    ('zone 2', 1.0),
    ('zone 1', 0.75),
    ('warm', 0.75),
]

# ACSM treats < ~8 km/h as walking; above that, the running equation applies.
RUN_THRESHOLD_KMH = 8


def detect_cardio_modality(name):
    n = (name or '').lower()
    if 'cycl' in n or 'bike' in n or 'spin' in n:
        return 'CYCLING'
    if 'row' in n:
        return 'ROWING'
    if 'ellipt' in n or 'cross trainer' in n or 'cross_trainer' in n:
        return 'ELLIPTICAL'
    if 'stair' in n or 'step mill' in n or 'stepmill' in n:
        return 'STAIR'
    if 'jump rope' in n or 'skipping' in n:
        return 'JUMP_ROPE'
    if any(k in n for k in ('tread', 'walk', 'run', 'jog', 'incline')):
        return 'WALK_RUN'
    return 'OTHER'


def intensity_multiplier(intensity):
    i = (intensity or '').lower()
    return next((mult for key, mult in INTENSITY_MULTIPLIERS if key in i), 1.0)


def age_from_date_of_birth(dob, today=None):
    if not dob:
        return None
    today = today or date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return age if 0 < age < 120 else None


def profile_calorie_inputs(user):
    """(weight_kg, age, sex) from the user's profile, any of which may be None."""
    profile = getattr(user, 'profile', None)
    if profile is None:
        return None, None, None
    return (
        profile.weight_kg,
        age_from_date_of_birth(profile.date_of_birth),
        profile.sex or None,
    )


def estimate_cardio_calories(*, name, duration_minutes, weight_kg, met_value=None, speed_kmh=None,
                             incline_percent=None, intensity='', heart_rate=None, age=None, sex=None):
    """Returns (kcal, method) or None when there isn't enough data to estimate."""
    if not weight_kg or weight_kg <= 0 or not duration_minutes or duration_minutes <= 0:
        return None

    # 1. Heart rate: most personal signal, but the equation is only validated for
    # exercising heart rates, and needs age + sex.
    if heart_rate and 90 <= heart_rate <= 220 and age and sex in ('MALE', 'FEMALE'):
        if sex == 'MALE':
            kj_per_min = -55.0969 + 0.6309 * heart_rate + 0.1988 * weight_kg + 0.2017 * age
        else:
            kj_per_min = -20.4022 + 0.4472 * heart_rate - 0.1263 * weight_kg + 0.074 * age
        if kj_per_min > 0:
            return round(kj_per_min / 4.184 * duration_minutes), 'heart_rate'

    modality = detect_cardio_modality(name)

    # 2. Walking / running with a known speed: ACSM equations (VO2 in ml/kg/min).
    if modality == 'WALK_RUN' and speed_kmh and 0 < speed_kmh < 30:
        meters_per_min = speed_kmh * 1000 / 60
        grade = max(0, incline_percent or 0) / 100
        if speed_kmh < RUN_THRESHOLD_KMH:
            vo2 = 0.1 * meters_per_min + 1.8 * meters_per_min * grade + 3.5
        else:
            vo2 = 0.2 * meters_per_min + 0.9 * meters_per_min * grade + 3.5
        # ~5 kcal per litre of O2 consumed.
        kcal_per_min = vo2 * weight_kg * 5 / 1000
        return round(kcal_per_min * duration_minutes), 'speed_incline'

    # 3. MET x weight x hours, scaled by intensity zone.
    base_met = met_value if met_value and met_value > 0 else MODALITY_MET[modality]
    met = base_met * intensity_multiplier(intensity)
    return round(met * weight_kg * (duration_minutes / 60)), 'met'
