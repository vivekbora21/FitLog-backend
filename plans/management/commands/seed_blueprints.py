"""
Seed the guided-plan Blueprint catalog: one fully fleshed-out blueprint per
JourneyProgram mode (CUT/BULK/FOCUS/RECOMP/HABIT).

Usage:
    python manage.py seed_blueprints          # seed everything
    python manage.py seed_blueprints --wipe   # delete all blueprints first, then re-seed

Idempotent: uses get_or_create on slug, safe to re-run.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from plans.models import Blueprint


def _phases(duration_days):
    foundation_end = round(duration_days * 0.30)
    build_end = round(duration_days * 0.70)
    return [
        {'name': 'Foundation', 'start_day': 1, 'end_day': foundation_end},
        {'name': 'Build', 'start_day': foundation_end + 1, 'end_day': build_end},
        {'name': 'Peak', 'start_day': build_end + 1, 'end_day': duration_days},
    ]


CUT_WORKOUTS = {
    'day_1': [
        {'exercise_name': 'Barbell Back Squat', 'sets': 4, 'reps': '6-8', 'rpe': 7.5, 'rest_seconds': 120, 'progression_rule': 'Add 2.5kg once all sets hit the top of the rep range with RPE <= 8.'},
        {'exercise_name': 'Romanian Deadlift (RDL)', 'sets': 3, 'reps': '8-10', 'rpe': 7.0, 'rest_seconds': 90, 'progression_rule': 'Add 2.5kg every 2 weeks if form stays strict.'},
        {'exercise_name': 'Leg Press', 'sets': 3, 'reps': '10-12', 'rpe': 8.0, 'rest_seconds': 90, 'progression_rule': 'Add one plate per side when RPE drops below 8.'},
        {'exercise_name': 'Hanging Leg Raise', 'sets': 3, 'reps': '12-15', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Add reps before adding a weighted vest.'},
    ],
    'day_2': [],
    'day_3': [
        {'exercise_name': 'Barbell Bench Press', 'sets': 4, 'reps': '6-8', 'rpe': 7.5, 'rest_seconds': 120, 'progression_rule': 'Add 2.5kg once all sets hit the top of the rep range with RPE <= 8.'},
        {'exercise_name': 'Wide-Grip Lat Pulldown', 'sets': 4, 'reps': '8-10', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Increase load once 10 reps achieved on all sets.'},
        {'exercise_name': 'Seated Dumbbell Shoulder Press', 'sets': 3, 'reps': '8-10', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Add 2kg per dumbbell every 2-3 weeks.'},
        {'exercise_name': 'Cable Face Pull', 'sets': 3, 'reps': '12-15', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Prioritize scapular control over load.'},
    ],
    'day_4': [],
    'day_5': [
        {'exercise_name': 'Conventional Deadlift', 'sets': 3, 'reps': '5', 'rpe': 8.0, 'rest_seconds': 150, 'progression_rule': 'Add 5kg per week while bar speed stays fast.'},
        {'exercise_name': 'Bulgarian Split Squat', 'sets': 3, 'reps': '10-12', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Add dumbbell weight once both legs hit 12 reps.'},
        {'exercise_name': 'Seated Cable Row', 'sets': 3, 'reps': '10-12', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Increase load when form is clean at top of range.'},
        {'exercise_name': 'Treadmill Running', 'sets': 1, 'reps': '20 min Zone 2', 'rpe': None, 'rest_seconds': 0, 'progression_rule': 'Increase duration by 5 min every 2 weeks.'},
    ],
    'day_6': [],
    'day_7': [],
}
CUT_MEALS = {
    'breakfast': {'sample_foods': ['Egg whites + 2 whole eggs', 'Oats with berries', 'Black coffee'], 'protein_g': 35, 'kcal': 420, 'fat_g': 12, 'swap_options': ['Greek yogurt with protein powder', 'Egg white omelet with spinach']},
    'lunch': {'sample_foods': ['Grilled chicken breast', 'Brown rice', 'Steamed broccoli'], 'protein_g': 45, 'kcal': 550, 'fat_g': 14, 'swap_options': ['Turkey breast with quinoa', 'White fish with sweet potato']},
    'snack': {'sample_foods': ['Protein shake', 'Handful of almonds'], 'protein_g': 25, 'kcal': 280, 'fat_g': 10, 'swap_options': ['Cottage cheese with cucumber', 'Rice cakes with peanut butter (light)']},
    'dinner': {'sample_foods': ['Baked salmon', 'Roasted vegetables', 'Small portion of quinoa'], 'protein_g': 40, 'kcal': 520, 'fat_g': 18, 'swap_options': ['Lean beef stir-fry', 'Tofu and vegetable curry']},
}

BULK_WORKOUTS = {
    'day_1': [
        {'exercise_name': 'Barbell Back Squat', 'sets': 5, 'reps': '5', 'rpe': 8.0, 'rest_seconds': 150, 'progression_rule': 'Add 2.5-5kg per week while all sets stay under RPE 9.'},
        {'exercise_name': 'Leg Press', 'sets': 4, 'reps': '10-12', 'rpe': 8.0, 'rest_seconds': 120, 'progression_rule': 'Add load once 12 reps hit on every set.'},
        {'exercise_name': 'Lying Leg Curl', 'sets': 3, 'reps': '10-12', 'rpe': 8.0, 'rest_seconds': 90, 'progression_rule': 'Add weight in small increments weekly.'},
        {'exercise_name': 'Standing Calf Raise', 'sets': 4, 'reps': '12-15', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Add reps then load.'},
    ],
    'day_2': [
        {'exercise_name': 'Barbell Bench Press', 'sets': 5, 'reps': '5', 'rpe': 8.0, 'rest_seconds': 150, 'progression_rule': 'Add 2.5kg per week while bar speed stays fast.'},
        {'exercise_name': 'Barbell Bent-Over Row', 'sets': 4, 'reps': '8-10', 'rpe': 8.0, 'rest_seconds': 120, 'progression_rule': 'Add load once top of range is hit for all sets.'},
        {'exercise_name': 'Incline Dumbbell Press', 'sets': 3, 'reps': '8-10', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Add 2kg per dumbbell every 2 weeks.'},
        {'exercise_name': 'Dumbbell Bicep Curl', 'sets': 3, 'reps': '10-12', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Add weight once 12 reps achieved.'},
    ],
    'day_3': [],
    'day_4': [
        {'exercise_name': 'Overhead Barbell Press (OHP)', 'sets': 4, 'reps': '6-8', 'rpe': 8.0, 'rest_seconds': 120, 'progression_rule': 'Add 2.5kg once all sets hit 8 reps.'},
        {'exercise_name': 'Wide-Grip Lat Pulldown', 'sets': 4, 'reps': '8-10', 'rpe': 8.0, 'rest_seconds': 90, 'progression_rule': 'Increase load once form is clean at top of range.'},
        {'exercise_name': 'Dumbbell Lateral Raise', 'sets': 3, 'reps': '12-15', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Add reps before load.'},
        {'exercise_name': 'Tricep Rope Pushdown', 'sets': 3, 'reps': '10-12', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Increase load progressively.'},
    ],
    'day_5': [
        {'exercise_name': 'Conventional Deadlift', 'sets': 4, 'reps': '5', 'rpe': 8.5, 'rest_seconds': 150, 'progression_rule': 'Add 5kg per week while form stays tight.'},
        {'exercise_name': 'Walking Lunge', 'sets': 3, 'reps': '12 per leg', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Add dumbbells once bodyweight reps feel easy.'},
        {'exercise_name': 'Chest-Supported Dumbbell Row', 'sets': 3, 'reps': '10-12', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Add load once 12 reps hit across all sets.'},
        {'exercise_name': 'Hammer Curl', 'sets': 3, 'reps': '10-12', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Increase load steadily.'},
    ],
    'day_6': [],
    'day_7': [],
}
BULK_MEALS = {
    'breakfast': {'sample_foods': ['4 whole eggs', 'Oats with banana and peanut butter', 'Whole milk'], 'protein_g': 40, 'kcal': 750, 'fat_g': 28, 'swap_options': ['Protein pancakes with syrup', 'Greek yogurt parfait with granola']},
    'lunch': {'sample_foods': ['Beef and rice bowl', 'Avocado', 'Mixed vegetables'], 'protein_g': 50, 'kcal': 850, 'fat_g': 30, 'swap_options': ['Chicken thigh with pasta', 'Salmon with couscous']},
    'snack': {'sample_foods': ['Mass gainer shake', 'Trail mix'], 'protein_g': 35, 'kcal': 500, 'fat_g': 18, 'swap_options': ['Peanut butter sandwich', 'Cottage cheese with granola']},
    'dinner': {'sample_foods': ['Grilled steak', 'Baked potato', 'Sauteed greens'], 'protein_g': 45, 'kcal': 780, 'fat_g': 26, 'swap_options': ['Chicken parmesan with pasta', 'Pork tenderloin with rice']},
}

FOCUS_WORKOUTS = {
    'day_1': [
        {'exercise_name': 'Barbell Back Squat', 'sets': 5, 'reps': '3', 'rpe': 8.5, 'rest_seconds': 180, 'progression_rule': 'Add 2.5kg per week while bar speed stays fast; deload every 4th week.'},
        {'exercise_name': 'Leg Press', 'sets': 3, 'reps': '8-10', 'rpe': 7.5, 'rest_seconds': 120, 'progression_rule': 'Accessory volume, add load slowly.'},
        {'exercise_name': 'Hanging Leg Raise', 'sets': 3, 'reps': '10-12', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Add reps then a weighted vest.'},
    ],
    'day_2': [],
    'day_3': [
        {'exercise_name': 'Barbell Bench Press', 'sets': 5, 'reps': '3', 'rpe': 8.5, 'rest_seconds': 180, 'progression_rule': 'Add 2.5kg per week; deload every 4th week if RPE creeps above 9.'},
        {'exercise_name': 'Barbell Bent-Over Row', 'sets': 3, 'reps': '6-8', 'rpe': 7.5, 'rest_seconds': 120, 'progression_rule': 'Keep as an accessory to protect recovery for the press.'},
        {'exercise_name': 'Tricep Rope Pushdown', 'sets': 3, 'reps': '10-12', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Add load steadily.'},
    ],
    'day_4': [
        {'exercise_name': 'Conventional Deadlift', 'sets': 5, 'reps': '3', 'rpe': 8.5, 'rest_seconds': 180, 'progression_rule': 'Add 2.5-5kg per week while form stays tight; deload every 4th week.'},
        {'exercise_name': 'Romanian Deadlift (RDL)', 'sets': 3, 'reps': '8', 'rpe': 7.0, 'rest_seconds': 90, 'progression_rule': 'Light accessory volume, prioritize hip hinge quality.'},
        {'exercise_name': 'Plank', 'sets': 3, 'reps': '45-60 sec', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Increase hold time before adding load.'},
    ],
    'day_5': [],
    'day_6': [],
    'day_7': [],
}
FOCUS_MEALS = {
    'breakfast': {'sample_foods': ['3 whole eggs', 'Whole grain toast', 'Avocado'], 'protein_g': 35, 'kcal': 550, 'fat_g': 22, 'swap_options': ['Greek yogurt with nuts', 'Protein oats']},
    'lunch': {'sample_foods': ['Grilled chicken', 'Brown rice', 'Mixed salad'], 'protein_g': 45, 'kcal': 650, 'fat_g': 18, 'swap_options': ['Turkey wrap with vegetables', 'Salmon with quinoa']},
    'snack': {'sample_foods': ['Protein shake', 'Banana'], 'protein_g': 25, 'kcal': 300, 'fat_g': 6, 'swap_options': ['Greek yogurt with berries', 'Rice cakes with peanut butter']},
    'dinner': {'sample_foods': ['Lean beef', 'Sweet potato', 'Steamed vegetables'], 'protein_g': 40, 'kcal': 620, 'fat_g': 20, 'swap_options': ['Grilled fish with rice', 'Chicken stir-fry']},
}

HABIT_WORKOUTS = {
    'day_1': [
        {'exercise_name': 'Goblet Squat', 'sets': 3, 'reps': '10-12', 'rpe': 6.0, 'rest_seconds': 90, 'progression_rule': 'Add weight once all sets feel easy at RPE 6.'},
        {'exercise_name': 'Push-Up', 'sets': 3, 'reps': '8-12', 'rpe': 6.0, 'rest_seconds': 60, 'progression_rule': 'Progress to full reps before adding load or incline.'},
        {'exercise_name': 'Inverted Row', 'sets': 3, 'reps': '8-12', 'rpe': 6.0, 'rest_seconds': 60, 'progression_rule': 'Lower the bar height as strength improves.'},
        {'exercise_name': 'Plank', 'sets': 3, 'reps': '20-30 sec', 'rpe': None, 'rest_seconds': 45, 'progression_rule': 'Increase hold time gradually.'},
    ],
    'day_2': [],
    'day_3': [
        {'exercise_name': 'Dumbbell Romanian Deadlift', 'sets': 3, 'reps': '10-12', 'rpe': 6.0, 'rest_seconds': 90, 'progression_rule': 'Add weight once form is consistent.'},
        {'exercise_name': 'Seated Dumbbell Shoulder Press', 'sets': 3, 'reps': '8-12', 'rpe': 6.0, 'rest_seconds': 60, 'progression_rule': 'Add small weight increments weekly.'},
        {'exercise_name': 'Single-Arm Dumbbell Row', 'sets': 3, 'reps': '10-12', 'rpe': 6.0, 'rest_seconds': 60, 'progression_rule': 'Focus on full range of motion before adding load.'},
    ],
    'day_4': [],
    'day_5': [
        {'exercise_name': 'Walking Lunge', 'sets': 3, 'reps': '10 per leg', 'rpe': 6.0, 'rest_seconds': 60, 'progression_rule': 'Add dumbbells once bodyweight feels easy.'},
        {'exercise_name': 'Incline Treadmill Walk', 'sets': 1, 'reps': '15-20 min', 'rpe': None, 'rest_seconds': 0, 'progression_rule': 'Increase incline or duration gradually.'},
        {'exercise_name': 'Dead Bug', 'sets': 3, 'reps': '10 per side', 'rpe': None, 'rest_seconds': 45, 'progression_rule': 'Slow the tempo before adding reps.'},
    ],
    'day_6': [],
    'day_7': [],
}
HABIT_MEALS = {
    'breakfast': {'sample_foods': ['2 eggs', 'Whole grain toast', 'Fruit'], 'protein_g': 22, 'kcal': 420, 'fat_g': 14, 'swap_options': ['Greek yogurt with granola', 'Protein smoothie']},
    'lunch': {'sample_foods': ['Grilled chicken salad', 'Whole grain roll'], 'protein_g': 35, 'kcal': 520, 'fat_g': 16, 'swap_options': ['Tuna sandwich', 'Bean and vegetable bowl']},
    'snack': {'sample_foods': ['Handful of nuts', 'Apple'], 'protein_g': 8, 'kcal': 220, 'fat_g': 12, 'swap_options': ['Yogurt cup', 'Protein bar']},
    'dinner': {'sample_foods': ['Baked fish', 'Rice', 'Steamed vegetables'], 'protein_g': 35, 'kcal': 540, 'fat_g': 15, 'swap_options': ['Chicken and vegetable stir-fry', 'Turkey chili']},
}

RECOMP_WORKOUTS = {
    'day_1': [
        {'exercise_name': 'Barbell Back Squat', 'sets': 4, 'reps': '6-8', 'rpe': 7.5, 'rest_seconds': 120, 'progression_rule': 'Add 2.5kg once all sets hit top of range at RPE <= 8.'},
        {'exercise_name': 'Romanian Deadlift (RDL)', 'sets': 3, 'reps': '8-10', 'rpe': 7.0, 'rest_seconds': 90, 'progression_rule': 'Add load every 2 weeks if form is strict.'},
        {'exercise_name': 'Leg Extension', 'sets': 3, 'reps': '12-15', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Add reps then load.'},
    ],
    'day_2': [],
    'day_3': [
        {'exercise_name': 'Barbell Bench Press', 'sets': 4, 'reps': '6-8', 'rpe': 7.5, 'rest_seconds': 120, 'progression_rule': 'Add 2.5kg once all sets hit top of range.'},
        {'exercise_name': 'Seated Cable Row', 'sets': 4, 'reps': '8-10', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Increase load steadily every 2 weeks.'},
        {'exercise_name': 'Dumbbell Lateral Raise', 'sets': 3, 'reps': '12-15', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Add reps before load.'},
    ],
    'day_4': [
        {'exercise_name': 'Bulgarian Split Squat', 'sets': 3, 'reps': '10-12', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Add dumbbell weight once both legs hit 12 reps.'},
        {'exercise_name': 'Wide-Grip Lat Pulldown', 'sets': 3, 'reps': '8-10', 'rpe': 7.5, 'rest_seconds': 90, 'progression_rule': 'Increase load once top of range is clean.'},
        {'exercise_name': 'Cable Face Pull', 'sets': 3, 'reps': '12-15', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Prioritize control over load.'},
    ],
    'day_5': [],
    'day_6': [
        {'exercise_name': 'Rowing Machine', 'sets': 1, 'reps': '20 min Zone 2', 'rpe': None, 'rest_seconds': 0, 'progression_rule': 'Increase duration gradually every 2 weeks.'},
        {'exercise_name': 'Hanging Knee Raise', 'sets': 3, 'reps': '10-12', 'rpe': None, 'rest_seconds': 60, 'progression_rule': 'Progress to straight-leg raises.'},
    ],
    'day_7': [],
}
RECOMP_MEALS = {
    'breakfast': {'sample_foods': ['3 egg omelet with vegetables', 'Whole grain toast'], 'protein_g': 32, 'kcal': 460, 'fat_g': 16, 'swap_options': ['Greek yogurt with protein powder', 'Protein oats']},
    'lunch': {'sample_foods': ['Grilled chicken breast', 'Quinoa', 'Roasted vegetables'], 'protein_g': 45, 'kcal': 580, 'fat_g': 16, 'swap_options': ['Turkey breast with brown rice', 'White fish with sweet potato']},
    'snack': {'sample_foods': ['Protein shake', 'Cottage cheese'], 'protein_g': 28, 'kcal': 280, 'fat_g': 8, 'swap_options': ['Handful of almonds', 'Rice cakes with peanut butter']},
    'dinner': {'sample_foods': ['Grilled salmon', 'Brown rice', 'Steamed greens'], 'protein_g': 40, 'kcal': 540, 'fat_g': 18, 'swap_options': ['Lean beef stir-fry', 'Tofu and vegetable curry']},
}


BLUEPRINTS = [
    {
        'slug': 'cut-60',
        'name': '60-Day Recomp & Shred',
        'mode': 'CUT',
        'description': 'A 60-day fat-loss program pairing a moderate calorie deficit with strength-preserving resistance training and steady-state cardio.',
        'difficulty': 'INTERMEDIATE',
        'default_duration_days': 60,
        'default_days_per_week': 4,
        'pacing_kg_per_week': -0.5,
        'workout_templates': CUT_WORKOUTS,
        'meal_templates': CUT_MEALS,
        'display_order': 1,
    },
    {
        'slug': 'bulk-90',
        'name': '90-Day Mass Architecture',
        'mode': 'BULK',
        'description': 'A 90-day lean-bulk program built on progressive overload across the big compound lifts with a controlled calorie surplus.',
        'difficulty': 'INTERMEDIATE',
        'default_duration_days': 90,
        'default_days_per_week': 5,
        'pacing_kg_per_week': 0.3,
        'workout_templates': BULK_WORKOUTS,
        'meal_templates': BULK_MEALS,
        'display_order': 2,
    },
    {
        'slug': 'focus-30',
        'name': '30-Day Strength Peak',
        'mode': 'FOCUS',
        'description': 'A 30-day strength-peaking block centered on low-rep, high-intensity work on the main lifts at maintenance calories.',
        'difficulty': 'ADVANCED',
        'default_duration_days': 30,
        'default_days_per_week': 4,
        'pacing_kg_per_week': 0.0,
        'workout_templates': FOCUS_WORKOUTS,
        'meal_templates': FOCUS_MEALS,
        'display_order': 3,
    },
    {
        'slug': 'habit-21',
        'name': '21-Day Habit Lock-in',
        'mode': 'HABIT',
        'description': 'A 21-day beginner-friendly reset to build a consistent training and eating habit with low-fatigue full-body sessions.',
        'difficulty': 'BEGINNER',
        'default_duration_days': 21,
        'default_days_per_week': 3,
        'pacing_kg_per_week': 0.0,
        'workout_templates': HABIT_WORKOUTS,
        'meal_templates': HABIT_MEALS,
        'display_order': 4,
    },
    {
        'slug': 'recomp-45',
        'name': '45-Day Lean Recomp',
        'mode': 'RECOMP',
        'description': 'A 45-day body recomposition program combining a small deficit with high-frequency strength training to build muscle while losing fat.',
        'difficulty': 'INTERMEDIATE',
        'default_duration_days': 45,
        'default_days_per_week': 4,
        'pacing_kg_per_week': -0.15,
        'workout_templates': RECOMP_WORKOUTS,
        'meal_templates': RECOMP_MEALS,
        'display_order': 5,
    },
]


class Command(BaseCommand):
    help = 'Seeds the guided-plan Blueprint catalog (one per journey mode). Idempotent.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--wipe',
            action='store_true',
            help='Delete ALL existing blueprints first, then re-seed.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options['wipe']:
            self.stdout.write(self.style.WARNING('Wiping all blueprints...'))
            Blueprint.objects.all().delete()

        created_count = 0
        updated_count = 0
        for bp in BLUEPRINTS:
            defaults = dict(bp)
            slug = defaults.pop('slug')
            defaults['phases'] = _phases(defaults['default_duration_days'])
            _, created = Blueprint.objects.get_or_create(slug=slug, defaults=defaults)
            if created:
                created_count += 1
                self.stdout.write(f"  + Blueprint: {defaults['name']}")
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nBlueprint catalog seeded: {created_count} created, {updated_count} already existed/updated, "
            f"{len(BLUEPRINTS)} total."
        ))
