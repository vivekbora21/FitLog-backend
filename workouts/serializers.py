from rest_framework import serializers
from django.db import transaction
from datetime import timedelta
from django.utils import timezone
from .progression import progression_for
from .models import Routine, RoutineExercise, AssignedWorkout, WorkoutSession, WorkoutExercise, WorkoutSet, ProgramDay, CardioEntry, JourneyProgram, ProgramDayExerciseSwap
from exercises.models import Exercise
from exercises.serializers import ExerciseSerializer
from progress.models import PersonalRecord
from progress.records import recompute_personal_records
from core.models import AuditLog
from notifications.models import Notification

class WorkoutSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkoutSet
        fields = [
            'id', 'set_number', 'set_type', 'weight_kg', 'reps', 'rpe', 'rir', 'completed',
            'duration_seconds', 'distance_km', 'incline_percent', 'speed_kmh',
            'resistance_level', 'calories', 'heart_rate', 'intensity',
        ]

class WorkoutExerciseSerializer(serializers.ModelSerializer):
    sets = WorkoutSetSerializer(many=True)
    exercise_name = serializers.CharField(source='exercise.name', read_only=True)
    primary_muscle = serializers.CharField(source='exercise.primary_muscle.name', read_only=True)

    class Meta:
        model = WorkoutExercise
        fields = ['id', 'exercise', 'exercise_name', 'primary_muscle', 'order', 'rest_seconds', 'notes', 'sets']

class WorkoutSessionSerializer(serializers.ModelSerializer):
    exercises = WorkoutExerciseSerializer(many=True, required=False)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    gym_name = serializers.CharField(source='gym.name', read_only=True)
    total_volume_kg = serializers.FloatField(read_only=True)
    total_calories = serializers.IntegerField(read_only=True)
    new_prs = serializers.SerializerMethodField()

    class Meta:
        model = WorkoutSession
        fields = [
            'id', 'user', 'user_email', 'user_name', 'gym', 'gym_name', 'assigned_workout',
            'routine', 'title', 'started_at', 'completed_at', 'duration_seconds',
            'overall_rpe', 'notes', 'exercises', 'total_volume_kg', 'total_calories',
            'new_prs', 'created_at'
        ]
        read_only_fields = ['user', 'created_at']

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_new_prs(self, obj):
        return getattr(obj, '_new_prs', [])

    @staticmethod
    def _create_exercises(session, exercises_data, weight_kg, user, track_prs):
        """Creates WorkoutExercise/WorkoutSet rows in bulk (instead of one INSERT per row —
        a 15-exercise/60-set session used to cost 150+ queries), estimating calories
        up front since PKs are client-generated UUIDs and need no round trip to know.
        Returns (new_prs, cardio sets grouped for the cardio-entry sync)."""
        all_sets_data = []  # (sets_data, exercise) per exercise, in order
        workout_exercises = []
        for ex_data in exercises_data:
            sets_data = ex_data.pop('sets', [])
            workout_exercises.append(WorkoutExercise(session=session, **ex_data))
            all_sets_data.append((sets_data, ex_data['exercise']))
        WorkoutExercise.objects.bulk_create(workout_exercises)

        all_sets = []  # flat, for the single bulk_create call
        sets_by_exercise = []  # parallel to workout_exercises
        for workout_exercise, (sets_data, exercise) in zip(workout_exercises, all_sets_data):
            created_sets = []
            for s_data in sets_data:
                workout_set = WorkoutSet(workout_exercise=workout_exercise, **s_data)
                if workout_set.calories is None:
                    estimated = workout_set.estimate_calories(weight_kg)
                    if estimated is not None:
                        workout_set.calories = estimated
                all_sets.append(workout_set)
                created_sets.append(workout_set)
            sets_by_exercise.append(created_sets)
        if all_sets:
            WorkoutSet.objects.bulk_create(all_sets)

        new_prs = []
        cardio_candidates = []  # (exercise_name, primary_muscle_name, [WorkoutSet, ...])
        for workout_exercise, (sets_data, exercise), created_sets in zip(workout_exercises, all_sets_data, sets_by_exercise):
            for workout_set in created_sets:
                if track_prs and workout_set.completed and workout_set.weight_kg > 0 and workout_set.reps > 0:
                    est_1rm = PersonalRecord.calculate_epley_1rm(workout_set.weight_kg, workout_set.reps)

                    pr, created = PersonalRecord.objects.get_or_create(
                        user=user,
                        exercise=exercise,
                        defaults={
                            'max_weight_kg': workout_set.weight_kg,
                            'reps': workout_set.reps,
                            'estimated_one_rep_max': est_1rm,
                            'achieved_at': session.started_at.date()
                        }
                    )
                    if created:
                        new_prs.append({
                            'id': str(pr.id),
                            'exercise_name': exercise.name,
                            'primary_muscle': exercise.primary_muscle.name if exercise.primary_muscle else 'Compound',
                            'max_weight_kg': pr.max_weight_kg,
                            'reps': pr.reps,
                            'estimated_one_rep_max': pr.estimated_one_rep_max,
                            'achieved_at': str(session.started_at.date()),
                            'is_first': True,
                        })
                    elif est_1rm > pr.estimated_one_rep_max:
                        old_1rm = pr.estimated_one_rep_max
                        pr.max_weight_kg = workout_set.weight_kg
                        pr.reps = workout_set.reps
                        pr.estimated_one_rep_max = est_1rm
                        pr.achieved_at = session.started_at.date()
                        pr.save()
                        new_prs.append({
                            'id': str(pr.id),
                            'exercise_name': exercise.name,
                            'primary_muscle': exercise.primary_muscle.name if exercise.primary_muscle else 'Compound',
                            'max_weight_kg': pr.max_weight_kg,
                            'reps': pr.reps,
                            'estimated_one_rep_max': pr.estimated_one_rep_max,
                            'previous_1rm': old_1rm,
                            'achieved_at': str(session.started_at.date()),
                            'is_first': False,
                        })

            muscle_name = exercise.primary_muscle.name if exercise.primary_muscle else ''
            cardio_candidates.append((exercise.name, muscle_name, created_sets))

        return new_prs, cardio_candidates

    @staticmethod
    def _sync_cardio_entry(session, user, cardio_candidates):
        """Keeps the auto-generated CardioEntry for this session in sync with its
        current cardio sets: updates it in place, creates it if newly cardio, or
        deletes it if the session no longer has qualifying cardio sets."""
        total_cardio_secs = 0
        cardio_modality = 'OTHER'
        cardio_intensity = 'Zone 2'
        for ex_name_raw, muscle_name_raw, sets in cardio_candidates:
            ex_name = ex_name_raw.lower()
            muscle_name = muscle_name_raw.lower()
            is_cardio = muscle_name == 'cardio' or 'cardio' in muscle_name or any(s.duration_seconds for s in sets)
            if not is_cardio:
                continue

            if 'tread' in ex_name or 'incline' in ex_name or 'walk' in ex_name:
                cardio_modality = 'TREADMILL'
            elif 'cycl' in ex_name or 'bike' in ex_name or 'spin' in ex_name:
                cardio_modality = 'CYCLING'
            elif 'row' in ex_name:
                cardio_modality = 'ROWING'
            elif 'ellipt' in ex_name:
                cardio_modality = 'ELLIPTICAL'
            elif 'cross' in ex_name:
                cardio_modality = 'CROSS_TRAINER'

            for s in sets:
                if not s.completed:
                    continue
                if s.duration_seconds:
                    total_cardio_secs += s.duration_seconds
                if s.intensity:
                    cardio_intensity = s.intensity
                if s.incline_percent is not None and s.incline_percent > 0:
                    cardio_intensity = f"{s.incline_percent}% Incline ({cardio_intensity})"

        existing_entry = CardioEntry.objects.filter(session=session).first()
        if total_cardio_secs >= 60:
            cardio_mins = round(total_cardio_secs / 60)
            if existing_entry:
                existing_entry.date = session.started_at.date()
                existing_entry.modality = cardio_modality
                existing_entry.duration_minutes = cardio_mins
                existing_entry.intensity = cardio_intensity
                existing_entry.completed = True
                existing_entry.save()
            else:
                CardioEntry.objects.create(
                    user=user,
                    session=session,
                    date=session.started_at.date(),
                    modality=cardio_modality,
                    duration_minutes=cardio_mins,
                    intensity=cardio_intensity,
                    completed=True
                )
        elif existing_entry:
            existing_entry.delete()

    @transaction.atomic
    def create(self, validated_data):
        exercises_data = validated_data.pop('exercises', [])
        user = self.context['request'].user
        # The session is being saved because it finished, so completed_at is never left
        # empty: trust the client's clock when sent, else derive it from the duration.
        if not validated_data.get('completed_at'):
            duration = validated_data.get('duration_seconds') or 0
            started_at = validated_data.get('started_at')
            validated_data['completed_at'] = (
                started_at + timedelta(seconds=duration) if started_at and duration else timezone.now()
            )
        session = WorkoutSession.objects.create(user=user, **validated_data)
        weight_kg = getattr(getattr(user, 'profile', None), 'weight_kg', None)

        new_prs, cardio_candidates = self._create_exercises(session, exercises_data, weight_kg, user, track_prs=True)
        session._new_prs = new_prs
        self._sync_cardio_entry(session, user, cardio_candidates)

        # If linked to an assigned workout, mark it COMPLETED
        if session.assigned_workout:
            assigned = session.assigned_workout
            assigned.status = 'COMPLETED'
            assigned.save()

            # Notify trainer
            Notification.objects.create(
                recipient=assigned.trainer,
                actor=user,
                gym=assigned.gym,
                verb='WORKOUT_COMPLETED',
                message=f"{user.get_full_name() or user.email} completed assigned workout: {assigned.routine.name}",
                target_type='WorkoutSession',
                target_id=str(session.id)
            )

        # A program day is not tied to a calendar date. Completing its session
        # advances the next unfinished prescription; missed dates never erase it.
        if session.routine_id:
            program = JourneyProgram.objects.filter(user=user, active=True).first()
            if program:
                program_day = ProgramDay.objects.filter(
                    program=program, day_number=program.current_day,
                    routine_id=session.routine_id, status='UPCOMING'
                ).first()
                if program_day:
                    program_day.status = 'COMPLETED'
                    program_day.completed_session = session
                    program_day.save(update_fields=['status', 'completed_session', 'updated_at'])
                    next_day = program.days.filter(day_number__gt=program.current_day, status='UPCOMING').order_by('day_number').first()
                    if next_day:
                        program.current_day = next_day.day_number
                    else:
                        program.active = False
                    program.save(update_fields=['current_day', 'active', 'updated_at'])

        AuditLog.objects.create(
            actor=user,
            gym=session.gym,
            action='WORKOUT_COMPLETED',
            resource_type='WorkoutSession',
            resource_id=str(session.id),
            details={'title': session.title, 'exercises_count': len(exercises_data)}
        )

        return session

    @transaction.atomic
    def update(self, instance, validated_data):
        # Program-day completion and assigned-workout status were settled when the
        # session was created; an edit only rewrites the log itself.
        validated_data.pop('routine', None)
        validated_data.pop('assigned_workout', None)
        exercises_data = validated_data.pop('exercises', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if 'started_at' in validated_data or 'duration_seconds' in validated_data:
            instance.completed_at = instance.started_at + timedelta(seconds=instance.duration_seconds or 0)
        instance.save()

        if exercises_data is not None:
            weight_kg = getattr(getattr(instance.user, 'profile', None), 'weight_kg', None)
            affected = set(instance.exercises.values_list('exercise_id', flat=True))
            affected.update(ex_data['exercise'].id for ex_data in exercises_data if ex_data.get('exercise'))
            instance.exercises.all().delete()

            _, cardio_candidates = self._create_exercises(instance, exercises_data, weight_kg, instance.user, track_prs=False)
            self._sync_cardio_entry(instance, instance.user, cardio_candidates)
            recompute_personal_records(instance.user, affected)
        elif 'started_at' in validated_data:
            # PR dates follow the session date.
            recompute_personal_records(instance.user, instance.exercises.values_list('exercise_id', flat=True))

        return instance

class RoutineExerciseSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source='exercise.name', read_only=True)
    primary_muscle = serializers.CharField(source='exercise.primary_muscle.name', read_only=True)
    met_value = serializers.FloatField(source='exercise.met_value', read_only=True)
    progression = serializers.SerializerMethodField()
    swap = serializers.SerializerMethodField()

    class Meta:
        model = RoutineExercise
        fields = ['id', 'exercise', 'exercise_name', 'primary_muscle', 'met_value', 'order', 'target_sets', 'target_reps', 'rest_seconds', 'target_rpe', 'suggested_weight_kg', 'focus', 'notes', 'progression', 'swap']

    def get_progression(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        # Nested serializers share the root context, so one plan response looks up
        # each exercise's history once no matter how many days repeat it.
        cache = self.context.setdefault('_progression_history', {})
        return progression_for(request.user, obj, cache)

    def get_swap(self, obj):
        # Set by ProgramDaySerializer.to_representation for each day being rendered;
        # absent when this serializer is used outside a program-day context (e.g. the
        # routines list/editor), where no per-day override applies.
        program_day_id = self.context.get('_current_program_day_id')
        if not program_day_id:
            return None
        swap_map = self.context.setdefault('_swap_map', {})
        if program_day_id not in swap_map:
            swap_map[program_day_id] = {
                s.routine_exercise_id: s
                for s in ProgramDayExerciseSwap.objects.filter(
                    program_day_id=program_day_id
                ).select_related('replacement_exercise', 'replacement_exercise__primary_muscle')
            }
        swap = swap_map[program_day_id].get(obj.id)
        if not swap:
            return None
        return {
            'id': str(swap.id),
            'exercise': str(swap.replacement_exercise_id),
            'exercise_name': swap.replacement_exercise.name,
            'primary_muscle': swap.replacement_exercise.primary_muscle.name if swap.replacement_exercise.primary_muscle_id else None,
            'met_value': swap.replacement_exercise.met_value,
        }

class RoutineSerializer(serializers.ModelSerializer):
    exercises = RoutineExerciseSerializer(many=True, required=False)
    created_by_name = serializers.SerializerMethodField()
    is_gym_template = serializers.BooleanField(read_only=True)

    class Meta:
        model = Routine
        fields = [
            'id', 'name', 'description', 'gym', 'user', 'created_by', 'created_by_name',
            'last_modified_by', 'is_gym_template', 'exercises', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_by', 'last_modified_by', 'created_at', 'updated_at']

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.email
        return None

    @transaction.atomic
    def create(self, validated_data):
        exercises_data = validated_data.pop('exercises', [])
        user = self.context['request'].user
        routine = Routine.objects.create(created_by=user, last_modified_by=user, **validated_data)

        for ex_data in exercises_data:
            RoutineExercise.objects.create(routine=routine, **ex_data)

        return routine

class ProgramDaySerializer(serializers.ModelSerializer):
    routine_details = RoutineSerializer(source='routine', read_only=True)
    calendar_date = serializers.SerializerMethodField()
    completed_session_id = serializers.UUIDField(source='completed_session.id', read_only=True, allow_null=True)
    completed_session_title = serializers.CharField(source='completed_session.title', read_only=True, allow_null=True)

    class Meta:
        model = ProgramDay
        fields = [
            'id', 'day_number', 'calendar_date', 'label', 'is_optional', 'status', 'routine', 'routine_details',
            'completed_session_id', 'completed_session_title',
            'workout_payload', 'meal_payload', 'macro_targets', 'expected_weight_kg',
        ]

    def get_calendar_date(self, obj):
        if not obj.program_id or not obj.program.start_date:
            return None
        return (obj.program.start_date + timedelta(days=obj.day_number - 1)).isoformat()

    def to_representation(self, instance):
        # Tells the nested RoutineExerciseSerializer which day it's rendering for, so it
        # can look up this day's exercise swaps without changing the shared Routine template.
        self.context['_current_program_day_id'] = instance.id
        return super().to_representation(instance)

class CardioEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = CardioEntry
        fields = ['id', 'date', 'modality', 'duration_minutes', 'intensity', 'heart_rate', 'target_zone', 'completed']
        read_only_fields = ['user']

class AssignedWorkoutSerializer(serializers.ModelSerializer):
    routine_name = serializers.CharField(source='routine.name', read_only=True)
    trainer_name = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    gym_name = serializers.CharField(source='gym.name', read_only=True)
    routine_details = RoutineSerializer(source='routine', read_only=True)

    class Meta:
        model = AssignedWorkout
        fields = [
            'id', 'gym', 'gym_name', 'trainer', 'trainer_name', 'client', 'client_name',
            'routine', 'routine_name', 'routine_details', 'scheduled_date', 'status',
            'trainer_feedback', 'feedback_date', 'created_at'
        ]
        read_only_fields = ['trainer', 'created_at']

    def get_trainer_name(self, obj):
        return obj.trainer.get_full_name() or obj.trainer.username

    def get_client_name(self, obj):
        return obj.client.get_full_name() or obj.client.username

    def create(self, validated_data):
        user = self.context['request'].user
        assigned = AssignedWorkout.objects.create(trainer=user, **validated_data)

        # Notify member
        Notification.objects.create(
            recipient=assigned.client,
            actor=user,
            gym=assigned.gym,
            verb='WORKOUT_ASSIGNED',
            message=f"Coach {user.get_full_name() or user.email} assigned routine: {assigned.routine.name}",
            target_type='AssignedWorkout',
            target_id=str(assigned.id)
        )

        AuditLog.objects.create(
            actor=user,
            gym=assigned.gym,
            action='WORKOUT_ASSIGNED',
            resource_type='AssignedWorkout',
            resource_id=str(assigned.id),
            details={'routine': assigned.routine.name, 'client': assigned.client.email}
        )

        return assigned
