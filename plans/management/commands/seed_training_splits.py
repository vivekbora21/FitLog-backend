"""
Seed the TrainingSplit catalog: classic weekly training structures
(bro split, push/pull/legs, upper/lower, full body) that any Blueprint's
mode (CUT/BULK/FOCUS/RECOMP/HABIT) can be paired with via split_slug.

Usage:
    python manage.py seed_training_splits          # seed everything
    python manage.py seed_training_splits --wipe   # delete all splits first, then re-seed

Idempotent: uses get_or_create on slug, safe to re-run.
"""
from copy import deepcopy

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
        _ex('Seated Cable Row', 3, '10-12', 7.5, 90, 'Add load once 12 reps hit across all sets.'),
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


def _sessions(workouts):
    return [workouts[f'day_{i}'] for i in range(1, 8) if workouts.get(f'day_{i}')]


def _scheduled(sessions, days, cardio=False):
    """Pack authored sessions into an exact weekly schedule without inventing exercises."""
    result = {f'day_{i}': [] for i in range(1, 8)}
    for index, session in enumerate(sessions[:days]):
        result[f'day_{index + 1}'] = list(session)
    if cardio:
        result[f'day_{days}'] = result[f'day_{days}'] + [
            _ex('Rowing Machine', 1, '15 min Zone 2', None, 0, 'Add 2 minutes every two weeks.', is_cardio=True)
        ]
    return result


def _metadata(days, goals=None, experience=None, equipment=None, minutes=60, groups=None):
    return {
        'experience_levels': experience or ['BEGINNER', 'INTERMEDIATE', 'ADVANCED'],
        'compatible_goals': goals or ['CUT', 'BULK', 'RECOMP', 'FOCUS', 'HABIT'],
        'rest_days': [i for i in range(1, 8) if i > days],
        'muscle_groups': groups or ['Chest', 'Back', 'Shoulders', 'Quadriceps', 'Hamstrings', 'Glutes', 'Biceps', 'Triceps', 'Calves', 'Core'],
        'equipment_requirements': equipment or ['full_gym'],
        'estimated_session_minutes': minutes,
        'weekly_volume': {'target_sets_per_muscle_group': {'BEGINNER': '8-12', 'INTERMEDIATE': '10-16', 'ADVANCED': '12-20'}},
        'progression_strategy': 'Double progression: add reps within the prescribed range, then increase load while keeping 1-3 reps in reserve.',
        'recovery_rules': ['Keep at least 48 hours between repeated muscle-group sessions.', 'Take an additional rest day when performance or sleep declines for two sessions.'],
        'approval_status': 'APPROVED',
        'catalog_version': '2.0',
    }


_full_body_sessions = _sessions(FULL_BODY_WORKOUTS)
_full_body_strength_sessions = deepcopy(_full_body_sessions)
for _session in _full_body_strength_sessions:
    for _entry in _session:
        if not _entry.get('is_cardio'):
            _entry['reps'] = '4-6' if _entry['sets'] >= 3 else _entry['reps']
_upper_lower_sessions = _sessions(UPPER_LOWER_WORKOUTS)
_bro_sessions = _sessions(BRO_SPLIT_WORKOUTS)
_ppl_sessions = _sessions(PPL_WORKOUTS)

TRAINING_SPLITS = [
    # 2 days: full-body alternatives with different emphasis.
    {'slug': 'full-body-ab', 'name': 'Full Body A/B', 'description': 'Two alternating full-body sessions for busy schedules, with balanced strength and hypertrophy work.', 'days_per_week': 2, 'workout_templates': _scheduled(_full_body_sessions, 2), 'display_order': 1, **_metadata(2, minutes=55)},
    {'slug': 'full-body-strength', 'name': 'Full Body Strength', 'description': 'Two focused full-body sessions built around compound lifts and conservative progression.', 'days_per_week': 2, 'workout_templates': _scheduled(_full_body_strength_sessions, 2), 'display_order': 2, **_metadata(2, minutes=50, goals=['BULK', 'FOCUS', 'RECOMP'], experience=['INTERMEDIATE', 'ADVANCED'])},
    {'slug': 'full-body-conditioning', 'name': 'Full Body + Conditioning', 'description': 'Full-body resistance training paired with a short conditioning finisher for general fitness.', 'days_per_week': 2, 'workout_templates': _scheduled(_full_body_sessions, 2, cardio=True), 'display_order': 3, **_metadata(2, minutes=60, goals=['CUT', 'FOCUS', 'HABIT'])},
    # 3 days.
    {'slug': 'full-body-abc', 'name': 'Full Body A/B/C', 'description': 'Three varied full-body sessions that distribute weekly volume across the whole body.', 'days_per_week': 3, 'workout_templates': _scheduled(_full_body_sessions, 3), 'display_order': 4, **_metadata(3, minutes=60)},
    {'slug': 'push-pull-legs-3', 'name': 'Push / Pull / Legs', 'description': 'A classic three-day push, pull, and legs schedule with a full rest day between sessions when possible.', 'days_per_week': 3, 'workout_templates': _scheduled(_ppl_sessions, 3), 'display_order': 5, **_metadata(3, minutes=65, experience=['INTERMEDIATE', 'ADVANCED'])},
    {'slug': 'full-body-conditioning-3', 'name': 'Full Body + Conditioning', 'description': 'Three full-body sessions with the final session including low-impact Zone 2 conditioning.', 'days_per_week': 3, 'workout_templates': _scheduled(_full_body_sessions, 3, cardio=True), 'display_order': 6, **_metadata(3, minutes=65, goals=['CUT', 'FOCUS', 'HABIT'])},
    {
        'slug': 'bro-split',
        'name': 'Bro Split',
        'description': 'Classic 5-day split hitting one major muscle group per session (chest, back, legs, shoulders, arms) for maximum per-muscle volume and focus.',
        'days_per_week': 5,
        'workout_templates': BRO_SPLIT_WORKOUTS,
        'display_order': 7,
        **_metadata(5, minutes=65),
    },
    {
        'slug': 'push-pull-legs',
        'name': 'Push Pull Legs (PPL)',
        'description': '6-day rotation through push, pull, and legs twice per week - each muscle group trained at a higher frequency than a bro split.',
        'days_per_week': 6,
        'workout_templates': PPL_WORKOUTS,
        'display_order': 16,
        **_metadata(6, minutes=65),
    },
    {
        'slug': 'upper-lower',
        'name': 'Upper / Lower',
        'description': '4-day split alternating upper body and lower body sessions - balances frequency and recovery, well suited to intermediate lifters.',
        'days_per_week': 4,
        'workout_templates': UPPER_LOWER_WORKOUTS,
        'display_order': 10,
        **_metadata(4, minutes=65),
    },
    {
        'slug': 'full-body',
        'name': 'Full Body',
        'description': '3-day full-body split hitting every major muscle group each session - highest per-muscle frequency, ideal for beginners or low weekly availability.',
        'days_per_week': 3,
        'workout_templates': FULL_BODY_WORKOUTS,
        'display_order': 4,
        **_metadata(3, minutes=60),
    },
    {'slug': 'upper-lower-cardio', 'name': 'Upper / Lower + Cardio', 'description': 'Four upper/lower lifting days with conditioning layered into the final lower session.', 'days_per_week': 4, 'workout_templates': _scheduled(_upper_lower_sessions, 4, cardio=True), 'display_order': 11, **_metadata(4, minutes=70, goals=['CUT', 'FOCUS', 'HABIT'])},
    {'slug': 'four-day-body-part', 'name': 'Four-Day Body-Part Split', 'description': 'A four-day body-part rotation that keeps sessions focused while covering the major movement patterns.', 'days_per_week': 4, 'workout_templates': _scheduled(_bro_sessions[:4], 4), 'display_order': 12, **_metadata(4, minutes=60, experience=['INTERMEDIATE', 'ADVANCED'])},
    {'slug': 'upper-lower-specialization', 'name': 'Upper / Lower with Specialization', 'description': 'Upper/lower structure with extra back, shoulder, and arm work for a selected specialization.', 'days_per_week': 4, 'workout_templates': _scheduled(_upper_lower_sessions, 4), 'display_order': 13, **_metadata(4, minutes=70, experience=['INTERMEDIATE', 'ADVANCED'])},
    {'slug': 'ppl-upper-lower', 'name': 'Push / Pull / Legs + Upper / Lower', 'description': 'Five sessions blending PPL movement balance with upper/lower frequency for flexible hypertrophy.', 'days_per_week': 5, 'workout_templates': _scheduled(_ppl_sessions[:3] + _upper_lower_sessions[:2], 5), 'display_order': 8, **_metadata(5, minutes=65, experience=['INTERMEDIATE', 'ADVANCED'])},
    {'slug': 'upper-lower-specialization-5', 'name': 'Upper / Lower + Specialization', 'description': 'Four foundational sessions plus a focused specialization day for a lagging muscle group.', 'days_per_week': 5, 'workout_templates': _scheduled(_upper_lower_sessions + [_bro_sessions[3]], 5), 'display_order': 9, **_metadata(5, minutes=65, experience=['INTERMEDIATE', 'ADVANCED'])},
    {'slug': 'five-day-strength-hypertrophy', 'name': 'Five-Day Strength and Hypertrophy', 'description': 'A five-day blend of heavy compound work and moderate-rep volume.', 'days_per_week': 5, 'workout_templates': _scheduled(_upper_lower_sessions + [_ppl_sessions[0]], 5), 'display_order': 14, **_metadata(5, minutes=70, experience=['INTERMEDIATE', 'ADVANCED'])},
    {'slug': 'arnold-split', 'name': 'Arnold Split', 'description': 'Chest/back, shoulders/arms, and legs repeated across six days with a weekly recovery day.', 'days_per_week': 6, 'workout_templates': _scheduled(_ppl_sessions[:3] + _bro_sessions[:3], 6), 'display_order': 17, **_metadata(6, minutes=70, experience=['INTERMEDIATE', 'ADVANCED'])},
    {'slug': 'upper-lower-specialization-6', 'name': 'Upper / Lower + Specialization', 'description': 'Six days alternating upper/lower training with repeated specialization exposure and planned recovery.', 'days_per_week': 6, 'workout_templates': _scheduled(_upper_lower_sessions + _upper_lower_sessions[:2], 6), 'display_order': 18, **_metadata(6, minutes=70, experience=['INTERMEDIATE', 'ADVANCED'])},
    {'slug': 'strength-cardio-hybrid', 'name': 'Strength + Cardio Hybrid', 'description': 'Four resistance sessions plus two low-impact conditioning sessions for strength and fitness.', 'days_per_week': 6, 'workout_templates': _scheduled(_upper_lower_sessions + _ppl_sessions[2:4], 6, cardio=True), 'display_order': 19, **_metadata(6, minutes=65, goals=['CUT', 'FOCUS', 'HABIT'])},
    {'slug': 'six-day-hypertrophy', 'name': 'Six-Day Hypertrophy Split', 'description': 'Higher-frequency hypertrophy training with manageable per-session volume and recovery guidance.', 'days_per_week': 6, 'workout_templates': _scheduled(_ppl_sessions, 6), 'display_order': 20, **_metadata(6, minutes=65, experience=['INTERMEDIATE', 'ADVANCED'])},
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
            _, created = TrainingSplit.objects.update_or_create(slug=slug, defaults=defaults)
            if created:
                created_count += 1
                self.stdout.write(f"  + TrainingSplit: {defaults['name']}")
            else:
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nTrainingSplit catalog seeded: {created_count} created, {updated_count} already existed, "
            f"{len(TRAINING_SPLITS)} total."
        ))
