"""
Seeds Vivek's real 60-day recomposition journey with the exact plan, actual logged
workouts, diet totals, cardio, and progress tracker entries from his personal
workbook "New start (3).xlsx" (or "New start.xlsx").

Seeds for both svivek431@gmail.com and vivek.singh@talentelgia.com.
Idempotent: safe to re-run. Auto-creates accounts if not already registered.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
import os
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from users.models import User, UserProfile
from exercises.models import MuscleGroup, EquipmentType, Exercise
from workouts.models import (
    Routine, RoutineExercise, JourneyProgram, ProgramDay,
    WorkoutSession, WorkoutExercise, WorkoutSet, CardioEntry,
)
from nutrition.defaults import DIET_PLAN_OPTION_A_TARGETS
from nutrition.models import MacroTarget, NutritionDay, MealEntry, Food
from progress.models import WeightEntry, BodyMeasurement, PersonalRecord, DailyLog

VIVEK_EMAIL = os.environ.get("VIVEK_EMAIL", "svivek431@gmail.com")


def dt(day_date, hour=7, minute=0):
    return datetime(day_date.year, day_date.month, day_date.day, hour, minute, tzinfo=dt_timezone.utc)


class Command(BaseCommand):
    help = "Seeds Vivek's real 60-day workout/diet/progress journey from 'New start (3).xlsx' onto his account."

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default=None,
            help="Path to 'New start (3).xlsx'. Defaults to repo root if present."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        excel_path = options.get('file')
        if not excel_path:
            candidates = [
                Path(settings.BASE_DIR).parent / "New start (3).xlsx",
                Path(settings.BASE_DIR) / "New start (3).xlsx",
                Path(settings.BASE_DIR).parent / "New start.xlsx",
                Path(settings.BASE_DIR) / "New start.xlsx",
            ]
            for c in candidates:
                if c.exists():
                    excel_path = str(c)
                    break

        if excel_path and os.path.exists(excel_path):
            self.stdout.write(f"Workbook found: {excel_path}")

        demo_password = os.environ.get('FITLOG_DEMO_PASSWORD', 'fitlog123')
        target_emails = [
            VIVEK_EMAIL,
            "vivek.singh@talentelgia.com",
        ]
        # Deduplicate while preserving order
        target_emails = list(dict.fromkeys(target_emails))

        # Shared Reference Data: Muscle groups & Equipment
        muscle_names = [
            ('Chest', 'chest'), ('Back', 'back'), ('Shoulders', 'shoulders'),
            ('Biceps', 'biceps'), ('Triceps', 'triceps'), ('Quadriceps', 'quadriceps'),
            ('Hamstrings', 'hamstrings'), ('Calves', 'calves'), ('Core', 'core'),
            ('Cardio', 'cardio'),
        ]
        muscles = {slug: MuscleGroup.objects.get_or_create(name=name, slug=slug)[0] for name, slug in muscle_names}

        equipment_names = [
            ('Barbell', 'barbell'), ('Dumbbell', 'dumbbell'), ('Cable', 'cable'),
            ('Machine', 'machine'), ('Bodyweight', 'bodyweight'), ('Cardio Equipment', 'cardio-equipment'),
            ('Kettlebell', 'kettlebell'),
        ]
        equipments = {slug: EquipmentType.objects.get_or_create(name=name, slug=slug)[0] for name, slug in equipment_names}

        def ex(name, slug, muscle_slug, equip_slug, instructions=''):
            obj, _ = Exercise.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name, 'gym': None,
                    'primary_muscle': muscles[muscle_slug],
                    'equipment': equipments[equip_slug],
                    'instructions': instructions,
                }
            )
            return obj

        # Exercise Catalog
        E = {
            'warmup_incline_bike': ex('Incline Treadmill Walk / Bike Warm-up', 'warmup-incline-treadmill-bike', 'cardio', 'cardio-equipment'),
            'warmup_rowing_tspine': ex('Rowing Machine / Dynamic T-Spine Mobility', 'warmup-rowing-tspine', 'cardio', 'cardio-equipment', 'Activate lats and posterior chain.'),
            'warmup_bike_hip': ex('Stationary Bike / Hip Mobility Flow', 'warmup-bike-hip-mobility', 'cardio', 'cardio-equipment', 'Open hips, ankles, and knee joints.'),
            'warmup_treadmill_band': ex('Treadmill Walk / Band Shoulder Dislocates', 'warmup-treadmill-band-dislocates', 'cardio', 'cardio-equipment'),
            'warmup_row_bike_mobility': ex('Rowing / Bike / Dynamic Mobility', 'warmup-rowing-bike-mobility', 'cardio', 'cardio-equipment', 'Joint lubrication and heart rate warmup.'),
            'warmup_treadmill_bw': ex('Treadmill / Dynamic Bodyweight Warm-up', 'warmup-treadmill-bodyweight', 'cardio', 'cardio-equipment', 'Full kinetic chain mobilization.'),

            'cardio_incline_12': ex('Incline Treadmill Walk (12% Incline, 4.8 km/h)', 'cardio-incline-walk-12-48', 'cardio', 'cardio-equipment'),
            'cardio_elliptical': ex('Elliptical Steady-State', 'cardio-elliptical-steady-state', 'cardio', 'cardio-equipment'),
            'cardio_bike_low': ex('Stationary Bike (Low Impact)', 'cardio-stationary-bike-low-impact', 'cardio', 'cardio-equipment'),
            'cardio_incline_10': ex('Incline Treadmill Walk (10% Incline, 5.0 km/h)', 'cardio-incline-walk-10-50', 'cardio', 'cardio-equipment'),
            'cardio_elliptical_stair': ex('Elliptical / Stair Climber Steady-State', 'cardio-elliptical-stair-climber', 'cardio', 'cardio-equipment'),
            'cardio_long_moderate': ex('Long Moderate Cardio (Bike / Incline Walk)', 'cardio-long-moderate-bike-incline', 'cardio', 'cardio-equipment'),
            'recovery_walk': ex('Light Mobility Walk', 'recovery-light-mobility-walk', 'cardio', 'bodyweight'),

            'bench_press': ex('Machine Chest Press / Barbell Bench Press', 'machine-barbell-bench-press', 'chest', 'barbell', 'Lower bar with control to mid-chest, press upward driving through heels.'),
            'incline_db_bench': ex('Incline Dumbbell Bench Press (30°)', 'incline-db-bench-press-30', 'chest', 'dumbbell', 'Set incline to 30 degrees; press dumbbells over clavicles.'),
            'cable_pec_fly': ex('Cable Pec Fly / Low-to-High Fly', 'cable-pec-fly-low-to-high', 'chest', 'cable', 'Squeeze pecs together with a slight bend in the elbows.'),
            'pec_deck_fly': ex('Pec Deck Machine Fly', 'pec-deck-machine-fly', 'chest', 'machine', 'Isolated chest stretch and peak squeeze.'),
            'machine_flat_db_press': ex('Machine / Flat Dumbbell Chest Press', 'machine-flat-db-chest-press', 'chest', 'machine', 'Hypertrophy pump and muscular endurance.'),
            'pushups': ex('Push-ups (Bodyweight)', 'pushups-bodyweight', 'chest', 'bodyweight', 'Strict core plank, lower until chest touches ground, lock out.'),
            'down_to_up_fly': ex('Down-to-Up Dumbbell Chest Fly', 'down-to-up-db-chest-fly', 'chest', 'dumbbell', 'Constant upward tension & peak squeeze.'),
            'low_to_high_db_fly': ex('Low-to-High Dumbbell Chest Fly', 'low-to-high-db-chest-fly', 'chest', 'dumbbell', 'Continuous upward tension, hard upper-chest contraction.'),

            'rope_pushdown': ex('Rope Triceps Pushdown', 'rope-triceps-pushdown', 'triceps', 'cable', 'Pin elbows to ribs, flared lockout.'),
            'v_grip_pushdown': ex('V-Grip Triceps Pushdown', 'v-grip-triceps-pushdown', 'triceps', 'cable', 'Elbows tucked, clean lockouts, solid triceps lateral head pump.'),
            'overhead_tricep_ext': ex('Overhead Cable Triceps Extension', 'overhead-cable-triceps-extension', 'triceps', 'cable', 'Full long-head triceps stretch, elbows tucked in close.'),
            'db_overhead_ext': ex('Dumbbell Overhead Extension', 'dumbbell-overhead-extension', 'triceps', 'dumbbell', 'Deep long-head stretch, elbows tucked in close.'),

            'hanging_leg_raise': ex('Hanging Knee / Leg Raise', 'hanging-knee-leg-raise', 'core', 'bodyweight', 'Controlled cadence, strict core focus.'),
            'ab_wheel_rollout': ex('Ab Wheel Rollout / Cable Crunch', 'ab-wheel-rollout-cable-crunch', 'core', 'cable', 'Braced abdominal core throughout.'),
            'cable_kneeling_crunch': ex('Cable Kneeling Crunch', 'cable-kneeling-crunch', 'core', 'cable', 'Deep abdominal contraction.'),
            'plank_weighted': ex('Plank (Weighted if feasible)', 'plank-weighted', 'core', 'bodyweight', 'Pelvic neutral, active glute squeeze.'),
            'ab_machine_crunch': ex('Ab Machine Crunch', 'ab-machine-crunch', 'core', 'machine', 'Focused spinal flexion and controlled core contraction.'),
            'situps': ex('Sit-ups (Bodyweight)', 'situps-bodyweight', 'core', 'bodyweight', 'Controlled abdominal flexion, full range.'),
            'kb_side_bend': ex('Kettlebell Side Bend', 'kettlebell-side-bend', 'core', 'kettlebell', 'Strict lateral flexion, engaged obliques, controlled tempo.'),

            'deadlift': ex('Conventional / Romanian Deadlift', 'conventional-romanian-deadlift', 'back', 'barbell', 'Hinge at hips, brace core, pull bar close to shins with a neutral spine.'),
            'lat_pulldown_wide': ex('Wide-Grip Lat Pulldown', 'wide-grip-lat-pulldown', 'back', 'cable', 'Drive elbows to pockets.'),
            'lat_pulldown_neutral': ex('Neutral-Grip Lat Pulldown', 'neutral-grip-lat-pulldown', 'back', 'cable', 'Full lat engagement, elbows tucked.'),
            'seated_cable_row': ex('Seated Cable Row (Neutral V-Grip)', 'seated-cable-row-neutral', 'back', 'cable', 'Strict scapular retraction, full eccentric lat stretch.'),
            'db_row_chest_supported': ex('Chest-Supported Dumbbell Row', 'chest-supported-db-row', 'back', 'dumbbell', 'Mid-back density without lower-back strain.'),
            'close_grip_row': ex('Close-Grip Seated Cable Row', 'close-grip-seated-cable-row', 'back', 'cable', 'Rhomboids and lat width reinforcement.'),
            'up_down_row': ex('Up-Down Rowing Machine', 'up-down-rowing-machine', 'back', 'machine', 'Full scapular retraction, strong mid-back squeeze.'),
            'face_pull': ex('Face Pull (External Rotation)', 'face-pull-external-rotation', 'shoulders', 'cable', 'High pulley to eye level, thumbs back, no momentum.'),

            'incline_db_curl': ex('Incline Dumbbell Biceps Curl', 'incline-db-biceps-curl', 'biceps', 'dumbbell', 'Seated incline, deep stretch on the biceps long head.'),
            'hammer_curl': ex('Standing Hammer Curl', 'standing-hammer-curl', 'biceps', 'dumbbell', 'Neutral grip, brachialis overload, zero swing.'),
            'preacher_curl': ex('EZ-Bar Preacher / Spider Curl', 'ez-bar-preacher-spider-curl', 'biceps', 'barbell', 'Strict biceps peak contraction, no hyperextension.'),

            'leg_press_squat': ex('Heavy Leg Press / Barbell Squat', 'heavy-leg-press-barbell-squat', 'quadriceps', 'machine', 'Full depth, knee tracking over toes.'),
            'bodyweight_squat': ex('Bodyweight Squat', 'bodyweight-squat', 'quadriceps', 'bodyweight', 'Clean depth, hip mobility primer and quad activation.'),
            'hack_squat': ex('Hack Squat / Leg Press', 'hack-squat-leg-press', 'quadriceps', 'machine', 'Controlled eccentric, full knee flexion.'),
            'leg_extension': ex('Seated Leg Extension', 'seated-leg-extension', 'quadriceps', 'machine', '1-second pause at peak knee extension.'),
            'goblet_squat': ex('Goblet Squat / Dumbbell Bulgarian Split Squat', 'goblet-squat-bulgarian-split', 'quadriceps', 'dumbbell', 'Unilateral leg balance and quad strength.'),
            'db_rdl': ex('Dumbbell Romanian Deadlift (RDL)', 'db-romanian-deadlift', 'hamstrings', 'dumbbell', 'Push hips back; slight knee bend; controlled eccentric.'),
            'leg_curl': ex('Lying / Seated Leg Curl', 'lying-seated-leg-curl', 'hamstrings', 'machine', 'Control eccentric tempo (2 sec down).'),
            'calf_raise': ex('Standing Calf Raise (Calf Machine)', 'standing-calf-raise-machine', 'calves', 'machine', '2-second stretch at bottom, drive through the big toe.'),

            'ohp': ex('Dumbbell / Barbell Overhead Press (OHP)', 'db-barbell-ohp', 'shoulders', 'barbell', 'Press overhead from collarbone to lockout with engaged core.'),
            'db_shoulder_press': ex('Dumbbell Shoulder Press', 'dumbbell-shoulder-press', 'shoulders', 'dumbbell', 'Strong overhead stability, clean lockouts on all sets.'),
            'side_lateral_raise': ex('Side Lateral Raise', 'side-lateral-raise', 'shoulders', 'dumbbell', 'Strict control, lead with elbows, paused contraction at top.'),
            'lateral_raise_cable': ex('Lean-Away Cable Lateral Raise', 'lean-away-cable-lateral-raise', 'shoulders', 'cable', 'Strict form, lead with elbows, paused contraction at top.'),
            'rear_db_fly': ex('Rear Dumbbell Fly', 'rear-dumbbell-fly', 'shoulders', 'dumbbell', 'Posterior delt isolation, slight elbow bend, scapular control.'),
            'rear_delt_fly': ex('Reverse Pec Deck Fly / Rear Delt Fly', 'reverse-pec-deck-rear-delt-fly', 'shoulders', 'machine', 'Clean scapular retraction.'),
            'arnold_press': ex('Seated Dumbbell Arnold Press', 'seated-db-arnold-press', 'shoulders', 'dumbbell', 'Full shoulder 3D rotational coverage.'),
        }

        # Seed high-protein staples into Food catalog globally
        staples = [
            ('Soya Chunks (Dry)', '40g dry weighed', 138, 21.0, 13.0, 0.5),
            ('Whole Farm Eggs', '3 large eggs', 210, 19.0, 1.5, 14.5),
            ('Skinless Chicken Breast', '100g raw weighed', 120, 31.0, 0.0, 2.5),
            ('Yellow Moong / Masoor Dal', '60g raw (1 cup cooked)', 205, 14.0, 35.0, 1.0),
            ('Homemade Low-Fat Dahi', '200g set curd', 120, 9.0, 12.0, 4.0),
            ('Roasted Chana (Bengal Gram)', '50g dry weighed', 180, 11.0, 29.0, 3.0),
            ('Rolled Oats (Plain)', '60g dry weighed', 230, 8.0, 40.0, 4.5),
        ]
        for s_name, serving, kcal, prot, carb, fat in staples:
            Food.objects.get_or_create(
                owner=None, name=s_name,
                defaults={'serving_label': serving, 'calories': kcal, 'protein_g': prot, 'carbs_g': carb, 'fat_g': fat}
            )

        # Seed data for each target account
        for email in target_emails:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'username': email.split('@')[0],
                    'first_name': 'Vivek',
                    'last_name': 'Singh',
                }
            )
            if created:
                user.set_password(demo_password)
                user.save()
                self.stdout.write(f"Created account for {email} with default password.")
            else:
                self.stdout.write(f"Updating data for existing account {email}.")

            self.stdout.write(f"Seeding 60-day journey from 'New start (3).xlsx' for {user.email} (id={user.id})...")

            # 1. Profile
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.height_cm = 175.0
            profile.weight_kg = 78.02  # Latest scale weight from Day 10–12 check-in
            profile.date_of_birth = date(1995, 3, 15)  # 31 yo
            profile.sex = 'MALE'
            profile.activity_level = 'MODERATE'
            profile.fitness_goal = 'FAT_LOSS'
            profile.save()

            # 2. Routines (Day 1-7 prescriptions from workbook)
            def routine(name, description):
                r, _ = Routine.objects.get_or_create(name=name, user=user, defaults={'description': description})
                return r

            def add(r, order, exercise, sets, reps, rest, focus, rpe=None, weight=None, notes=''):
                RoutineExercise.objects.get_or_create(
                    routine=r, exercise=exercise, order=order,
                    defaults={
                        'target_sets': sets, 'target_reps': str(reps),
                        'rest_seconds': rest, 'target_rpe': rpe,
                        'suggested_weight_kg': weight, 'focus': focus, 'notes': notes,
                    }
                )

            day1 = routine('Day 1: Chest, Triceps & Abs', 'Push focus: Horizontal press and direct triceps loading.')
            add(day1, 1, E['warmup_incline_bike'], 1, '5-10 min', 0, 'Warm-up', 4.5)
            add(day1, 2, E['bench_press'], 3, '8-10', 120, 'Chest (Anchor)', 8.5, 50, 'Barbell or machine flat press. Smooth cadence.')
            add(day1, 3, E['incline_db_bench'], 3, '8-10', 105, 'Chest', 8, 17.5, '30-degree incline for clavicular pecs.')
            add(day1, 4, E['cable_pec_fly'], 3, '10-12', 60, 'Chest', 8, 10, 'Continuous cable tension.')
            add(day1, 5, E['rope_pushdown'], 3, '10-12', 60, 'Triceps', 8, 30, 'Flared at lockout, elbows pinned.')
            add(day1, 6, E['overhead_tricep_ext'], 3, '10-12', 60, 'Triceps', 7.5, 5.0)
            add(day1, 7, E['pushups'], 3, '12-15', 50, 'Core', 8, None, 'Superset with leg raises.')
            add(day1, 8, E['hanging_leg_raise'], 3, '12-15', 50, 'Core', 8)
            add(day1, 9, E['cardio_incline_12'], 1, '15-25 min (Ramp-Up)', 0, 'Cardio (Fat Loss)', None, None, 'Weeks 1-2 ramp-up toward the weekly target.')

            day2 = routine('Day 2: Back, Biceps & Rear Delts', 'Heavy upper pull and lats.')
            add(day2, 1, E['warmup_rowing_tspine'], 1, '5-10 min', 0, 'Warm-up', 4.5)
            add(day2, 2, E['deadlift'], 3, '4-6', 150, 'Back (Anchor)', 8.5, 55, 'Rebuild hinge mechanics and posterior chain.')
            add(day2, 3, E['lat_pulldown_wide'], 3, '8-10', 90, 'Back', 8, 52.5)
            add(day2, 4, E['seated_cable_row'], 3, '10-12', 75, 'Back', 8, 47.5)
            add(day2, 5, E['face_pull'], 3, '12-15', 60, 'Back / Posture', 7.5, 13.75)
            add(day2, 6, E['incline_db_curl'], 3, '10-12', 60, 'Biceps', 8, 11)
            add(day2, 7, E['hammer_curl'], 2, '10-12', 60, 'Biceps', 8, 12)
            add(day2, 8, E['cardio_elliptical'], 1, '25-30 min', 0, 'Cardio (Fat Loss)', None, None, 'Target HR 125-135 bpm; steady pace Zone 2.')

            day3 = routine('Day 3: Quads, Hamstrings & Calves', 'Lower body power and core.')
            add(day3, 1, E['warmup_bike_hip'], 1, '5-10 min', 0, 'Warm-up', 4.5)
            add(day3, 2, E['leg_press_squat'], 3, '4-6', 150, 'Quads (Anchor)', 8.5, 140, 'Full depth, knee tracking over toes.')
            add(day3, 3, E['db_rdl'], 3, '8-10', 105, 'Hamstrings', 8, 24)
            add(day3, 4, E['leg_extension'], 3, '10-12', 68, 'Quads', 8, 45)
            add(day3, 5, E['leg_curl'], 3, '10-12', 68, 'Hamstrings', 8, 40)
            add(day3, 6, E['calf_raise'], 3, '12-15', 60, 'Calves', 8, 50)
            add(day3, 7, E['ab_wheel_rollout'], 3, '12-15', 50, 'Core', 8)
            add(day3, 8, E['cardio_bike_low'], 1, '20-25 min', 0, 'Cardio (Fat Loss)', None, None, 'Active flush for legs; steady cadence.')

            day4 = routine('Day 4: Shoulders, Arms & Abs', 'Delts and direct arm hypertrophy.')
            add(day4, 1, E['warmup_treadmill_band'], 1, '5-10 min', 0, 'Warm-up', 4.5)
            add(day4, 2, E['ohp'], 3, '4-6', 150, 'Shoulders (Anchor)', 8.5, 20, 'Solid overhead control and lockout.')
            add(day4, 3, E['lateral_raise_cable'], 4, '12-15', 60, 'Shoulders', 8, 7.5)
            add(day4, 4, E['rear_delt_fly'], 3, '12-15', 60, 'Shoulders', 8, 40)
            add(day4, 5, E['preacher_curl'], 3, '10-12', 60, 'Biceps', 8, 25)
            add(day4, 6, E['overhead_tricep_ext'], 3, '10-12', 60, 'Triceps', 8, 20)
            add(day4, 7, E['cable_kneeling_crunch'], 3, '12-15', 50, 'Core', 8, 40)
            add(day4, 8, E['cardio_incline_10'], 1, '25-30 min', 0, 'Cardio (Fat Loss)', None, None)

            day5 = routine('Day 5: Upper Hypertrophy & Legs', 'Kinetic balance and unilateral legs.')
            add(day5, 1, E['warmup_row_bike_mobility'], 1, '5-10 min', 0, 'Warm-up', 4.5)
            add(day5, 2, E['incline_db_bench'], 3, '6-8', 120, 'Upper Body (Anchor)', 8.5, 24, 'Secondary chest stimulus.')
            add(day5, 3, E['lat_pulldown_neutral'], 3, '8-10', 90, 'Upper Body', 8, 55)
            add(day5, 4, E['db_row_chest_supported'], 3, '10-12', 75, 'Upper Body', 8, 22)
            add(day5, 5, E['pec_deck_fly'], 3, '12-15', 60, 'Upper Body', 7.5, 45)
            add(day5, 6, E['goblet_squat'], 3, '8-10 / leg', 90, 'Legs', 8, 24)
            add(day5, 7, E['plank_weighted'], 3, '45-60 sec', 45, 'Core', 8)
            add(day5, 8, E['cardio_elliptical_stair'], 1, '25-30 min', 0, 'Cardio (Fat Loss)', None, None)

            day6 = routine('Day 6 (Optional): Full Body Pump', 'Volume reinforcement and conditioning.')
            add(day6, 1, E['warmup_treadmill_bw'], 1, '5-10 min', 0, 'Warm-up', 4.5)
            add(day6, 2, E['hack_squat'], 3, '10-12', 90, 'Full Body', 7.5, 110)
            add(day6, 3, E['machine_flat_db_press'], 3, '10-12', 82, 'Full Body', 7.5, 22)
            add(day6, 4, E['close_grip_row'], 3, '10-12', 82, 'Full Body', 7.5, 45)
            add(day6, 5, E['db_rdl'], 3, '10-12', 90, 'Full Body', 7.5, 20)
            add(day6, 6, E['arnold_press'], 2, '10-12', 68, 'Full Body', 7.5, 14)
            add(day6, 7, E['cable_kneeling_crunch'], 3, '12-15', 50, 'Core', 7.5, 35)
            add(day6, 8, E['cardio_long_moderate'], 1, '35-45 min', 0, 'Cardio (Aerobic Base)', None, None)

            day7 = routine('Day 7: Full Rest & Meal Prep', 'Complete systemic and CNS recovery.')
            add(day7, 1, E['recovery_walk'], 1, '20-30 min (Optional)', 0, 'Recovery', None, None)

            weekly_cycle = [
                (day1, 'Day 1: Chest, Triceps & Abs', False),
                (day2, 'Day 2: Back, Biceps & Rear Delts', False),
                (day3, 'Day 3: Quads, Hamstrings & Calves', False),
                (day4, 'Day 4: Shoulders, Arms & Abs', False),
                (day5, 'Day 5: Upper Hypertrophy & Legs', False),
                (day6, 'Day 6: Rest / Active Recovery', True),
                (day7, 'Day 7: Full Rest & Recovery', True),
            ]

            # 3. 60-Day Journey Program
            JourneyProgram.objects.filter(user=user, active=True).exclude(name='60-Day Fitness Journey').update(active=False)
            program, _ = JourneyProgram.objects.get_or_create(
                user=user, active=True,
                defaults={
                    'name': '60-Day Fitness Journey',
                    'mode': 'RECOMP',
                    'start_date': date(2026, 9, 14),
                    'duration_days': 60,
                    'current_day': 12,
                    'start_weight_kg': 77.76,
                    'target_weight_kg': 74.0,
                    'target_weekly_rate_kg': -0.44,
                    'target_cardio_minutes_early': 120,
                    'target_cardio_minutes_later': 150,
                }
            )
            program.mode = 'RECOMP'
            program.current_day = 12
            program.start_weight_kg = 77.76
            program.target_weight_kg = 74.0
            program.target_weekly_rate_kg = -0.44
            program.target_cardio_minutes_early = 120
            program.target_cardio_minutes_later = 150
            program.save()

            for number in range(1, 61):
                r, label, optional = weekly_cycle[(number - 1) % 7]
                ProgramDay.objects.get_or_create(
                    program=program, day_number=number,
                    defaults={'routine': r, 'label': label, 'is_optional': optional}
                )

            # 4. Actual logged workout sessions
            def log_session(day_number, day_date, routine_obj, title, notes, overall_rpe, duration_min, lifts):
                session, _ = WorkoutSession.objects.get_or_create(
                    user=user, routine=routine_obj, started_at=dt(day_date),
                    defaults={
                        'title': title, 'completed_at': dt(day_date) + timedelta(minutes=duration_min),
                        'duration_seconds': duration_min * 60, 'overall_rpe': overall_rpe, 'notes': notes,
                    }
                )
                session.title = title
                session.completed_at = dt(day_date) + timedelta(minutes=duration_min)
                session.duration_seconds = duration_min * 60
                session.overall_rpe = overall_rpe
                session.notes = notes
                session.save()

                session.exercises.all().delete()

                for order, (exercise, rest, sets) in enumerate(lifts, start=1):
                    we = WorkoutExercise.objects.create(session=session, exercise=exercise, order=order, rest_seconds=rest)
                    for set_number, (set_type, weight, reps) in enumerate(sets, start=1):
                        WorkoutSet.objects.create(
                            workout_exercise=we, set_number=set_number, set_type=set_type,
                            weight_kg=weight, reps=reps, completed=True,
                        )
                        if weight > 0 and reps > 0:
                            est_1rm = PersonalRecord.calculate_epley_1rm(weight, reps)
                            pr, made = PersonalRecord.objects.get_or_create(
                                user=user, exercise=exercise,
                                defaults={'max_weight_kg': weight, 'reps': reps, 'estimated_one_rep_max': est_1rm, 'achieved_at': day_date}
                            )
                            if not made and est_1rm > pr.estimated_one_rep_max:
                                pr.max_weight_kg, pr.reps, pr.estimated_one_rep_max, pr.achieved_at = weight, reps, est_1rm, day_date
                                pr.save()
                ProgramDay.objects.filter(program=program, day_number=day_number).update(status='COMPLETED', completed_session=session)
                return session

            N, W = 'NORMAL', 'WARMUP'

            # Day 1: 2026-09-14 (Push)
            log_session(1, date(2026, 9, 14), day1, 'Day 1: Chest, Triceps & Abs',
                'Day 1 baseline: 77.76 kg. Full Push workout & 16.5m cardio completed.', 8.5, 66, [
                    (E['bench_press'], 150, [(N, 50, 10), (N, 50, 10), (N, 50, 8)]),
                    (E['incline_db_bench'], 105, [(N, 17.5, 12), (N, 17.5, 10), (N, 17.5, 6)]),
                    (E['down_to_up_fly'], 60, [(N, 5.0, 10), (N, 5.0, 10), (N, 5.0, 10)]),
                    (E['rope_pushdown'], 60, [(N, 30, 10), (N, 30, 10), (N, 30, 8)]),
                    (E['overhead_tricep_ext'], 60, [(N, 5.0, 10), (N, 5.0, 10), (N, 5.0, 10)]),
                    (E['pushups'], 50, [(N, 0, 12), (N, 0, 12), (N, 0, 12)]),
                    (E['hanging_leg_raise'], 50, [(N, 0, 10), (N, 0, 10), (N, 0, 10)]),
                ])
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 14),
                defaults={'modality': 'CROSS_TRAINER', 'duration_minutes': 17, 'intensity': 'Zone 2 (Moderate)',
                          'target_zone': '10m Bike + 6.5m Cross Trainer', 'completed': True}
            )

            # Day 2: 2026-09-15 (Pull)
            log_session(2, date(2026, 9, 15), day2, 'Day 2: Back, Biceps & Rear Delts',
                '4 sets (40kg x8 feeler, 3x8 @ 60kg working sets). Solid hinge mechanics, explosive lockout.', 8.5, 82, [
                    (E['deadlift'], 150, [(W, 40, 8), (N, 60, 8), (N, 60, 8), (N, 60, 8)]),
                    (E['lat_pulldown_wide'], 90, [(N, 30, 15), (N, 30, 12), (N, 35, 12)]),
                    (E['seated_cable_row'], 75, [(N, 30, 12), (N, 30, 12), (N, 30, 12)]),
                    (E['face_pull'], 60, [(N, 25, 12), (N, 25, 12), (N, 25, 12)]),
                    (E['incline_db_curl'], 60, [(N, 5.0, 12), (N, 5.0, 12), (N, 5.0, 10)]),
                    (E['hammer_curl'], 60, [(N, 10.0, 12), (N, 10.0, 12), (N, 10.0, 12)]),
                ])
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 15),
                defaults={'modality': 'CYCLING', 'duration_minutes': 22, 'intensity': 'Zone 2',
                          'target_zone': '12m Bike + 10m Incline Treadmill', 'completed': True}
            )

            # Day 3: 2026-09-16 (Legs)
            log_session(3, date(2026, 9, 16), day3, 'Day 3: Quads, Hamstrings & Calves',
                'Waist at 91.0 cm after this session. Bodyweight/hack squat lead-in, then leg press block.', 8.5, 80, [
                    (E['bodyweight_squat'], 60, [(W, 0, 10), (W, 0, 10), (W, 0, 10)]),
                    (E['hack_squat'], 90, [(N, 15, 10), (N, 15, 10), (N, 15, 10)]),
                    (E['leg_press_squat'], 150, [(N, 50, 10), (N, 50, 10), (N, 50, 10)]),
                    (E['leg_extension'], 68, [(N, 30, 12), (N, 30, 10), (N, 30, 12)]),
                    (E['leg_curl'], 68, [(N, 20, 12), (N, 20, 12), (N, 20, 12)]),
                    (E['calf_raise'], 60, [(N, 0, 15), (N, 0, 15), (N, 0, 15)]),
                    (E['ab_machine_crunch'], 50, [(N, 0, 20), (N, 0, 18), (N, 0, 18)]),
                ])
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 16),
                defaults={'modality': 'CROSS_TRAINER', 'duration_minutes': 18, 'intensity': 'Zone 2',
                          'target_zone': '6m Cross Trainer + 12m Bike', 'completed': True}
            )

            # Day 4: 2026-09-17 (Shoulders & Arms)
            log_session(4, date(2026, 9, 17), day4, 'Day 4: Shoulders, Arms & Abs',
                'Waist -2.0 cm net reduction from Day 1. Solid overhead control on DB Shoulder Press.', 8.5, 82, [
                    (E['db_shoulder_press'], 150, [(N, 12.5, 12), (N, 12.5, 12), (N, 12.5, 12)]),
                    (E['side_lateral_raise'], 60, [(N, 5.0, 12), (N, 5.0, 12), (N, 5.0, 12)]),
                    (E['rear_db_fly'], 60, [(N, 5.0, 12), (N, 5.0, 12), (N, 5.0, 12)]),
                    (E['preacher_curl'], 60, [(N, 20, 12), (N, 20, 12), (N, 20, 12)]),
                    (E['db_overhead_ext'], 60, [(N, 12.5, 12), (N, 12.5, 12), (N, 12.5, 12)]),
                    (E['situps'], 50, [(N, 0, 15), (N, 0, 15), (N, 0, 15)]),
                ])
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 17),
                defaults={'modality': 'TREADMILL', 'duration_minutes': 21, 'intensity': 'Zone 2',
                          'target_zone': '8m @ 6% 6km/h + 13m @ 10% 5km/h', 'completed': True}
            )

            # Day 5: 2026-09-18 (Upper / Legs)
            log_session(5, date(2026, 9, 18), day5, 'Day 5: Upper Hypertrophy & Legs',
                'Day 5: 77.84 kg. Upper/Legs session & 23m cardio completed.', 8.0, 75, [
                    (E['incline_db_bench'], 120, [(N, 15, 12), (N, 15, 12), (N, 15, 12)]),
                    (E['lat_pulldown_neutral'], 90, [(N, 35, 12), (N, 35, 12), (N, 35, 12)]),
                    (E['db_row_chest_supported'], 75, [(N, 15, 12), (N, 15, 12), (N, 15, 12)]),
                    (E['pec_deck_fly'], 60, [(N, 20, 12), (N, 20, 12), (N, 20, 12)]),
                    (E['goblet_squat'], 90, [(N, 15, 12), (N, 15, 12), (N, 15, 12)]),
                    (E['ab_machine_crunch'], 50, [(N, 7.0, 15), (N, 7.0, 15), (N, 7.0, 15)]),
                ])
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 18),
                defaults={'modality': 'TREADMILL', 'duration_minutes': 23, 'intensity': 'Zone 2',
                          'target_zone': '9m Treadmill 6% + 14m Cross Trainer', 'completed': True}
            )

            # Day 6: 2026-09-19 (Rest Day)
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 19),
                defaults={'modality': 'OTHER', 'duration_minutes': 30, 'intensity': 'Zone 2',
                          'target_zone': 'Brisk Walk / Outdoor (7,000 steps)', 'completed': True}
            )

            # Day 7: 2026-09-20 (Rest Day)
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 20),
                defaults={'modality': 'OTHER', 'duration_minutes': 30, 'intensity': 'Zone 2',
                          'target_zone': 'Brisk Walk / Outdoor (7,500 steps)', 'completed': True}
            )

            # Day 8: 2026-09-21 (Push)
            log_session(8, date(2026, 9, 21), day1, 'Day 8: Push (Chest, Triceps & Abs)',
                "Day 8: 78.24 kg. Push workout & 21m cardio completed. +5kg Bench PR (55kg).", 8.5, 80, [
                    (E['pushups'], 50, [(N, 0, 15), (N, 0, 12), (N, 0, 10)]),
                    (E['bench_press'], 150, [(N, 55, 10), (N, 55, 10), (N, 55, 8)]),
                    (E['incline_db_bench'], 105, [(N, 15, 12), (N, 17.5, 10), (N, 20, 8)]),
                    (E['low_to_high_db_fly'], 60, [(N, 5.0, 12), (N, 7.5, 12), (N, 7.5, 12)]),
                    (E['v_grip_pushdown'], 60, [(N, 35, 12), (N, 35, 12), (N, 35, 12)]),
                    (E['overhead_tricep_ext'], 60, [(N, 15, 12), (N, 15, 12), (N, 15, 12)]),
                    (E['hanging_leg_raise'], 50, [(N, 0, 15), (N, 0, 12), (N, 0, 12)]),
                ])
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 21),
                defaults={'modality': 'CYCLING', 'duration_minutes': 21, 'intensity': 'Zone 2',
                          'target_zone': '9m Bike + 12m Incline Treadmill', 'completed': True}
            )

            # Day 9: 2026-09-22 (Pull)
            log_session(9, date(2026, 9, 22), day2, 'Day 9: Pull (Back, Biceps & Rear Delts)',
                'Day 9 weigh-in: 78.04 kg. Completed Pull session & 21 min cardio. Overload on Lat Pulldown (+5kg) and Curls (+2.5kg).', 8.5, 82, [
                    (E['deadlift'], 150, [(N, 60, 8), (N, 60, 8), (N, 60, 8)]),
                    (E['lat_pulldown_wide'], 90, [(N, 40, 15), (N, 40, 12), (N, 40, 12)]),
                    (E['up_down_row'], 75, [(N, 17.5, 12), (N, 17.5, 12), (N, 17.5, 12)]),
                    (E['incline_db_curl'], 60, [(N, 5.0, 15), (N, 7.5, 12), (N, 7.5, 10)]),
                    (E['hammer_curl'], 60, [(N, 10.0, 12), (N, 12.5, 10), (N, 12.5, 10)]),
                ])
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 22),
                defaults={'modality': 'TREADMILL', 'duration_minutes': 21, 'intensity': 'Zone 2',
                          'target_zone': '9m Treadmill + 12m Cross Trainer', 'completed': True}
            )

            # Day 10: 2026-09-23 (Legs - from New start (3).xlsx)
            log_session(10, date(2026, 9, 23), day3, 'Day 10: Legs (Quads, Hamstrings & Calves)',
                'Day 10: 78.02 kg. Legs session: Leg press pyramided to 70kg (+20kg overload vs Day 3), Leg ext 35kg (+5kg), and 20m cardio.', 8.5, 78, [
                    (E['bodyweight_squat'], 60, [(N, 0, 12), (N, 0, 12), (N, 0, 12)]),
                    (E['leg_press_squat'], 150, [(N, 40, 12), (N, 50, 12), (N, 70, 12)]),
                    (E['leg_curl'], 68, [(N, 20, 12), (N, 25, 12), (N, 25, 12)]),
                    (E['leg_extension'], 68, [(N, 35, 12), (N, 35, 12), (N, 35, 12)]),
                    (E['db_rdl'], 90, [(N, 15, 12), (N, 15, 12), (N, 15, 12)]),
                    (E['calf_raise'], 60, [(N, 0, 15), (N, 0, 15), (N, 0, 15)]),
                    (E['hanging_leg_raise'], 50, [(N, 0, 12), (N, 0, 12), (N, 0, 12)]),
                    (E['kb_side_bend'], 50, [(N, 7.5, 12), (N, 7.5, 12), (N, 7.5, 12)]),
                ])
            CardioEntry.objects.update_or_create(
                user=user, date=date(2026, 9, 23),
                defaults={'modality': 'CYCLING', 'duration_minutes': 20, 'intensity': 'Zone 2',
                          'target_zone': '10m Treadmill + 10m Cycling (res 6)', 'completed': True}
            )

            # Mark rest days 6, 7, 11 as completed in program
            ProgramDay.objects.filter(program=program, day_number__in=[6, 7, 11]).update(status='COMPLETED')

            # 5. Nutrition targets & logs
            MacroTarget.objects.update_or_create(user=user, defaults=DIET_PLAN_OPTION_A_TARGETS)

            nutrition_log = [
                # date, calories, protein, carbs, fat, water_ml
                (date(2026, 9, 14), 1850, 69, 230, 48, 2500),
                (date(2026, 9, 15), 2250, 93, 275, 62, 3500),
                (date(2026, 9, 16), 1935, 95, 240, 52, 3500),
                (date(2026, 9, 17), 2220, 120, 260, 58, 3500),
                (date(2026, 9, 18), 1917, 124, 235, 49, 3500),
                (date(2026, 9, 19), 1934, 128, 240, 50, 3000),
                (date(2026, 9, 20), 3195, 126, 380, 85, 3500),
                (date(2026, 9, 21), 1984, 110, 245, 52, 3500),
                (date(2026, 9, 22), 2250, 112, 270, 60, 3500),
                (date(2026, 9, 23), 1700, 108, 210, 44, 3500),
                (date(2026, 9, 24), 1834, 86, 225, 48, 3500),
            ]
            for d, cal, prot, carb, fat, water in nutrition_log:
                nd, _ = NutritionDay.objects.get_or_create(user=user, date=d, defaults={'water_consumed_ml': water})
                nd.water_consumed_ml = water
                nd.save()
                if not nd.meals.exists():
                    MealEntry.objects.create(
                        nutrition_day=nd, meal_type='DINNER',
                        name='Day’s Logged Intake (Option A protocol, 2,160 kcal template)',
                        calories=cal, protein_g=prot, carbs_g=carb, fat_g=fat,
                    )

            # 6. Progress tracker: weight & measurements (Days 1–12)
            weights_data = [
                (date(2026, 9, 14), 77.76),
                (date(2026, 9, 15), 77.84),
                (date(2026, 9, 16), 78.26),
                (date(2026, 9, 17), 78.60),
                (date(2026, 9, 18), 77.84),
                (date(2026, 9, 21), 78.24),
                (date(2026, 9, 22), 78.04),
                (date(2026, 9, 23), 78.02),
                (date(2026, 9, 24), 78.02),
                (date(2026, 9, 25), 78.02),
            ]
            for d, weight in weights_data:
                w_entry, _ = WeightEntry.objects.get_or_create(user=user, date=d, defaults={'weight_kg': weight})
                w_entry.weight_kg = weight
                w_entry.save()

            measurements_data = [
                # date, waist, chest, arm, neck, shoulders, hips, thighs, calves
                (date(2026, 9, 14), 93.0, 101.0, 31.0, 38.0, 118.0, 99.0, 57.0, 37.0),
                (date(2026, 9, 15), 92.5, 101.4, 31.2, 38.0, 118.2, 98.8, 57.1, 37.0),
                (date(2026, 9, 16), 92.0, 102.0, 31.5, 38.0, 118.8, 98.5, 57.4, 37.2),
                (date(2026, 9, 17), 91.0, 101.5, 32.0, 38.0, 119.5, 98.2, 57.8, 37.5),
                (date(2026, 9, 18), 91.0, 101.5, 32.0, 36.0, 119.5, 98.0, 57.8, 37.5),
                (date(2026, 9, 19), 91.0, 101.5, 32.5, 36.0, 119.5, 98.0, 57.8, 37.5),
                (date(2026, 9, 21), 90.5, 102.0, 32.5, 36.0, 120.0, 98.0, 58.0, 37.5),
                (date(2026, 9, 22), 90.5, 102.0, 32.5, 36.0, 120.0, 98.0, 58.0, 37.5),
                (date(2026, 9, 23), 90.5, 102.0, 32.7, 36.0, 120.0, 98.0, 58.0, 37.5),
                (date(2026, 9, 24), 90.5, 102.0, 33.0, 36.0, 120.0, 98.0, 58.0, 37.5),
                (date(2026, 9, 25), 90.5, 102.0, 33.0, 36.0, 120.0, 98.0, 58.0, 37.5),
            ]
            for d, waist, chest, arm, neck, shld, hips, thg, calf in measurements_data:
                m, _ = BodyMeasurement.objects.get_or_create(
                    user=user, date=d,
                    defaults={
                        'waist_cm': waist, 'chest_cm': chest, 'arms_cm': arm, 'neck_cm': neck,
                        'shoulders_cm': shld, 'hips_cm': hips, 'thighs_cm': thg, 'calves_cm': calf,
                        'biceps_left_cm': round(arm - 0.1, 1), 'biceps_right_cm': arm,
                        'thigh_left_cm': thg, 'thigh_right_cm': round(thg + 0.2, 1),
                        'calf_left_cm': calf, 'calf_right_cm': calf,
                    }
                )
                m.waist_cm = waist
                m.chest_cm = chest
                m.arms_cm = arm
                m.neck_cm = neck
                m.shoulders_cm = shld
                m.hips_cm = hips
                m.thighs_cm = thg
                m.calves_cm = calf
                m.biceps_left_cm = round(arm - 0.1, 1)
                m.biceps_right_cm = arm
                m.thigh_left_cm = thg
                m.thigh_right_cm = round(thg + 0.2, 1)
                m.calf_left_cm = calf
                m.calf_right_cm = calf
                m.save()

            # 7. Daily Log: Steps, Sleep & Recovery Notes
            daily_entries = [
                # date, steps, sleep_hours, sleep_quality, energy_level, recovery_notes
                (date(2026, 9, 14), 8500, 8.0, 4, 2, 'Day 1 baseline: 77.76 kg. Push workout & 16.5m cardio done.'),
                (date(2026, 9, 15), 6500, 8.0, 4, 4, 'Day 2: 77.84 kg. Back session & 22m cardio (12m bike + 10m incline treadmill).'),
                (date(2026, 9, 16), 6500, 8.0, 4, 4, 'Day 3: 78.26 kg. Quads/hams/calves & 18m cross trainer + bike.'),
                (date(2026, 9, 17), 5000, 8.0, 4, 4, 'Day 4: 78.60 kg. Shoulders/arms & 21m incline treadmill done.'),
                (date(2026, 9, 18), 5500, 8.0, 4, 4, 'Day 5: 77.84 kg. Upper/Legs session & 23m cardio (9m incline treadmill + 14m cross trainer) completed.'),
                (date(2026, 9, 19), 7000, 7.0, 5, 5, 'Day 6: Rest day. Brisk outdoor walk; 7,000 steps achieved.'),
                (date(2026, 9, 20), 7500, 7.0, 4, 5, 'Week 1 review milestone'),
                (date(2026, 9, 21), 6500, 8.0, 4, 2, "Day 8: 78.24 kg. Push workout & 21m cardio completed. Body sore from Sunday's cricket session."),
                (date(2026, 9, 22), 6000, 8.0, 4, 3, 'Day 9: 78.04 kg. Completed Pull workout and 21m cardio.'),
                (date(2026, 9, 23), 6000, 8.0, 4, 4, 'Day 10: 78.02 kg. Legs session (Leg press to 70kg) & 20m cardio.'),
                (date(2026, 9, 24), 5500, 8.0, 4, 3, 'Day 11: 78.02 kg. Rest day & recovery.'),
                (date(2026, 9, 25), 6000, 8.0, 4, 4, 'Day 12: 78.02 kg. Arms measuring 33.0 cm (+2.0 cm net gain).'),
            ]
            for d, steps, sleep_h, sq, energy, notes in daily_entries:
                dl, _ = DailyLog.objects.get_or_create(
                    user=user, date=d,
                    defaults={
                        'steps': steps,
                        'sleep_hours': sleep_h,
                        'sleep_quality': sq,
                        'energy_level': energy,
                        'recovery_notes': notes,
                    }
                )
                dl.steps = steps
                dl.sleep_hours = sleep_h
                dl.sleep_quality = sq
                dl.energy_level = energy
                dl.recovery_notes = notes
                dl.save()

            self.stdout.write(self.style.SUCCESS(
                f"Successfully seeded {user.email}: "
                f"60-day RECOMP journey (Day {program.current_day}/60), "
                f"8 logged workouts, {len(weights_data)} weight entries, "
                f"{len(measurements_data)} body measurement checkpoints, "
                f"{len(nutrition_log)} nutrition days, {len(daily_entries)} daily logs, "
                f"and 10 cardio sessions from 'New start (3).xlsx'."
            ))
