"""
Seed the TrainingSplit catalog: classic weekly training structures
(bro split, push/pull/legs, upper/lower, full body) that any Blueprint's
mode (CUT/BULK/FOCUS/RECOMP/HABIT) can be paired with via split_slug.

Usage:
    python manage.py seed_training_splits          # seed everything
    python manage.py seed_training_splits --wipe   # delete all splits first, then re-seed

Idempotent: uses get_or_create on slug, safe to re-run.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from plans.models import TrainingSplit


def _ex(name, sets, reps, rpe, rest, progression, is_cardio=False):
    entry = {
        'exercise_name': name, 'sets': sets, 'reps': reps, 'rpe': rpe,
        'rest_seconds': rest, 'progression_rule': progression,
    }
    if is_cardio:
        entry['is_cardio'] = True
    return entry


BRO_SPLIT_WORKOUTS = {
    'day_1': [  # Chest
        _ex('Barbell Bench Press', 4, '6-8', 7.5, 120, 'Add 2.5kg once all sets hit the top of the rep range.'),
        _ex('Incline Dumbbell Press', 3, '8-10', 7.5, 90, 'Add 2kg per dumbbell every 2 weeks.'),
        _ex('Cable Chest Fly', 3, '12-15', None, 60, 'Add reps before load.'),
        _ex('Dips (Chest Focus)', 3, '8-12', 7.0, 90, 'Add a weighted belt once 12 reps are clean.'),
    ],
    'day_2': [  # Back
        _ex('Conventional Deadlift', 3, '5', 8.0, 150, 'Add 5kg per week while bar speed stays fast.'),
        _ex('Wide-Grip Lat Pulldown', 4, '8-10', 7.5, 90, 'Increase load once 10 reps hit on all sets.'),
        _ex('Barbell Bent-Over Row', 3, '8-10', 7.5, 90, 'Add load once top of range is clean.'),
        _ex('Seated Cable Row', 3, '10-12', 7.0, 90, 'Add load steadily every 2 weeks.'),
    ],
    'day_3': [  # Legs
        _ex('Barbell Back Squat', 4, '6-8', 7.5, 150, 'Add 2.5kg once all sets hit top of range.'),
        _ex('Romanian Deadlift (RDL)', 3, '8-10', 7.0, 90, 'Add 2.5kg every 2 weeks if form stays strict.'),
        _ex('Leg Press', 3, '10-12', 8.0, 90, 'Add one plate per side when RPE drops below 8.'),
        _ex('Standing Calf Raise', 4, '12-15', None, 60, 'Add reps then load.'),
    ],
    'day_4': [  # Shoulders
        _ex('Overhead Barbell Press (OHP)', 4, '6-8', 7.5, 120, 'Add 2.5kg once all sets hit 8 reps.'),
        _ex('Seated Dumbbell Shoulder Press', 3, '8-10', 7.5, 90, 'Add 2kg per dumbbell every 2-3 weeks.'),
        _ex('Dumbbell Lateral Raise', 4, '12-15', None, 60, 'Add reps before load.'),
        _ex('Cable Face Pull', 3, '12-15', None, 60, 'Prioritize scapular control over load.'),
    ],
    'day_5': [  # Arms
        _ex('Dumbbell Bicep Curl', 3, '10-12', None, 60, 'Add weight once 12 reps achieved.'),
        _ex('Hammer Curl', 3, '10-12', None, 60, 'Increase load steadily.'),
        _ex('Tricep Rope Pushdown', 3, '10-12', None, 60, 'Increase load progressively.'),
        _ex('Close-Grip Bench Press', 3, '8-10', 7.5, 90, 'Add load once top of range is clean on all sets.'),
    ],
    'day_6': [],
    'day_7': [],
}

PPL_WORKOUTS = {
    'day_1': [  # Push
        _ex('Barbell Bench Press', 4, '6-8', 7.5, 120, 'Add 2.5kg once all sets hit the top of the rep range.'),
        _ex('Overhead Barbell Press (OHP)', 3, '8-10', 7.5, 120, 'Add 2.5kg once all sets hit 10 reps.'),
        _ex('Incline Dumbbell Press', 3, '8-10', 7.5, 90, 'Add 2kg per dumbbell every 2 weeks.'),
        _ex('Dumbbell Lateral Raise', 3, '12-15', None, 60, 'Add reps before load.'),
        _ex('Tricep Rope Pushdown', 3, '10-12', None, 60, 'Increase load progressively.'),
    ],
    'day_2': [  # Pull
        _ex('Conventional Deadlift', 3, '5', 8.0, 150, 'Add 5kg per week while bar speed stays fast.'),
        _ex('Wide-Grip Lat Pulldown', 4, '8-10', 7.5, 90, 'Increase load once 10 reps hit on all sets.'),
        _ex('Seated Cable Row', 3, '10-12', 7.0, 90, 'Add load steadily every 2 weeks.'),
        _ex('Cable Face Pull', 3, '12-15', None, 60, 'Prioritize scapular control over load.'),
        _ex('Dumbbell Bicep Curl', 3, '10-12', None, 60, 'Add weight once 12 reps achieved.'),
    ],
    'day_3': [  # Legs
        _ex('Barbell Back Squat', 4, '6-8', 7.5, 150, 'Add 2.5kg once all sets hit top of range.'),
        _ex('Romanian Deadlift (RDL)', 3, '8-10', 7.0, 90, 'Add 2.5kg every 2 weeks if form stays strict.'),
        _ex('Bulgarian Split Squat', 3, '10-12', 7.5, 90, 'Add dumbbell weight once both legs hit 12 reps.'),
        _ex('Standing Calf Raise', 4, '12-15', None, 60, 'Add reps then load.'),
    ],
    'day_4': [  # Push
        _ex('Barbell Bench Press', 4, '6-8', 8.0, 120, 'Add 2.5kg per week while bar speed stays fast.'),
        _ex('Seated Dumbbell Shoulder Press', 3, '8-10', 7.5, 90, 'Add 2kg per dumbbell every 2-3 weeks.'),
        _ex('Cable Chest Fly', 3, '12-15', None, 60, 'Add reps before load.'),
        _ex('Close-Grip Bench Press', 3, '8-10', 7.5, 90, 'Add load once top of range is clean on all sets.'),
    ],
    'day_5': [  # Pull
        _ex('Barbell Bent-Over Row', 4, '8-10', 7.5, 120, 'Add load once top of range is hit for all sets.'),
        _ex('Chest-Supported Dumbbell Row', 3, '10-12', 7.5, 90, 'Add load once 12 reps hit across all sets.'),
        _ex('Hammer Curl', 3, '10-12', None, 60, 'Increase load steadily.'),
        _ex('Hanging Leg Raise', 3, '12-15', None, 60, 'Add reps before adding a weighted vest.'),
    ],
    'day_6': [  # Legs
        _ex('Leg Press', 4, '10-12', 8.0, 90, 'Add one plate per side when RPE drops below 8.'),
        _ex('Walking Lunge', 3, '12 per leg', 7.5, 90, 'Add dumbbells once bodyweight reps feel easy.'),
        _ex('Lying Leg Curl', 3, '10-12', 8.0, 90, 'Add weight in small increments weekly.'),
        _ex('Rowing Machine', 1, '15 min Zone 2', None, 0, 'Increase duration gradually every 2 weeks.', is_cardio=True),
    ],
    'day_7': [],
}

UPPER_LOWER_WORKOUTS = {
    'day_1': [  # Upper
        _ex('Barbell Bench Press', 4, '6-8', 7.5, 120, 'Add 2.5kg once all sets hit the top of the rep range.'),
        _ex('Barbell Bent-Over Row', 4, '8-10', 7.5, 120, 'Add load once top of range is hit for all sets.'),
        _ex('Seated Dumbbell Shoulder Press', 3, '8-10', 7.5, 90, 'Add 2kg per dumbbell every 2-3 weeks.'),
        _ex('Wide-Grip Lat Pulldown', 3, '8-10', 7.5, 90, 'Increase load once 10 reps hit on all sets.'),
        _ex('Dumbbell Bicep Curl', 3, '10-12', None, 60, 'Add weight once 12 reps achieved.'),
        _ex('Tricep Rope Pushdown', 3, '10-12', None, 60, 'Increase load progressively.'),
    ],
    'day_2': [  # Lower
        _ex('Barbell Back Squat', 4, '6-8', 7.5, 150, 'Add 2.5kg once all sets hit top of range.'),
        _ex('Romanian Deadlift (RDL)', 3, '8-10', 7.0, 90, 'Add 2.5kg every 2 weeks if form stays strict.'),
        _ex('Leg Press', 3, '10-12', 8.0, 90, 'Add one plate per side when RPE drops below 8.'),
        _ex('Lying Leg Curl', 3, '10-12', 8.0, 90, 'Add weight in small increments weekly.'),
        _ex('Standing Calf Raise', 4, '12-15', None, 60, 'Add reps then load.'),
    ],
    'day_3': [],
    'day_4': [  # Upper
        _ex('Overhead Barbell Press (OHP)', 4, '6-8', 7.5, 120, 'Add 2.5kg once all sets hit 8 reps.'),
        _ex('Seated Cable Row', 4, '10-12', 7.5, 90, 'Add load steadily every 2 weeks.'),
        _ex('Incline Dumbbell Press', 3, '8-10', 7.5, 90, 'Add 2kg per dumbbell every 2 weeks.'),
        _ex('Cable Face Pull', 3, '12-15', None, 60, 'Prioritize scapular control over load.'),
        _ex('Hammer Curl', 3, '10-12', None, 60, 'Increase load steadily.'),
        _ex('Close-Grip Bench Press', 3, '8-10', 7.5, 90, 'Add load once top of range is clean on all sets.'),
    ],
    'day_5': [  # Lower
        _ex('Conventional Deadlift', 3, '5', 8.0, 150, 'Add 5kg per week while bar speed stays fast.'),
        _ex('Bulgarian Split Squat', 3, '10-12', 7.5, 90, 'Add dumbbell weight once both legs hit 12 reps.'),
        _ex('Leg Extension', 3, '12-15', None, 60, 'Add reps then load.'),
        _ex('Hanging Leg Raise', 3, '12-15', None, 60, 'Add reps before adding a weighted vest.'),
    ],
    'day_6': [],
    'day_7': [],
}

FULL_BODY_WORKOUTS = {
    'day_1': [
        _ex('Barbell Back Squat', 3, '6-8', 7.5, 120, 'Add 2.5kg once all sets hit top of range.'),
        _ex('Barbell Bench Press', 3, '6-8', 7.5, 120, 'Add 2.5kg once all sets hit the top of the rep range.'),
        _ex('Seated Cable Row', 3, '10-12', 7.0, 90, 'Add load steadily every 2 weeks.'),
        _ex('Plank', 3, '30-45 sec', None, 45, 'Increase hold time before adding load.'),
    ],
    'day_2': [],
    'day_3': [
        _ex('Romanian Deadlift (RDL)', 3, '8-10', 7.0, 90, 'Add 2.5kg every 2 weeks if form stays strict.'),
        _ex('Overhead Barbell Press (OHP)', 3, '8-10', 7.5, 90, 'Add 2.5kg once all sets hit 10 reps.'),
        _ex('Wide-Grip Lat Pulldown', 3, '8-10', 7.5, 90, 'Increase load once 10 reps hit on all sets.'),
        _ex('Dumbbell Lateral Raise', 3, '12-15', None, 60, 'Add reps before load.'),
    ],
    'day_4': [],
    'day_5': [
        _ex('Leg Press', 3, '10-12', 8.0, 90, 'Add one plate per side when RPE drops below 8.'),
        _ex('Incline Dumbbell Press', 3, '8-10', 7.5, 90, 'Add 2kg per dumbbell every 2 weeks.'),
        _ex('Barbell Bent-Over Row', 3, '8-10', 7.5, 90, 'Add load once top of range is clean.'),
        _ex('Hanging Leg Raise', 3, '12-15', None, 60, 'Add reps before adding a weighted vest.'),
    ],
    'day_6': [],
    'day_7': [],
}


TRAINING_SPLITS = [
    {
        'slug': 'bro-split',
        'name': 'Bro Split',
        'description': 'Classic 5-day split hitting one major muscle group per session (chest, back, legs, shoulders, arms) for maximum per-muscle volume and focus.',
        'days_per_week': 5,
        'workout_templates': BRO_SPLIT_WORKOUTS,
        'display_order': 1,
    },
    {
        'slug': 'push-pull-legs',
        'name': 'Push Pull Legs (PPL)',
        'description': '6-day rotation through push, pull, and legs twice per week - each muscle group trained at a higher frequency than a bro split.',
        'days_per_week': 6,
        'workout_templates': PPL_WORKOUTS,
        'display_order': 2,
    },
    {
        'slug': 'upper-lower',
        'name': 'Upper / Lower',
        'description': '4-day split alternating upper body and lower body sessions - balances frequency and recovery, well suited to intermediate lifters.',
        'days_per_week': 4,
        'workout_templates': UPPER_LOWER_WORKOUTS,
        'display_order': 3,
    },
    {
        'slug': 'full-body',
        'name': 'Full Body',
        'description': '3-day full-body split hitting every major muscle group each session - highest per-muscle frequency, ideal for beginners or low weekly availability.',
        'days_per_week': 3,
        'workout_templates': FULL_BODY_WORKOUTS,
        'display_order': 4,
    },
]


class Command(BaseCommand):
    help = 'Seeds the TrainingSplit catalog (bro split, PPL, upper/lower, full body). Idempotent.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--wipe',
            action='store_true',
            help='Delete ALL existing training splits first, then re-seed.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options['wipe']:
            self.stdout.write(self.style.WARNING('Wiping all training splits...'))
            TrainingSplit.objects.all().delete()

        created_count = 0
        updated_count = 0
        for split in TRAINING_SPLITS:
            defaults = dict(split)
            slug = defaults.pop('slug')
            _, created = TrainingSplit.objects.get_or_create(slug=slug, defaults=defaults)
            if created:
                created_count += 1
                self.stdout.write(f"  + TrainingSplit: {defaults['name']}")
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nTrainingSplit catalog seeded: {created_count} created, {updated_count} already existed, "
            f"{len(TRAINING_SPLITS)} total."
        ))
