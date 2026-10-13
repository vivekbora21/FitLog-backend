"""Tunable constants for the plan engine (spec working rule 0.3: "Constants
are defaults. Every number in sections 4 and 6 lives in one config module
so it can be tuned without touching logic.").

Only section 4/5 constants are defined here (sections 6's split/volume
constants are out of scope for this pass).

IMPORTANT: engine.py reads these as ``config.NAME`` (module attribute
lookup), not via ``from .config import NAME``, so tests can monkeypatch a
single value (e.g. ``PACE_HARD_LIMIT_MODE``) for a single case without
reloading the module.
"""

from .domain import Mode, RecompDirection

ENGINE_VERSION = "1.0.0"

# --- 4.1 Energy expenditure ---------------------------------------------
# Single source of truth for the BMR->TDEE multiplier, shared with
# nutrition.targets.ACTIVITY_FACTORS (that module imports this dict rather
# than keeping its own copy, so the two calorie systems can no longer
# disagree). Keyed by the user's actual lifestyle activity
# (domain.ActivityLevel), not by days_per_week -- training frequency and
# how active someone's day job/life is are different things, and
# conflating them meant two users training the same number of days got
# identical TDEE regardless of how sedentary or active the rest of their
# week was.
ACTIVITY_FACTOR_BY_LEVEL = {
    "SEDENTARY": 1.2,
    "LIGHT": 1.375,
    "MODERATE": 1.55,
    "HIGH": 1.725,
    "ATHLETE": 1.9,
}

# --- 4.2 Energy constant --------------------------------------------------
ENERGY_KCAL_PER_KG = 7700

# --- 4.3 Mode policies ------------------------------------------------------
RECOMP_DIRECTION_FACTOR = {
    RecompDirection.LEAN_OUT: -0.05,
    RecompDirection.MAINTAIN: 0.0,
    RecompDirection.LEAN_GAIN: 0.05,
}
DEFAULT_RECOMP_DIRECTION = RecompDirection.LEAN_OUT
FOCUS_GOAL_SUGGEST_PCT = 0.02  # D2 FOCUS_GOAL_SUGGESTS_CUT_OR_BULK threshold

# --- 4.4 Calorie floor ------------------------------------------------------
CALORIE_FLOOR_KCAL = {
    "male": 1500,
    "female": 1200,
}

# --- 4.6 Pace bands (% of current body weight per week) --------------------
# gentle: < gentle_max ; typical: gentle_max..typical_max inclusive ;
# aggressive (warn): > typical_max ; hard limit (block/warn per D1): > hard_limit
PACE_BANDS_PCT = {
    Mode.CUT: {"gentle_max": 0.25, "typical_max": 1.0, "hard_limit": 1.5},
    Mode.BULK: {"gentle_max": 0.10, "typical_max": 0.50, "hard_limit": 1.0},
}

# D1 (section 0A): what happens beyond the hard pace limit.
# "block" (decided, default) or "warn".
PACE_HARD_LIMIT_MODE = "block"

# --- 4.7 Macros --------------------------------------------------------------
PROTEIN_G_PER_KG_BY_MODE = {
    Mode.CUT: 2.0,
    Mode.RECOMP: 2.0,
    Mode.BULK: 1.8,
    Mode.FOCUS: 1.6,
    # Spec doesn't give Habit its own protein value; Habit is FOCUS's twin
    # (same maintenance formula), so it uses FOCUS's 1.6 g/kg too.
    Mode.HABIT: 1.6,
}
FAT_PCT_OF_TARGET_CALORIES = 0.25
CARB_FLOOR_G = 50
FAT_FLOOR_G_PER_KG = 0.6     # carb-floor fallback cascade step 1
PROTEIN_FLOOR_G_PER_KG = 1.6  # carb-floor fallback cascade step 2
MACRO_CALORIE_TOLERANCE_KCAL = 10  # acceptance / property-test tolerance

# --- V-19 MACROS_UNUSUAL thresholds (g/kg of current body weight) ----------
MACROS_UNUSUAL_PROTEIN_MIN_G_PER_KG = 1.2
MACROS_UNUSUAL_PROTEIN_MAX_G_PER_KG = 3.0
MACROS_UNUSUAL_FAT_MIN_G_PER_KG = 0.5

# --- V-13 RECOMP_OVERRIDE_LARGE ---------------------------------------------
RECOMP_OVERRIDE_LARGE_PCT = 0.15  # fraction of TDEE

# --- 4.5 days_needed / goal check -------------------------------------------
DAYS_NEEDED_MIN_WEEKLY_RATE_KG = 0.05
DAYS_NEEDED_MAX_DAYS = 365
GOAL_NOT_REACHED_TOLERANCE_KG = 0.25

# --- 6.1 / V-11 consecutive-day warning --------------------------------------
# "run longer than 2 when days/week is 3-4; longer than 3 when 5; none when 6"
# (a value of None means the rule never fires for that days_per_week).
CONSECUTIVE_DAY_RUN_LIMIT_BY_DAYS_PER_WEEK = {
    3: 2,
    4: 2,
    5: 3,
    6: None,
}

# --- V-15 BEGINNER_HIGH_FREQUENCY ---------------------------------------------
BEGINNER_HIGH_FREQUENCY_DAYS_PER_WEEK = (5, 6)

# --- V-01 profile ranges (D2: 18+ only in v1) --------------------------------
MIN_AGE = 18
MAX_AGE = 90
MIN_WEIGHT_KG = 30
MAX_WEIGHT_KG = 300
MIN_HEIGHT_CM = 120
MAX_HEIGHT_CM = 230

# --- V-02 / V-03 ---------------------------------------------------------
MIN_DURATION_DAYS = 7
MAX_DURATION_DAYS = 365
MIN_DAYS_PER_WEEK = 3
MAX_DAYS_PER_WEEK = 6

# --- V-06 goal direction ------------------------------------------------
GOAL_MIN_DELTA_KG = 0.5

# --- V-09 BMI floor for a Cut goal ---------------------------------------
MIN_GOAL_BMI = 18.5

# --- 4.10 mode-change defaults (used by callers of the engine, not by the
# engine itself, which is stateless -- kept here since it is a section-4
# constant) ---
DEFAULT_DURATION_DAYS_BY_MODE = {
    Mode.CUT: 60,
    Mode.BULK: 90,
    Mode.RECOMP: 45,
    Mode.FOCUS: 30,
    Mode.HABIT: 30,
}
