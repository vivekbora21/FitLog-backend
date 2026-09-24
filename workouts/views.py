from datetime import date, timedelta
from collections import Counter
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db import models, transaction
from django.db.models import Count, Q
from .models import Routine, AssignedWorkout, WorkoutSession, JourneyProgram, ProgramDay, CardioEntry
from .serializers import RoutineSerializer, AssignedWorkoutSerializer, WorkoutSessionSerializer, ProgramDaySerializer, CardioEntrySerializer
from memberships.models import TrainerClientAssignment, GymMembership
from progress.models import WeightEntry, BodyMeasurement, PersonalRecord
from nutrition.models import NutritionDay
from nutrition.targets import TargetTimeline
from core.models import AuditLog
from notifications.models import Notification
from analytics.pacing import (
    resolve_start_weight,
    resolve_target_weekly_rate,
    resolve_target_weight,
    calculate_journey_pacing,
    DEFAULT_WEEKLY_RATES,
)

class WorkoutSessionViewSet(viewsets.ModelViewSet):
    serializer_class = WorkoutSessionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        client_id = self.request.query_params.get('client_id')

        if client_id:
            # Check if requesting user is assigned trainer for this client and client shared workouts
            is_coach = TrainerClientAssignment.objects.filter(
                trainer_membership__user=user,
                client_membership__user_id=client_id,
                is_active=True,
                client_membership__share_workouts_with_trainers=True
            ).exists()
            if is_coach:
                return WorkoutSession.objects.filter(user_id=client_id).prefetch_related(
                    'exercises__sets', 'exercises__exercise'
                )
            return WorkoutSession.objects.none()

        # By default, member sees their own personal sessions
        return WorkoutSession.objects.filter(user=user).prefetch_related(
            'exercises__sets', 'exercises__exercise'
        )

    @action(detail=False, methods=['get'], url_path='today')
    def today(self, request):
        program = JourneyProgram.objects.filter(user=request.user, active=True).first()
        if not program:
            return Response({'program': None, 'today': None})
        day = program.days.filter(day_number=program.current_day).select_related('routine').prefetch_related('routine__exercises__exercise').first()
        return Response({
            'program': {
                'id': str(program.id),
                'name': program.name,
                'mode': program.mode,
                'mode_label': dict(JourneyProgram.MODE_CHOICES).get(program.mode, program.mode),
                'current_day': program.current_day,
                'duration_days': program.duration_days,
            },
            'today': ProgramDaySerializer(day, context={'request': request}).data if day else None
        })

    @action(detail=False, methods=['get'], url_path='plan')
    def plan(self, request):
        program = JourneyProgram.objects.filter(user=request.user, active=True).first()
        if not program:
            return Response({'program': None, 'days': []})
        days = program.days.select_related('routine').prefetch_related(
            'routine__exercises__exercise',
            'routine__exercises__exercise__primary_muscle'
        ).order_by('day_number')
        return Response({
            'program': {
                'id': str(program.id),
                'name': program.name,
                'mode': program.mode,
                'mode_label': dict(JourneyProgram.MODE_CHOICES).get(program.mode, program.mode),
                'start_date': program.start_date,
                'current_day': program.current_day,
                'duration_days': program.duration_days,
                'start_weight_kg': program.start_weight_kg,
                'target_weight_kg': program.target_weight_kg,
                'target_weekly_rate_kg': program.target_weekly_rate_kg,
                'target_cardio_minutes_early': program.target_cardio_minutes_early,
                'target_cardio_minutes_later': program.target_cardio_minutes_later,
            },
            'days': ProgramDaySerializer(days, many=True, context={'request': request}).data,
        })

    @action(detail=False, methods=['get'], url_path='journey-history')
    def journey_history(self, request):
        programs = JourneyProgram.objects.filter(user=request.user).annotate(
            completed_days=Count('days', filter=Q(days__status='COMPLETED'))
        ).order_by('-start_date', '-created_at')

        journeys = [
            {
                'id': str(p.id),
                'name': p.name,
                'mode': p.mode,
                'mode_label': dict(JourneyProgram.MODE_CHOICES).get(p.mode, p.mode),
                'start_date': str(p.start_date),
                'duration_days': p.duration_days,
                'current_day': p.current_day,
                'completed_days': p.completed_days,
                'active': p.active,
                'archived_at': p.archived_at.isoformat() if p.archived_at else None,
                'start_weight_kg': p.start_weight_kg,
                'target_weight_kg': p.target_weight_kg,
            }
            for p in programs
        ]
        return Response({'journeys': journeys})

    @action(detail=False, methods=['get'], url_path='journey/(?P<journey_id>[^/.]+)')
    def journey_detail(self, request, journey_id=None):
        program = JourneyProgram.objects.filter(user=request.user, id=journey_id).select_related('focus_exercise').first()
        if not program:
            return Response({'error': 'Journey not found.'}, status=status.HTTP_404_NOT_FOUND)

        days = program.days.select_related('routine', 'completed_session').prefetch_related(
            'routine__exercises__exercise',
            'routine__exercises__exercise__primary_muscle',
            'completed_session__exercises__exercise',
            'completed_session__exercises__exercise__primary_muscle',
            'completed_session__exercises__sets',
        ).order_by('day_number')

        days_data = []
        completed_days = 0
        missed_days = 0
        for d in days:
            entry = ProgramDaySerializer(d).data
            entry['completed_session'] = WorkoutSessionSerializer(d.completed_session).data if d.completed_session else None
            days_data.append(entry)
            if d.status == 'COMPLETED':
                completed_days += 1
            elif d.status == 'MISSED':
                missed_days += 1

        start_date = program.start_date
        end_date = start_date + timedelta(days=program.duration_days - 1)
        today = date.today()
        range_end = min(end_date, today)

        weight_log = list(
            WeightEntry.objects.filter(user=request.user, date__gte=start_date, date__lte=end_date)
            .order_by('date')
            .values('date', 'weight_kg', 'body_fat_pct', 'notes')
        )
        cardio_log = list(
            CardioEntry.objects.filter(user=request.user, date__gte=start_date, date__lte=end_date)
            .order_by('date')
            .values('id', 'date', 'modality', 'duration_minutes', 'intensity', 'heart_rate', 'target_zone', 'completed')
        )
        measurements_log = list(
            BodyMeasurement.objects.filter(user=request.user, date__gte=start_date, date__lte=end_date)
            .order_by('date')
            .values(
                'date', 'neck_cm', 'shoulders_cm', 'chest_cm', 'waist_cm', 'hips_cm',
                'arms_cm', 'biceps_left_cm', 'biceps_right_cm', 'forearms_cm',
                'thighs_cm', 'thigh_left_cm', 'thigh_right_cm', 'calves_cm', 'calf_left_cm', 'calf_right_cm',
            )
        )

        pacing = calculate_journey_pacing(request.user, program)

        personal_records = [
            {
                'exercise': pr.exercise.name,
                'primary_muscle': pr.exercise.primary_muscle.name if pr.exercise.primary_muscle else None,
                'max_weight_kg': pr.max_weight_kg,
                'reps': pr.reps,
                'estimated_one_rep_max': pr.estimated_one_rep_max,
                'achieved_at': str(pr.achieved_at),
            }
            for pr in PersonalRecord.objects.filter(
                user=request.user, achieved_at__gte=start_date, achieved_at__lte=range_end
            ).select_related('exercise', 'exercise__primary_muscle').order_by('-achieved_at')
        ]

        # All logged sessions in the journey window (including ones not tied to a program day)
        all_sessions = list(
            WorkoutSession.objects.filter(
                user=request.user, started_at__date__gte=start_date, started_at__date__lte=end_date
            ).prefetch_related('exercises__sets', 'exercises__exercise__primary_muscle').order_by('started_at')
        )

        total_volume_kg = round(sum(s.total_volume_kg() for s in all_sessions), 1)
        total_sets = sum(
            1 for s in all_sessions for we in s.exercises.all() for st in we.sets.all() if st.completed
        )
        total_training_minutes = round(sum(s.duration_seconds for s in all_sessions) / 60)
        session_rpes = [s.overall_rpe for s in all_sessions if s.overall_rpe]
        avg_session_rpe = round(sum(session_rpes) / len(session_rpes), 1) if session_rpes else None

        best_session = max(all_sessions, key=lambda s: s.total_volume_kg(), default=None)
        best_session_data = None
        if best_session and best_session.total_volume_kg() > 0:
            best_session_data = {
                'title': best_session.title,
                'date': best_session.started_at.strftime('%Y-%m-%d'),
                'volume_kg': round(best_session.total_volume_kg(), 1),
            }

        muscle_counter = Counter()
        for s in all_sessions:
            for we in s.exercises.all():
                completed_sets = sum(1 for st in we.sets.all() if st.completed)
                if completed_sets and we.exercise.primary_muscle:
                    muscle_counter[we.exercise.primary_muscle.name] += completed_sets
        muscle_breakdown = [
            {'muscle': muscle, 'sets': count}
            for muscle, count in muscle_counter.most_common(8)
        ]

        volume_trend = [
            {
                'date': s.started_at.strftime('%Y-%m-%d'),
                'label': s.started_at.strftime('%b %d'),
                'title': s.title,
                'volume_kg': round(s.total_volume_kg(), 1),
                'duration_min': round(s.duration_seconds / 60),
            }
            for s in all_sessions
        ]

        # Fall back to the pacing engine's resolved baseline (nearest prior weigh-in, or
        # profile weight) when the program itself was started without a start weight.
        pacing_velocity = pacing.get('velocity') or {}
        start_weight = program.start_weight_kg if program.start_weight_kg else pacing_velocity.get('start_weight')
        current_weight = weight_log[-1]['weight_kg'] if weight_log else start_weight
        weight_change = round(current_weight - start_weight, 2) if (current_weight is not None and start_weight is not None) else None

        waist_readings = [m['waist_cm'] for m in measurements_log if m['waist_cm'] is not None]
        start_waist = waist_readings[0] if waist_readings else None
        current_waist = waist_readings[-1] if waist_readings else None
        waist_change = round(current_waist - start_waist, 1) if (start_waist is not None and current_waist is not None) else None

        # Nutrition adherence across the journey window
        days_in_range = max(0, (range_end - start_date).days + 1)
        nutrition_days = list(
            NutritionDay.objects.filter(user=request.user, date__gte=start_date, date__lte=range_end)
            .prefetch_related('meals')
        )
        # Judge the plan against the targets that applied when it ended, not today's.
        macro_target = TargetTimeline(request.user).on(range_end)
        nutrition_summary = None
        if nutrition_days:
            avg_calories = round(sum(nd.total_calories() for nd in nutrition_days) / len(nutrition_days))
            avg_protein = round(sum(nd.total_protein() for nd in nutrition_days) / len(nutrition_days), 1)
            nutrition_summary = {
                'days_logged': len(nutrition_days),
                'days_in_range': days_in_range,
                'avg_calories': avg_calories,
                'calories_target': macro_target.daily_calories,
                'avg_protein_g': avg_protein,
                'protein_target_g': macro_target.protein_g,
            }

        summary = {
            'total_workouts': len(all_sessions),
            'total_volume_kg': total_volume_kg,
            'total_sets': total_sets,
            'total_training_minutes': total_training_minutes,
            'avg_session_rpe': avg_session_rpe,
            'best_session': best_session_data,
            'muscle_breakdown': muscle_breakdown,
            'start_weight_kg': start_weight,
            'current_weight_kg': current_weight,
            'weight_change_kg': weight_change,
            'start_waist_cm': start_waist,
            'current_waist_cm': current_waist,
            'waist_change_cm': waist_change,
            'total_cardio_minutes': sum(c['duration_minutes'] for c in cardio_log if c['completed']),
            'total_cardio_sessions': len(cardio_log),
        }

        return Response({
            'program': {
                'id': str(program.id),
                'name': program.name,
                'mode': program.mode,
                'mode_label': dict(JourneyProgram.MODE_CHOICES).get(program.mode, program.mode),
                'start_date': str(program.start_date),
                'end_date': str(end_date),
                'duration_days': program.duration_days,
                'current_day': program.current_day,
                'active': program.active,
                'archived_at': program.archived_at.isoformat() if program.archived_at else None,
                'start_weight_kg': program.start_weight_kg,
                'target_weight_kg': program.target_weight_kg,
                'target_weekly_rate_kg': program.target_weekly_rate_kg,
                'target_cardio_minutes_early': program.target_cardio_minutes_early,
                'target_cardio_minutes_later': program.target_cardio_minutes_later,
                'focus_exercise_name': program.focus_exercise.name if program.focus_exercise else None,
                'target_focus_1rm': program.target_focus_1rm,
                'completed_days': completed_days,
                'missed_days': missed_days,
            },
            'pacing': pacing,
            'summary': summary,
            'personal_records': personal_records,
            'volume_trend': volume_trend,
            'days': days_data,
            'weight_log': weight_log,
            'measurements_log': measurements_log,
            'cardio_log': cardio_log,
            'nutrition_summary': nutrition_summary,
        })

    @action(detail=False, methods=['post'], url_path='start-journey')
    @transaction.atomic
    def start_journey(self, request):
        user = request.user
        data = request.data or {}

        mode = data.get('mode', 'CUT')
        if mode not in dict(JourneyProgram.MODE_CHOICES):
            mode = 'CUT'

        blueprint = data.get('blueprint')

        # Plan length comes from the member: either a day count or a target end date.
        start_date = date.today()
        raw_end_date = data.get('end_date')
        try:
            if raw_end_date:
                duration_days = (date.fromisoformat(str(raw_end_date)) - start_date).days + 1
            else:
                duration_days = int(data.get('duration_days'))
        except (ValueError, TypeError):
            return Response(
                {'detail': 'Provide duration_days or a valid end_date (YYYY-MM-DD).'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        min_days, max_days = JourneyProgram.MIN_DURATION_DAYS, JourneyProgram.MAX_DURATION_DAYS
        if not min_days <= duration_days <= max_days:
            return Response(
                {'detail': f'Plan length must be between {min_days} and {max_days} days (got {duration_days}).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        name = data.get('name')
        if not name:
            if blueprint == 'CUT_60':
                name = '60-Day Recomp & Shred'
            elif blueprint == 'BULK_90':
                name = '90-Day Mass Architecture'
            elif blueprint == 'FOCUS_30':
                name = '30-Day Strength Peak'
            elif blueprint == 'HABIT_21':
                name = '21-Day Habit Lock-in'
            else:
                name = f"{duration_days}-Day {dict(JourneyProgram.MODE_CHOICES).get(mode, 'Fitness')} Journey"

        # 1. Start weight resolution & precedence
        raw_start_w = data.get('start_weight_kg')
        start_weight_kg = resolve_start_weight(user, override_kg=raw_start_w, start_date=start_date)
        if raw_start_w is not None and str(raw_start_w).strip() != '':
            try:
                if float(raw_start_w) > 0:
                    WeightEntry.objects.update_or_create(
                        user=user,
                        date=start_date,
                        defaults={'weight_kg': start_weight_kg}
                    )
            except (ValueError, TypeError):
                pass

        # Target weight & weekly rate
        raw_target_w = data.get('target_weight_kg')
        target_weight_kg = None
        if raw_target_w is not None and str(raw_target_w).strip() != '':
            try:
                val = float(raw_target_w)
                if val > 0:
                    target_weight_kg = round(val, 2)
            except (ValueError, TypeError):
                pass

        target_weekly_rate_kg = resolve_target_weekly_rate(
            mode,
            start_weight_kg=start_weight_kg,
            target_weight_kg=target_weight_kg,
            duration_days=duration_days,
            explicit_rate_kg=data.get('target_weekly_rate_kg'),
        )
        if target_weight_kg is None:
            target_weight_kg = resolve_target_weight(start_weight_kg, target_weekly_rate_kg, duration_days)

        focus_exercise = None
        focus_exercise_id = data.get('focus_exercise_id')
        if focus_exercise_id:
            from exercises.models import Exercise
            focus_exercise = Exercise.objects.filter(id=focus_exercise_id).first()

        target_focus_1rm = None
        if data.get('target_focus_1rm'):
            try:
                target_focus_1rm = float(data.get('target_focus_1rm'))
            except (ValueError, TypeError):
                pass

        # 2. Non-destructive archiving of existing active journeys
        JourneyProgram.objects.filter(user=user, active=True).update(
            active=False,
            archived_at=timezone.now()
        )

        # 3. Create the new active JourneyProgram
        new_program = JourneyProgram.objects.create(
            user=user,
            name=name,
            mode=mode,
            start_date=start_date,
            duration_days=duration_days,
            current_day=1,
            active=True,
            start_weight_kg=start_weight_kg,
            target_weight_kg=target_weight_kg,
            target_weekly_rate_kg=target_weekly_rate_kg,
            focus_exercise=focus_exercise,
            target_focus_1rm=target_focus_1rm,
            target_cardio_minutes_early=60 if mode == 'BULK' else (90 if mode == 'FOCUS' else 120),
            target_cardio_minutes_later=75 if mode == 'BULK' else (105 if mode == 'FOCUS' else 150),
        )

        # 4. Schedule ProgramDay rows
        user_gym_ids = GymMembership.objects.filter(user=user, status='ACTIVE').values_list('gym_id', flat=True)
        available_routines = list(Routine.objects.filter(
            models.Q(user=user) | models.Q(gym_id__in=user_gym_ids)
        ).order_by('created_at').distinct())

        if not available_routines:
            default_r, _ = Routine.objects.get_or_create(
                user=user,
                name='Full Body Foundation',
                defaults={'description': 'Core strength and full body hypertrophy.'}
            )
            available_routines = [default_r]

        num_routines = len(available_routines)
        program_days = []
        for d in range(1, duration_days + 1):
            r = available_routines[(d - 1) % num_routines]
            is_optional = ((d % 7) == 6)
            is_rest = ((d % 7) == 0)
            label = f"Day {d}: {r.name}"
            if is_rest:
                label = f"Day {d}: Recovery & Active Rest"

            program_days.append(ProgramDay(
                program=new_program,
                day_number=d,
                routine=r,
                label=label,
                is_optional=is_optional or is_rest,
                status='UPCOMING'
            ))

        ProgramDay.objects.bulk_create(program_days)

        pacing_data = calculate_journey_pacing(user, new_program)

        return Response({
            'message': f"Journey successfully started: {new_program.name}",
            'program': {
                'id': str(new_program.id),
                'name': new_program.name,
                'mode': new_program.mode,
                'mode_label': dict(JourneyProgram.MODE_CHOICES).get(new_program.mode, new_program.mode),
                'start_date': str(new_program.start_date),
                'duration_days': new_program.duration_days,
                'current_day': 1,
                'start_weight_kg': new_program.start_weight_kg,
                'target_weight_kg': new_program.target_weight_kg,
                'target_weekly_rate_kg': new_program.target_weekly_rate_kg,
            },
            'pacing': pacing_data,
        }, status=status.HTTP_201_CREATED)

class RoutineViewSet(viewsets.ModelViewSet):
    serializer_class = RoutineSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # User's active gym IDs
        user_gym_ids = GymMembership.objects.filter(user=user, status='ACTIVE').values_list('gym_id', flat=True)

        # Personal routines OR templates from gyms user belongs to
        return Routine.objects.filter(
            models.Q(user=user) | models.Q(gym_id__in=user_gym_ids)
        ).prefetch_related('exercises__exercise').distinct()

class AssignedWorkoutViewSet(viewsets.ModelViewSet):
    serializer_class = AssignedWorkoutSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Return workouts assigned TO the user, or workouts assigned BY the user (if trainer)
        return AssignedWorkout.objects.filter(
            models.Q(client=user) | models.Q(trainer=user)
        ).select_related('routine', 'client', 'trainer', 'gym').order_by('-scheduled_date')

    @action(detail=True, methods=['post'], url_path='feedback')
    def give_feedback(self, request, pk=None):
        assigned = self.get_object()
        feedback = request.data.get('feedback', '')
        if not feedback:
            return Response({'error': 'Feedback text is required.'}, status=status.HTTP_400_BAD_REQUEST)

        assigned.trainer_feedback = feedback
        assigned.feedback_date = timezone.now()
        assigned.save()

        # Notify member
        Notification.objects.create(
            recipient=assigned.client,
            actor=request.user,
            gym=assigned.gym,
            verb='FEEDBACK_POSTED',
            message=f"Coach {request.user.get_full_name() or request.user.email} left feedback on your workout: {assigned.routine.name}",
            target_type='AssignedWorkout',
            target_id=str(assigned.id)
        )

        AuditLog.objects.create(
            actor=request.user,
            gym=assigned.gym,
            action='FEEDBACK_POSTED',
            resource_type='AssignedWorkout',
            resource_id=str(assigned.id),
            details={'client': assigned.client.email, 'routine': assigned.routine.name}
        )

        return Response(AssignedWorkoutSerializer(assigned).data)

class CardioEntryViewSet(viewsets.ModelViewSet):
    serializer_class = CardioEntrySerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        return CardioEntry.objects.filter(user=self.request.user).order_by('-date')
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
