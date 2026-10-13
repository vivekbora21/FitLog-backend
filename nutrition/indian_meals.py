"""Indian meal-plan templates, scaled to a member's real calorie/macro
targets (from `nutrition.targets.calculate_recommended_targets` or their
current `MacroTarget`) instead of the fixed Western day totals baked into
`plans.Blueprint.meal_templates` (CUT=1770/BULK=2880/FOCUS=2120/HABIT=1700/
RECOMP=1860 kcal, same regardless of the member's actual numbers).

Values are approximate home-style servings from common reference tables
(IFCT/USDA-style figures), not lab-measured -- treat them as estimates to
show the member a realistic day, not as dietetic advice. Before any
production nutrition claim, verify against IFCT 2017 and have a registered
dietitian review portions and the protein-booster logic (same caveat as
fitlog_india_library_and_plans_proposal.md section 6.4).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

MEAL_SHARE = {
    'breakfast': 0.25,
    'lunch': 0.30,
    'snack': 0.15,
    'dinner': 0.30,
}

# Each template is one full day at a reference calorie level; `scale_template`
# multiplies every meal's macros by `target_calories / reference_kcal` to fit
# the member's actual target, then tops up protein with boosters if the
# scaled day still falls short.
TEMPLATES = {
    'VEG': [
        {
            'id': 'veg-a',
            'label': 'Dal, roti and paneer',
            'reference_kcal': 2207,
            'meals': {
                'breakfast': {'kcal': 450, 'protein_g': 18, 'carbs_g': 62, 'fat_g': 14,
                              'items': ['2 vegetable paratha', 'curd (1 katori)']},
                'lunch': {'kcal': 680, 'protein_g': 28, 'carbs_g': 95, 'fat_g': 18,
                          'items': ['3 roti', 'dal (1.5 katori)', 'mixed sabzi (1 katori)', 'salad']},
                'snack': {'kcal': 330, 'protein_g': 14, 'carbs_g': 40, 'fat_g': 10,
                          'items': ['sprouts chaat (1 katori)', 'roasted chana (1 handful)']},
                'dinner': {'kcal': 747, 'protein_g': 52, 'carbs_g': 98, 'fat_g': 25,
                           'items': ['2 roti', 'paneer bhurji (150 g)', 'rice (1 katori)', 'dal (1 katori)']},
            },
        },
        {
            'id': 'veg-b',
            'label': 'Rice, rajma and soya',
            'reference_kcal': 2180,
            'meals': {
                'breakfast': {'kcal': 420, 'protein_g': 16, 'carbs_g': 58, 'fat_g': 12,
                              'items': ['poha (1.5 katori)', 'peanuts (1 tbsp)', '1 glass milk']},
                'lunch': {'kcal': 670, 'protein_g': 26, 'carbs_g': 100, 'fat_g': 16,
                          'items': ['rice (1.5 katori)', 'rajma (1.5 katori)', 'salad']},
                'snack': {'kcal': 320, 'protein_g': 16, 'carbs_g': 32, 'fat_g': 11,
                          'items': ['soya chunks chaat (50 g dry)', '1 fruit']},
                'dinner': {'kcal': 770, 'protein_g': 50, 'carbs_g': 90, 'fat_g': 24,
                           'items': ['3 roti', 'paneer curry (150 g)', 'curd (1 katori)']},
            },
        },
    ],
    'EGG': [
        {
            'id': 'egg-a',
            'label': 'Egg bhurji and dal',
            'reference_kcal': 2125,
            'meals': {
                'breakfast': {'kcal': 430, 'protein_g': 24, 'carbs_g': 48, 'fat_g': 16,
                              'items': ['3-egg bhurji', '2 roti']},
                'lunch': {'kcal': 650, 'protein_g': 24, 'carbs_g': 95, 'fat_g': 16,
                          'items': ['3 roti', 'dal (1 katori)', 'sabzi (1 katori)']},
                'snack': {'kcal': 310, 'protein_g': 12, 'carbs_g': 38, 'fat_g': 9,
                          'items': ['boiled egg (1)', 'fruit chaat']},
                'dinner': {'kcal': 735, 'protein_g': 33, 'carbs_g': 100, 'fat_g': 22,
                           'items': ['rice (1.5 katori)', 'egg curry (2 eggs)', 'salad']},
            },
        },
        {
            'id': 'egg-b',
            'label': 'Omelette and paneer',
            'reference_kcal': 2150,
            'meals': {
                'breakfast': {'kcal': 440, 'protein_g': 22, 'carbs_g': 50, 'fat_g': 17,
                              'items': ['2-egg omelette', '2 brown bread slices']},
                'lunch': {'kcal': 660, 'protein_g': 26, 'carbs_g': 92, 'fat_g': 17,
                          'items': ['3 roti', 'paneer sabzi (100 g)', 'dal (1 katori)']},
                'snack': {'kcal': 300, 'protein_g': 13, 'carbs_g': 36, 'fat_g': 9,
                          'items': ['curd (1 katori)', 'roasted chana']},
                'dinner': {'kcal': 750, 'protein_g': 31, 'carbs_g': 100, 'fat_g': 23,
                           'items': ['rice (1.5 katori)', 'egg curry (2 eggs)', 'mixed veg (1 katori)']},
            },
        },
    ],
    'NON_VEG': [
        {
            'id': 'nonveg-a',
            'label': 'Chicken curry and rice',
            'reference_kcal': 2325,
            'meals': {
                'breakfast': {'kcal': 440, 'protein_g': 22, 'carbs_g': 55, 'fat_g': 14,
                              'items': ['2-egg omelette', '2 roti']},
                'lunch': {'kcal': 700, 'protein_g': 38, 'carbs_g': 95, 'fat_g': 18,
                          'items': ['rice (1.5 katori)', 'chicken curry (150 g)', 'dal (1 katori)']},
                'snack': {'kcal': 340, 'protein_g': 18, 'carbs_g': 32, 'fat_g': 12,
                          'items': ['grilled chicken (80 g)', '1 fruit']},
                'dinner': {'kcal': 845, 'protein_g': 45, 'carbs_g': 110, 'fat_g': 20,
                           'items': ['3 roti', 'chicken curry (150 g)', 'salad']},
            },
        },
        {
            'id': 'nonveg-b',
            'label': 'Fish curry and dal',
            'reference_kcal': 2260,
            'meals': {
                'breakfast': {'kcal': 420, 'protein_g': 20, 'carbs_g': 54, 'fat_g': 13,
                              'items': ['boiled eggs (2)', 'upma (1 katori)']},
                'lunch': {'kcal': 690, 'protein_g': 34, 'carbs_g': 98, 'fat_g': 17,
                          'items': ['rice (1.5 katori)', 'fish curry (150 g)', 'dal (1 katori)']},
                'snack': {'kcal': 330, 'protein_g': 16, 'carbs_g': 34, 'fat_g': 11,
                          'items': ['sprouts chaat', '1 fruit']},
                'dinner': {'kcal': 820, 'protein_g': 48, 'carbs_g': 100, 'fat_g': 21,
                           'items': ['3 roti', 'chicken/fish curry (150 g)', 'curd (1 katori)']},
            },
        },
    ],
}

# Approx protein per typical serving -- used by `_protein_boosters` to close
# a protein gap the scaled template still leaves (proposal section 6.1 step
# 4). Ordered cheapest/most-accessible first for an Indian household.
BOOSTER_PROTEIN_G_PER_SERVING = [
    ('curd (1 katori)', 5),
    ('sprouts (1 katori)', 8),
    ('paneer (100 g)', 18),
    ('soya chunks (50 g dry)', 26),
    ('3-egg bhurji', 19),
    ('whey scoop', 24),
]
MAX_BOOSTER_SERVINGS = 4


def _scale_meal(meal: dict, factor: float) -> dict:
    return {
        'items': meal['items'],
        'kcal': round(meal['kcal'] * factor),
        'protein_g': round(meal['protein_g'] * factor),
        'carbs_g': round(meal['carbs_g'] * factor),
        'fat_g': round(meal['fat_g'] * factor),
    }


def _protein_boosters(protein_gap_g: float, diet_preference: str) -> List[Dict]:
    if protein_gap_g <= 0:
        return []
    available = BOOSTER_PROTEIN_G_PER_SERVING
    if diet_preference == 'VEG':
        available = [b for b in available if b[0] != '3-egg bhurji']
    boosters = []
    remaining = protein_gap_g
    for name, protein_per_serving in available:
        if remaining <= 0 or len(boosters) >= MAX_BOOSTER_SERVINGS:
            break
        servings = min(2, max(1, round(remaining / protein_per_serving)))
        boosters.append({'item': name, 'servings': servings, 'protein_g': servings * protein_per_serving})
        remaining -= servings * protein_per_serving
    return boosters


def scale_template(template: dict, target_calories: int, target_protein_g: int,
                    diet_preference: str) -> dict:
    """Scales one day template to `target_calories`, then suggests protein
    boosters (not baked into the scaled meals) if the scaled day still falls
    short of `target_protein_g` -- see this module's docstring: Indian
    home-style meals rarely reach 1.6-2.2 g/kg on their own."""
    factor = target_calories / template['reference_kcal'] if template['reference_kcal'] else 1.0
    scaled_meals = {name: _scale_meal(meal, factor) for name, meal in template['meals'].items()}
    total_kcal = sum(m['kcal'] for m in scaled_meals.values())
    total_protein = sum(m['protein_g'] for m in scaled_meals.values())
    total_carbs = sum(m['carbs_g'] for m in scaled_meals.values())
    total_fat = sum(m['fat_g'] for m in scaled_meals.values())
    protein_gap = max(0, target_protein_g - total_protein)
    return {
        'id': template['id'],
        'label': template['label'],
        'meals': scaled_meals,
        'totals': {
            'kcal': total_kcal, 'protein_g': total_protein,
            'carbs_g': total_carbs, 'fat_g': total_fat,
        },
        'protein_gap_g': protein_gap,
        'protein_boosters': _protein_boosters(protein_gap, diet_preference),
    }


def meal_plan_options(target_calories: int, target_protein_g: int,
                       diet_preference: Optional[str] = None) -> List[dict]:
    """Every selectable meal-plan option for the given diet preference (both
    templates), or for all three preferences if none is given -- the
    'choose from multiple' entry point this module exists for."""
    preferences = [diet_preference] if diet_preference in TEMPLATES else list(TEMPLATES)
    options = []
    for pref in preferences:
        for template in TEMPLATES[pref]:
            scaled = scale_template(template, target_calories, target_protein_g, pref)
            options.append({'diet_preference': pref, **scaled})
    return options
