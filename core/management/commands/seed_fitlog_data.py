import os
import uuid
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from users.models import User, UserProfile
from gyms.models import Gym, GymBranch, GymEquipment
from memberships.models import GymMembership, TrainerClientAssignment, GymInvitation
from exercises.models import MuscleGroup, EquipmentType, Exercise
from workouts.models import Routine, RoutineExercise, AssignedWorkout, WorkoutSession, WorkoutExercise, WorkoutSet, JourneyProgram, ProgramDay, CardioEntry
from nutrition.models import NutritionDay, MealEntry
from nutrition.targets import get_or_create_macro_target
from progress.models import WeightEntry, BodyMeasurement, PersonalRecord
from notifications.models import Notification
from core.models import AuditLog

class Command(BaseCommand):
    help = "Seeds comprehensive production-ready FitLog fitness data across all domains"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Starting FitLog database seeding...")

        demo_password = os.environ.get('FITLOG_DEMO_PASSWORD', 'fitlog123')

        # 1. Muscle Groups
        muscle_names = [
            ('Chest', 'chest'),
            ('Back', 'back'),
            ('Shoulders', 'shoulders'),
            ('Biceps', 'biceps'),
            ('Triceps', 'triceps'),
            ('Quadriceps', 'quadriceps'),
            ('Hamstrings', 'hamstrings'),
            ('Glutes', 'glutes'),
            ('Calves', 'calves'),
            ('Core', 'core'),
            ('Cardio', 'cardio')
        ]
        muscles = {}
        for name, slug in muscle_names:
            m, _ = MuscleGroup.objects.get_or_create(name=name, slug=slug)
            muscles[slug] = m

        # 2. Equipment Types
        equipment_names = [
            ('Barbell', 'barbell'),
            ('Dumbbell', 'dumbbell'),
            ('Cable', 'cable'),
            ('Machine', 'machine'),
            ('Bodyweight', 'bodyweight'),
            ('Kettlebell', 'kettlebell'),
            ('Cardio Equipment', 'cardio-equipment')
        ]
        equipments = {}
        for name, slug in equipment_names:
            eq, _ = EquipmentType.objects.get_or_create(name=name, slug=slug)
            equipments[slug] = eq

        # 3. Standard Global Exercises (50+)
        raw_exercises = [
            # Chest
            ("Barbell Bench Press", "barbell-bench-press", "chest", "barbell", "Lie on flat bench, lower bar with control to mid-chest, press upwards driving through heels."),
            ("Incline Dumbbell Press", "incline-dumbbell-press", "chest", "dumbbell", "Set incline to 30 degrees. Press dumbbells up over clavicles, keeping shoulder blades retracted."),
            ("Decline Barbell Press", "decline-barbell-press", "chest", "barbell", "Focus on lower pectoral fibers with safe grip on decline bench."),
            ("Cable Chest Fly", "cable-chest-fly", "chest", "cable", "Set pulleys at chest height. Squeeze pecs together with slight bend in elbows."),
            ("Dips (Chest Focus)", "chest-dips", "chest", "bodyweight", "Lean torso forward 30 degrees, flare elbows slightly to emphasize pectoral load."),
            ("Push-ups", "push-ups", "chest", "bodyweight", "Strict core plank, lower until chest touches ground, lock out pecs."),

            # Back
            ("Conventional Barbell Deadlift", "barbell-deadlift", "back", "barbell", "Hinge at hips, brace core, pull bar close to shins with neutral spine."),
            ("Barbell Bent-Over Row", "barbell-bent-over-row", "back", "barbell", "Hinge to 45 degrees, pull barbell to lower ribcage engaging lats."),
            ("Pull-ups", "pull-ups", "back", "bodyweight", "Pronated grip wider than shoulders, pull chest to bar, control descent."),
            ("Chin-ups", "chin-ups", "back", "bodyweight", "Supinated shoulder-width grip, driving elbows down and back."),
            ("Lat Pulldown", "lat-pulldown", "back", "cable", "Pull bar down towards upper chest while leaning slightly back."),
            ("Seated Cable Row", "seated-cable-row", "back", "cable", "Neutral spine, drive elbows back towards torso, squeezing scapulae."),
            ("Single-Arm Dumbbell Row", "single-arm-dumbbell-row", "back", "dumbbell", "Support on flat bench, row dumbbell into hip pocket with full stretch."),
            ("T-Bar Row", "t-bar-row", "back", "machine", "Chest-supported or platform row targeting mid-back thickness."),

            # Legs (Quads / Hams / Glutes / Calves)
            ("Barbell Back Squat", "barbell-back-squat", "quadriceps", "barbell", "Bar across traps, break at knees and hips simultaneously, hit parallel depth."),
            ("Barbell Front Squat", "barbell-front-squat", "quadriceps", "barbell", "Clean rack position with high elbows, vertical torso depth."),
            ("Leg Press", "leg-press", "quadriceps", "machine", "Feet shoulder-width on carriage, lower until knees form 90 degree angle."),
            ("Leg Extension", "leg-extension", "quadriceps", "machine", "Isolate quadriceps, pause for 1 second at full contraction."),
            ("Romanian Deadlift (RDL)", "romanian-deadlift", "hamstrings", "barbell", "Keep knees soft, push hips backward until deep hamstring stretch is felt."),
            ("Lying Leg Curl", "lying-leg-curl", "hamstrings", "machine", "Dorsiflex ankles, curl pad towards glutes, control negative."),
            ("Seated Leg Curl", "seated-leg-curl", "hamstrings", "machine", "Isolate knee flexion in seated position with thigh pad pinned."),
            ("Barbell Hip Thrust", "barbell-hip-thrust", "glutes", "barbell", "Upper back against bench, drive through heels to complete hip extension."),
            ("Walking Dumbbell Lunges", "walking-dumbbell-lunges", "glutes", "dumbbell", "Step forward into 90-degree lunges, torso upright."),
            ("Standing Calf Raise", "standing-calf-raise", "calves", "machine", "Full ankle extension at top, slow 3-second stretch at bottom."),
            ("Seated Calf Raise", "seated-calf-raise", "calves", "machine", "Targets soleus muscle with knees bent 90 degrees."),

            # Shoulders
            ("Overhead Barbell Press", "overhead-barbell-press", "shoulders", "barbell", "Press overhead from collarbone to lockout with engaged core and glutes."),
            ("Seated Dumbbell Shoulder Press", "seated-dumbbell-shoulder-press", "shoulders", "dumbbell", "Press dumbbells vertically overhead on high-incline bench."),
            ("Dumbbell Lateral Raise", "dumbbell-lateral-raise", "shoulders", "dumbbell", "Slight forward lean, raise arms in scapular plane to shoulder height."),
            ("Cable Lateral Raise", "cable-lateral-raise", "shoulders", "cable", "Constant tension throughout shoulder abduction movement."),
            ("Cable Face Pull", "cable-face-pull", "shoulders", "cable", "Pull rope towards bridge of nose, externally rotating forearms."),
            ("Dumbbell Rear Delt Fly", "dumbbell-rear-delt-fly", "shoulders", "dumbbell", "Hinged over, sweep arms wide focusing on posterior deltoids."),

            # Arms (Biceps & Triceps)
            ("Barbell Bicep Curl", "barbell-bicep-curl", "biceps", "barbell", "Supinated shoulder-width grip, curl bar without swinging torso."),
            ("Incline Dumbbell Curl", "incline-dumbbell-curl", "biceps", "dumbbell", "45-degree bench, deep stretch on long head of biceps at bottom."),
            ("Hammer Curl", "hammer-curl", "biceps", "dumbbell", "Neutral palm grip, targeting brachialis and forearm flexors."),
            ("Preacher Curl", "preacher-curl", "biceps", "machine", "Arm locked on preacher pad, preventing momentum for pure peak tension."),
            ("Tricep Rope Pushdown", "tricep-rope-pushdown", "triceps", "cable", "Pin elbows to ribs, extend downwards and spread rope ends apart."),
            ("Skull Crushers (EZ-Bar)", "skull-crushers", "triceps", "barbell", "Lower EZ-bar to forehead or behind head for long head triceps stretch."),
            ("Overhead Cable Tricep Extension", "overhead-cable-tricep-extension", "triceps", "cable", "Face away from cable tower, press forward with elbows fixed."),
            ("Close-Grip Bench Press", "close-grip-bench-press", "triceps", "barbell", "Hands spaced 14 inches apart, lower bar to sternum focusing on triceps."),

            # Core
            ("Hanging Leg Raise", "hanging-leg-raise", "core", "bodyweight", "Hang from pull-up bar, raise straight legs to 90 degrees using lower abs."),
            ("Ab Wheel Rollout", "ab-wheel-rollout", "core", "bodyweight", "Kneeling rollout extending arms and hips, pull back using rectus abdominis."),
            ("Cable Woodchoppers", "cable-woodchoppers", "core", "cable", "Diagonal rotational pull across body for internal and external obliques."),
            ("Plank", "plank", "core", "bodyweight", "Forearms and toes, maintain straight rigid body line for duration."),

            # Cardio
            ("Treadmill Running", "treadmill-running", "cardio", "cardio-equipment", "Aerobic or interval cardio pacing on motorized treadmill."),
            ("Rowing Machine Ergometer", "rowing-machine", "cardio", "cardio-equipment", "Full-body power stroke driving with legs, then hips, then arms."),
            ("Assault Air Bike", "assault-air-bike", "cardio", "cardio-equipment", "Max effort high-intensity interval conditioning with fan resistance."),
            ("Stairmaster", "stairmaster", "cardio", "cardio-equipment", "Continuous stair climbing for low-impact conditioning and glute endurance.")
        ]

        for name, slug, m_slug, eq_slug, instr in raw_exercises:
            Exercise.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'primary_muscle': muscles[m_slug],
                    'equipment': equipments[eq_slug],
                    'instructions': instr,
                    'gym': None  # Global standard
                }
            )

        self.stdout.write(f"Created/Verified {len(raw_exercises)} standard global exercises.")

        # 4. Gym: Apex Performance Club
        gym, _ = Gym.objects.get_or_create(
            slug="apex-performance-club",
            defaults={
                'name': "Apex Performance Club",
                'description': "Elite strength and athletic conditioning training facility.",
                'address': "450 Olympic Boulevard",
                'city': "San Francisco, CA",
                'phone': "(415) 555-0199",
                'email': "contact@apexfit.com",
            }
        )

        GymBranch.objects.get_or_create(
            gym=gym,
            name="Downtown Flagship",
            defaults={'address': "450 Olympic Blvd", 'phone': "(415) 555-0199"}
        )
        GymBranch.objects.get_or_create(
            gym=gym,
            name="Uptown Training Ground",
            defaults={'address': "1200 Pacific Ave", 'phone': "(415) 555-0244"}
        )

        GymEquipment.objects.get_or_create(gym=gym, name="Eleiko Olympic Power Racks", defaults={'category': 'BARBELL', 'quantity': 8})
        GymEquipment.objects.get_or_create(gym=gym, name="Custom Rogue Dumbbells (5-150 lbs)", defaults={'category': 'DUMBBELL', 'quantity': 3})
        GymEquipment.objects.get_or_create(gym=gym, name="Prime Fitness Dual Cable Stacks", defaults={'category': 'CABLE', 'quantity': 4})
        GymEquipment.objects.get_or_create(gym=gym, name="Concept2 Rowers & SkiErgs", defaults={'category': 'CARDIO', 'quantity': 6})

        # 5. Seed Real Authenticated Personas
        # Persona 1: Gym Owner
        owner_user, _ = User.objects.get_or_create(
            email="owner@apexfit.com",
            defaults={
                'username': "david_vance",
                'first_name': "David",
                'last_name': "Vance",
            }
        )
        owner_user.set_password(demo_password)
        owner_user.save()
        UserProfile.objects.get_or_create(user=owner_user, defaults={'fitness_goal': 'STRENGTH', 'weight_kg': 85.0, 'height_cm': 183.0})

        # Persona 2: Trainer / Coach
        trainer_user, _ = User.objects.get_or_create(
            email="coach.marcus@apexfit.com",
            defaults={
                'username': "coach_marcus",
                'first_name': "Marcus",
                'last_name': "Rivera",
            }
        )
        trainer_user.set_password(demo_password)
        trainer_user.save()
        UserProfile.objects.get_or_create(user=trainer_user, defaults={'fitness_goal': 'HYPERTROPHY', 'weight_kg': 90.0, 'height_cm': 188.0, 'bio': 'CSCS Certified Strength & Hypertrophy Coach with 10+ years experience.'})

        # Persona 3: Gym Member
        member_user, _ = User.objects.get_or_create(
            email="alex.member@example.com",
            defaults={
                'username': "alex_chen",
                'first_name': "Alex",
                'last_name': "Chen",
            }
        )
        member_user.set_password(demo_password)
        member_user.save()
        UserProfile.objects.get_or_create(user=member_user, defaults={'fitness_goal': 'HYPERTROPHY', 'weight_kg': 80.2, 'height_cm': 178.0, 'bio': 'Passionate lifter focused on progressive overload and aesthetic symmetry.'})

        # 6. Gym Memberships
        owner_membership, _ = GymMembership.objects.get_or_create(
            user=owner_user,
            gym=gym,
            defaults={'role': 'OWNER', 'status': 'ACTIVE'}
        )
        trainer_membership, _ = GymMembership.objects.get_or_create(
            user=trainer_user,
            gym=gym,
            defaults={'role': 'TRAINER', 'status': 'ACTIVE'}
        )
        member_membership, _ = GymMembership.objects.get_or_create(
            user=member_user,
            gym=gym,
            defaults={
                'role': 'MEMBER',
                'status': 'ACTIVE',
                'share_workouts_with_trainers': True,
                'share_progress_with_trainers': True,
                'share_nutrition_with_trainers': True
            }
        )

        # 7. Trainer-Client Assignment
        assignment, _ = TrainerClientAssignment.objects.get_or_create(
            trainer_membership=trainer_membership,
            client_membership=member_membership,
            defaults={'is_active': True, 'notes': 'Hypertrophy specialization cycle targeting upper body volume.'}
        )

        # 8. Pending Invitation (Demonstrating onboarding flow)
        GymInvitation.objects.get_or_create(
            gym=gym,
            email="sarah.athlete@example.com",
            defaults={
                'role': 'MEMBER',
                'invited_by': owner_user,
                'status': 'PENDING',
                'expires_at': timezone.now() + timedelta(days=7)
            }
        )

        # 9. Routines
        # Gym Template: Apex Push Hypertrophy
        routine_push, _ = Routine.objects.get_or_create(
            name="Apex PPL - Push Hypertrophy",
            gym=gym,
            defaults={
                'description': "High-intensity hypertrophy session targeting chest, anterior delts, and lateral triceps heads.",
                'created_by': trainer_user,
                'last_modified_by': trainer_user
            }
        )
        bench_ex = Exercise.objects.get(slug="barbell-bench-press")
        incline_ex = Exercise.objects.get(slug="incline-dumbbell-press")
        lat_raise_ex = Exercise.objects.get(slug="dumbbell-lateral-raise")
        tricep_ex = Exercise.objects.get(slug="tricep-rope-pushdown")

        RoutineExercise.objects.get_or_create(routine=routine_push, exercise=bench_ex, defaults={'order': 1, 'target_sets': 4, 'target_reps': '6-8', 'rest_seconds': 120})
        RoutineExercise.objects.get_or_create(routine=routine_push, exercise=incline_ex, defaults={'order': 2, 'target_sets': 3, 'target_reps': '8-10', 'rest_seconds': 90})
        RoutineExercise.objects.get_or_create(routine=routine_push, exercise=lat_raise_ex, defaults={'order': 3, 'target_sets': 4, 'target_reps': '12-15', 'rest_seconds': 60})
        RoutineExercise.objects.get_or_create(routine=routine_push, exercise=tricep_ex, defaults={'order': 4, 'target_sets': 3, 'target_reps': '10-12', 'rest_seconds': 60})

        # Gym Template: Apex Pull Strength
        routine_pull, _ = Routine.objects.get_or_create(
            name="Apex PPL - Pull Strength",
            gym=gym,
            defaults={
                'description': "Heavy lat and posterior chain development workout.",
                'created_by': trainer_user,
                'last_modified_by': trainer_user
            }
        )
        deadlift_ex = Exercise.objects.get(slug="barbell-deadlift")
        pullup_ex = Exercise.objects.get(slug="pull-ups")
        cable_row_ex = Exercise.objects.get(slug="seated-cable-row")
        bicep_ex = Exercise.objects.get(slug="barbell-bicep-curl")

        RoutineExercise.objects.get_or_create(routine=routine_pull, exercise=deadlift_ex, defaults={'order': 1, 'target_sets': 3, 'target_reps': '5', 'rest_seconds': 180})
        RoutineExercise.objects.get_or_create(routine=routine_pull, exercise=pullup_ex, defaults={'order': 2, 'target_sets': 3, 'target_reps': '8-10', 'rest_seconds': 90})
        RoutineExercise.objects.get_or_create(routine=routine_pull, exercise=cable_row_ex, defaults={'order': 3, 'target_sets': 3, 'target_reps': '10-12', 'rest_seconds': 90})
        RoutineExercise.objects.get_or_create(routine=routine_pull, exercise=bicep_ex, defaults={'order': 4, 'target_sets': 3, 'target_reps': '10-12', 'rest_seconds': 60})

        # Workbook-oriented schedule: five core sessions plus optional Day 6.
        # The same weekly structure is expanded to program days below, rather
        # than manufacturing a separate static UI dataset.
        routine_legs, _ = Routine.objects.get_or_create(name='60-Day Journey - Legs', user=member_user, defaults={'description': 'Day 3: heavy legs, hamstrings, calves and core.', 'created_by': trainer_user, 'last_modified_by': trainer_user})
        squat_ex = Exercise.objects.get(slug="barbell-back-squat")
        rdl_ex = Exercise.objects.get(slug="romanian-deadlift")
        RoutineExercise.objects.get_or_create(routine=routine_legs, exercise=squat_ex, defaults={'order': 1, 'target_sets': 3, 'target_reps': '4-6', 'rest_seconds': 150, 'target_rpe': 8.5, 'suggested_weight_kg': 140, 'focus': 'Quads anchor', 'notes': 'Full depth and knee tracking.'})
        RoutineExercise.objects.get_or_create(routine=routine_legs, exercise=rdl_ex, defaults={'order': 2, 'target_sets': 3, 'target_reps': '8-10', 'rest_seconds': 90, 'target_rpe': 8, 'focus': 'Hamstrings', 'notes': 'Push hips back; control the eccentric.'})
        routine_shoulders, _ = Routine.objects.get_or_create(name='60-Day Journey - Shoulders & Arms', user=member_user, defaults={'description': 'Day 4: shoulder anchor, arms and core.', 'created_by': trainer_user, 'last_modified_by': trainer_user})
        RoutineExercise.objects.get_or_create(routine=routine_shoulders, exercise=lat_raise_ex, defaults={'order': 1, 'target_sets': 4, 'target_reps': '12-15', 'rest_seconds': 60, 'target_rpe': 8, 'suggested_weight_kg': 7.5, 'focus': 'Shoulders', 'notes': 'Strict lateral-delt tension.'})
        RoutineExercise.objects.get_or_create(routine=routine_shoulders, exercise=tricep_ex, defaults={'order': 2, 'target_sets': 3, 'target_reps': '10-12', 'rest_seconds': 60, 'target_rpe': 8, 'focus': 'Triceps', 'notes': 'Control the long-head stretch.'})
        routine_upper, _ = Routine.objects.get_or_create(name='60-Day Journey - Upper', user=member_user, defaults={'description': 'Day 5: upper-body hypertrophy and conditioning.', 'created_by': trainer_user, 'last_modified_by': trainer_user})
        RoutineExercise.objects.get_or_create(routine=routine_upper, exercise=incline_ex, defaults={'order': 1, 'target_sets': 3, 'target_reps': '6-8', 'rest_seconds': 120, 'target_rpe': 8.5, 'suggested_weight_kg': 24, 'focus': 'Upper anchor', 'notes': '30-degree incline press.'})
        RoutineExercise.objects.get_or_create(routine=routine_upper, exercise=cable_row_ex, defaults={'order': 2, 'target_sets': 3, 'target_reps': '10-12', 'rest_seconds': 75, 'target_rpe': 8, 'focus': 'Upper back', 'notes': 'Scapular control, no lower-back swing.'})

        program, _ = JourneyProgram.objects.get_or_create(
            user=member_user,
            active=True,
            defaults={
                'name': '60-Day Fitness Journey',
                'duration_days': 60,
                'start_date': date.today() - timedelta(days=4),
                'current_day': 5
            }
        )
        weekly_cycle = [(routine_push, 'Day 1 · Push', False), (routine_pull, 'Day 2 · Pull', False), (routine_legs, 'Day 3 · Legs', False), (routine_shoulders, 'Day 4 · Shoulders / Arms', False), (routine_upper, 'Day 5 · Upper / Conditioning', False), (routine_upper, 'Day 6 · Optional Full Body', True)]
        for number in range(1, 61):
            routine, label, optional = weekly_cycle[(number - 1) % len(weekly_cycle)]
            ProgramDay.objects.get_or_create(program=program, day_number=number, defaults={'routine': routine, 'label': label, 'is_optional': optional})

        # Personal Member Routine: Alex's Leg Day Special
        Routine.objects.get_or_create(
            name="Alex's Sunday Quad Blast",
            user=member_user,
            defaults={
                'description': "Personal weekend volume workout.",
                'created_by': member_user,
                'last_modified_by': member_user
            }
        )

        # 10. Assigned Workouts
        # Past completed workout with coach feedback
        past_assigned, _ = AssignedWorkout.objects.get_or_create(
            gym=gym,
            trainer=trainer_user,
            client=member_user,
            routine=routine_pull,
            scheduled_date=date.today() - timedelta(days=2),
            defaults={
                'status': 'COMPLETED',
                'trainer_feedback': "Solid deadlift speed Alex! Let's bump the working weight by 2.5kg next pull day.",
                'feedback_date': timezone.now() - timedelta(days=1)
            }
        )

        # Today's pending assigned workout
        AssignedWorkout.objects.get_or_create(
            gym=gym,
            trainer=trainer_user,
            client=member_user,
            routine=routine_push,
            scheduled_date=date.today(),
            defaults={'status': 'PENDING'}
        )

        # 11. Past Workout Sessions for Alex (Personal Data)
        session1 = WorkoutSession.objects.filter(
            user=member_user,
            assigned_workout=past_assigned
        ).first()
        if not session1:
            session1 = WorkoutSession.objects.create(
                user=member_user,
                assigned_workout=past_assigned,
                title="Apex PPL - Pull Strength",
                gym=gym,
                routine=routine_pull,
                started_at=timezone.now() - timedelta(days=2, hours=3),
                completed_at=timezone.now() - timedelta(days=2, hours=2),
                duration_seconds=3480,
                overall_rpe=8,
                notes='Felt energetic. Hit strong deadlifts with clean lockouts.'
            )
        # Session 1 exercises and sets
        we1, _ = WorkoutExercise.objects.get_or_create(session=session1, exercise=deadlift_ex, defaults={'order': 1, 'rest_seconds': 180})
        WorkoutSet.objects.get_or_create(workout_exercise=we1, set_number=1, defaults={'set_type': 'WARMUP', 'weight_kg': 100.0, 'reps': 5, 'completed': True})
        WorkoutSet.objects.get_or_create(workout_exercise=we1, set_number=2, defaults={'set_type': 'NORMAL', 'weight_kg': 140.0, 'reps': 5, 'completed': True})
        WorkoutSet.objects.get_or_create(workout_exercise=we1, set_number=3, defaults={'set_type': 'NORMAL', 'weight_kg': 160.0, 'reps': 5, 'completed': True})

        we2, _ = WorkoutExercise.objects.get_or_create(session=session1, exercise=pullup_ex, defaults={'order': 2, 'rest_seconds': 90})
        WorkoutSet.objects.get_or_create(workout_exercise=we2, set_number=1, defaults={'set_type': 'NORMAL', 'weight_kg': 0.0, 'reps': 10, 'completed': True})
        WorkoutSet.objects.get_or_create(workout_exercise=we2, set_number=2, defaults={'set_type': 'NORMAL', 'weight_kg': 0.0, 'reps': 9, 'completed': True})
        WorkoutSet.objects.get_or_create(workout_exercise=we2, set_number=3, defaults={'set_type': 'NORMAL', 'weight_kg': 0.0, 'reps': 8, 'completed': True})

        we3, _ = WorkoutExercise.objects.get_or_create(session=session1, exercise=bicep_ex, defaults={'order': 3, 'rest_seconds': 60})
        WorkoutSet.objects.get_or_create(workout_exercise=we3, set_number=1, defaults={'set_type': 'NORMAL', 'weight_kg': 35.0, 'reps': 12, 'completed': True})
        WorkoutSet.objects.get_or_create(workout_exercise=we3, set_number=2, defaults={'set_type': 'NORMAL', 'weight_kg': 35.0, 'reps': 10, 'completed': True})

        # Session 2: Leg Day 4 days ago
        session2 = WorkoutSession.objects.filter(
            user=member_user,
            title="Heavy Squat & Hamstring Session"
        ).first()
        if not session2:
            session2 = WorkoutSession.objects.create(
                user=member_user,
                title="Heavy Squat & Hamstring Session",
                gym=gym,
                started_at=timezone.now() - timedelta(days=4, hours=4),
                completed_at=timezone.now() - timedelta(days=4, hours=3),
                duration_seconds=3900,
                overall_rpe=9,
                notes='Squats felt deep and crisp.'
            )
        we_sq, _ = WorkoutExercise.objects.get_or_create(session=session2, exercise=squat_ex, defaults={'order': 1, 'rest_seconds': 180})
        WorkoutSet.objects.get_or_create(workout_exercise=we_sq, set_number=1, defaults={'set_type': 'NORMAL', 'weight_kg': 120.0, 'reps': 6, 'completed': True})
        WorkoutSet.objects.get_or_create(workout_exercise=we_sq, set_number=2, defaults={'set_type': 'NORMAL', 'weight_kg': 130.0, 'reps': 5, 'completed': True})
        WorkoutSet.objects.get_or_create(workout_exercise=we_sq, set_number=3, defaults={'set_type': 'NORMAL', 'weight_kg': 135.0, 'reps': 4, 'completed': True})

        # 12. Nutrition
        get_or_create_macro_target(member_user)
        today_nutri, _ = NutritionDay.objects.get_or_create(
            user=member_user,
            date=date.today(),
            defaults={'water_consumed_ml': 2250}
        )
        MealEntry.objects.get_or_create(
            nutrition_day=today_nutri,
            name="Oatmeal, Blueberries & Whey Isolate",
            defaults={'meal_type': 'BREAKFAST', 'calories': 520, 'protein_g': 42.0, 'carbs_g': 68.0, 'fat_g': 9.0}
        )
        MealEntry.objects.get_or_create(
            nutrition_day=today_nutri,
            name="Grilled Chicken Breast, Jasmine Rice & Avocado",
            defaults={'meal_type': 'LUNCH', 'calories': 720, 'protein_g': 58.0, 'carbs_g': 78.0, 'fat_g': 16.0}
        )
        MealEntry.objects.get_or_create(
            nutrition_day=today_nutri,
            name="Greek Yogurt Bowl with Honey & Walnuts",
            defaults={'meal_type': 'SNACK', 'calories': 340, 'protein_g': 24.0, 'carbs_g': 28.0, 'fat_g': 14.0}
        )

        # 13. Progress (Weight & PRs)
        for i in range(14, 0, -1):
            d = date.today() - timedelta(days=i)
            # Gradual weight trend from 81.5 down to 80.2
            w = round(81.5 - (14 - i) * 0.09, 1)
            WeightEntry.objects.get_or_create(user=member_user, date=d, defaults={'weight_kg': w, 'body_fat_pct': 14.2})

        BodyMeasurement.objects.get_or_create(
            user=member_user,
            date=date.today() - timedelta(days=7),
            defaults={'chest_cm': 108.0, 'waist_cm': 82.5, 'arms_cm': 41.2, 'thighs_cm': 62.0}
        )
        CardioEntry.objects.get_or_create(user=member_user, date=date.today() - timedelta(days=2), modality='ELLIPTICAL', defaults={'duration_minutes': 30, 'intensity': 'Zone 2', 'target_zone': '125–135 bpm'})
        CardioEntry.objects.get_or_create(user=member_user, date=date.today() - timedelta(days=1), modality='TREADMILL', defaults={'duration_minutes': 35, 'intensity': 'Zone 2', 'target_zone': '125–135 bpm'})

        PersonalRecord.objects.get_or_create(
            user=member_user,
            exercise=deadlift_ex,
            defaults={'max_weight_kg': 160.0, 'reps': 5, 'estimated_one_rep_max': 186.7, 'achieved_at': date.today() - timedelta(days=2)}
        )
        PersonalRecord.objects.get_or_create(
            user=member_user,
            exercise=squat_ex,
            defaults={'max_weight_kg': 135.0, 'reps': 4, 'estimated_one_rep_max': 153.0, 'achieved_at': date.today() - timedelta(days=4)}
        )
        PersonalRecord.objects.get_or_create(
            user=member_user,
            exercise=bench_ex,
            defaults={'max_weight_kg': 105.0, 'reps': 5, 'estimated_one_rep_max': 122.5, 'achieved_at': date.today() - timedelta(days=6)}
        )

        # 14. Notifications & Audit Logs
        if not Notification.objects.filter(recipient=member_user, verb='WORKOUT_ASSIGNED').exists():
            Notification.objects.create(
                recipient=member_user,
                actor=trainer_user,
                gym=gym,
                verb='WORKOUT_ASSIGNED',
                message=f"Coach Marcus Rivera assigned: Apex PPL - Push Hypertrophy",
                is_read=False
            )
        if not Notification.objects.filter(recipient=member_user, verb='FEEDBACK_POSTED').exists():
            Notification.objects.create(
                recipient=member_user,
                actor=trainer_user,
                gym=gym,
                verb='FEEDBACK_POSTED',
                message=f"Coach Marcus Rivera left feedback on your Pull workout: 'Solid deadlift speed Alex!'",
                is_read=False
            )

        if not AuditLog.objects.filter(actor=owner_user, gym=gym, action='TRAINER_ASSIGNED').exists():
            AuditLog.objects.create(
                actor=owner_user,
                gym=gym,
                action='TRAINER_ASSIGNED',
                resource_type='TrainerClientAssignment',
                resource_id=str(assignment.id),
                details={'trainer': trainer_user.email, 'client': member_user.email}
            )

        self.stdout.write(self.style.SUCCESS("FitLog database successfully seeded with all domain models and personas!"))
        self.stdout.write(f"Personas configured with default demo credentials.")
        self.stdout.write(f"1. Gym Owner: owner@apexfit.com")
        self.stdout.write(f"2. Trainer: coach.marcus@apexfit.com")
        self.stdout.write(f"3. Member: alex.member@example.com")
