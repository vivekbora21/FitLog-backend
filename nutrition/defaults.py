"""
Single source of truth for fallback nutrition targets. Kept import-free so the
model, the target calculator, seed commands and views can all depend on it.

A user's real targets are derived from their profile (see targets.py); these
values only apply when a MacroTarget has to exist before the profile is complete.
Clients never hard-code their own fallbacks - they render what the API returns.
"""

DEFAULT_MACRO_TARGETS = {
    'daily_calories': 2400,
    'protein_g': 160,
    'carbs_g': 250,
    'fat_g': 70,
    'water_ml': 3000,
}

# Workbook Pillar 9 (8,000–10,000 steps) and Pillar 7 (7.5–8.5h sleep) lower bounds.
DEFAULT_LIFESTYLE_TARGETS = {
    'daily_steps': 8000,
    'sleep_hours': 7.5,
}

# Option A totals from the "New start.xlsx" Diet Plan sheet (sum of its meal rows).
DIET_PLAN_OPTION_A_TARGETS = {
    'daily_calories': 2160,
    'protein_g': 165,
    'carbs_g': 264,
    'fat_g': 43,
    'water_ml': 3500,
}
