from rest_framework import serializers
from django.db import transaction
from datetime import timedelta
from django.utils import timezone
from .progression import progression_for
from .models import Routine, RoutineExercise, AssignedWorkout, WorkoutSession, WorkoutExercise, WorkoutSet, ProgramDay, CardioEntry, JourneyProgram
from exercises.models import Exercise
from exercises.serializers import ExerciseSerializer
from progress.models import PersonalRecord
from progress.records import recompute_personal_records
from core.models import AuditLog
from notifications.models import Notification

class WorkoutSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkoutSet
        fields = ['id', 'set_number', 'set_type', 'weight_kg', 'reps', 'rpe', 'completed']

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

    class Meta:
        model = WorkoutSession
        fields = [
            'id', 'user', 'user_email', 'user_name', 'gym', 'gym_name', 'assigned_workout',
            'routine', 'title', 'started_at', 'completed_at', 'duration_seconds',
            'overall_rpe', 'notes', 'exercises', 'total_volume_kg', 'created_at'
        ]
        read_only_fields = ['user', 'created_at']

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

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

        for ex_data in exercises_data:
            sets_data = ex_data.pop('sets', [])
            workout_exercise = WorkoutExercise.objects.create(session=session, **ex_data)

            for s_data in sets_data:
                workout_set = WorkoutSet.objects.create(workout_exercise=workout_exercise, **s_data)

                # Check Personal Record if completed
                if workout_set.completed and workout_set.weight_kg > 0 and workout_set.reps > 0:
                    exercise = workout_exercise.exercise
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
                    if not created and est_1rm > pr.estimated_one_rep_max:
                        pr.max_weight_kg = workout_set.weight_kg
                        pr.reps = workout_set.reps
                        pr.estimated_one_rep_max = est_1rm
                        pr.achieved_at = session.started_at.date()
                        pr.save()

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
            affected = set(instance.exercises.values_list('exercise_id', flat=True))
            instance.exercises.all().delete()
            for ex_data in exercises_data:
                sets_data = ex_data.pop('sets', [])
                workout_exercise = WorkoutExercise.objects.create(session=instance, **ex_data)
                affected.add(workout_exercise.exercise_id)
                for s_data in sets_data:
                    WorkoutSet.objects.create(workout_exercise=workout_exercise, **s_data)
            recompute_personal_records(instance.user, affected)
        elif 'started_at' in validated_data:
            # PR dates follow the session date.
            recompute_personal_records(instance.user, instance.exercises.values_list('exercise_id', flat=True))

        return instance

class RoutineExerciseSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source='exercise.name', read_only=True)
    primary_muscle = serializers.CharField(source='exercise.primary_muscle.name', read_only=True)
    progression = serializers.SerializerMethodField()

    class Meta:
        model = RoutineExercise
        fields = ['id', 'exercise', 'exercise_name', 'primary_muscle', 'order', 'target_sets', 'target_reps', 'rest_seconds', 'target_rpe', 'suggested_weight_kg', 'focus', 'notes', 'progression']

    def get_progression(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        # Nested serializers share the root context, so one plan response looks up
        # each exercise's history once no matter how many days repeat it.
        cache = self.context.setdefault('_progression_history', {})
        return progression_for(request.user, obj, cache)

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
    class Meta:
        model = ProgramDay
        fields = ['id', 'day_number', 'label', 'is_optional', 'status', 'routine', 'routine_details']

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
