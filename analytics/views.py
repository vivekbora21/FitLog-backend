from datetime import date, timedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from django.db import models
from workouts.models import WorkoutSession, AssignedWorkout, CardioEntry, JourneyProgram, ProgramDay
from nutrition.defaults import DEFAULT_MACRO_TARGETS
from nutrition.models import NutritionDay
from nutrition.targets import TargetTimeline, weekly_cardio_target, weekly_workouts_target as resolve_weekly_workouts
from progress.models import PersonalRecord, WeightEntry, BodyMeasurement, DailyLog
from .pacing import calculate_journey_pacing, calculate_rolling_average
from .weekly_health import build_weekly_health
from .weekly_review import build_weekly_review

class DashboardStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        start_of_month = today.replace(day=1)
        ninety_days_ago = today - timedelta(days=90)

        # Workouts
        user_sessions = WorkoutSession.objects.filter(user=user)
        workouts_this_week = user_sessions.filter(started_at__date__gte=start_of_week).count()
        workouts_this_month = user_sessions.filter(started_at__date__gte=start_of_month).count()

        # Volume calculation this week
        week_sessions = user_sessions.filter(started_at__date__gte=start_of_week)
        total_volume_week = sum(s.total_volume_kg() for s in week_sessions)

        # Activity heatmap: session dates in last 90 days
        recent_sessions = user_sessions.filter(started_at__date__gte=ninety_days_ago)
        activity_dates = {}
        for s in recent_sessions:
            d_str = s.started_at.strftime('%Y-%m-%d')
            activity_dates[d_str] = activity_dates.get(d_str, 0) + 1

        # Current streak calculation (consecutive days backwards from today/yesterday)
        streak = 0
        check_date = today
        if not activity_dates.get(check_date.strftime('%Y-%m-%d')):
            check_date = today - timedelta(days=1)
        while activity_dates.get(check_date.strftime('%Y-%m-%d')):
            streak += 1
            check_date -= timedelta(days=1)

        # Today's nutrition & daily lifestyle log
        nutrition_day = NutritionDay.objects.filter(user=user, date=today).first()
        timeline = TargetTimeline(user)
        target = timeline.current

        calories_consumed = nutrition_day.total_calories() if nutrition_day else 0
        protein_consumed = nutrition_day.total_protein() if nutrition_day else 0
        carbs_consumed = nutrition_day.total_carbs() if nutrition_day else 0
        fat_consumed = nutrition_day.total_fat() if nutrition_day else 0
        water_consumed = nutrition_day.water_consumed_ml if nutrition_day else 0

        daily_log_today = DailyLog.objects.filter(user=user, date=today).first()
        steps_today = daily_log_today.steps if daily_log_today and daily_log_today.steps is not None else 0
        sleep_today = daily_log_today.sleep_hours if daily_log_today and daily_log_today.sleep_hours is not None else 0.0
        sleep_quality_today = daily_log_today.sleep_quality if daily_log_today else None
        energy_level_today = daily_log_today.energy_level if daily_log_today else None
        recovery_notes_today = daily_log_today.recovery_notes if daily_log_today else ''


        # Pending assigned workout
        pending_assigned = AssignedWorkout.objects.filter(
            client=user,
            status='PENDING'
        ).select_related('routine', 'trainer').first()

        pending_workout_data = None
        if pending_assigned:
            pending_workout_data = {
                'id': str(pending_assigned.id),
                'routine_name': pending_assigned.routine.name,
                'routine_id': str(pending_assigned.routine.id),
                'trainer_name': pending_assigned.trainer.get_full_name() or pending_assigned.trainer.email,
                'scheduled_date': str(pending_assigned.scheduled_date),
            }

        # Recent PRs
        prs = PersonalRecord.objects.filter(user=user).select_related('exercise')[:5]
        prs_data = [
            {
                'exercise': pr.exercise.name,
                'max_weight_kg': pr.max_weight_kg,
                'reps': pr.reps,
                'estimated_1rm': pr.estimated_one_rep_max,
                'achieved_at': str(pr.achieved_at)
            }
            for pr in prs
        ]

        weights = list(WeightEntry.objects.filter(user=user).order_by('date'))
        current_weight = weights[-1].weight_kg if weights else None
        starting_weight = weights[0].weight_kg if weights else None
        rolling = calculate_rolling_average([w.weight_kg for w in weights])
        previous_avg = calculate_rolling_average([w.weight_kg for w in weights[-14:-7]])
        weekly_change = round(rolling - previous_avg, 2) if rolling is not None and previous_avg is not None else None
        measurements = list(BodyMeasurement.objects.filter(user=user).order_by('date'))
        current_waist = next((m.waist_cm for m in reversed(measurements) if m.waist_cm is not None), None)
        starting_waist = next((m.waist_cm for m in measurements if m.waist_cm is not None), None)
        cardio_minutes = sum(CardioEntry.objects.filter(user=user, date__gte=start_of_week, completed=True).values_list('duration_minutes', flat=True))
        program = JourneyProgram.objects.filter(user=user, active=True).first()
        target_cardio = weekly_cardio_target(target, program)

        # Trend Series for Dashboard Charts
        measurement_waist_by_date = {m.date: m.waist_cm for m in measurements if m.waist_cm is not None}
        weight_trend = [
            {
                'date': w.date.strftime('%Y-%m-%d'),
                'label': w.date.strftime('%b %d'),
                'weight_kg': float(w.weight_kg),
                'waist_cm': float(measurement_waist_by_date[w.date]) if w.date in measurement_waist_by_date else None,
            }
            for w in weights[-14:]
        ]

        recent_sessions = list(
            user_sessions.prefetch_related('exercises__sets')
            .order_by('started_at')
        )
        volume_trend = [
            {
                'date': s.started_at.strftime('%Y-%m-%d'),
                'label': s.started_at.strftime('%b %d'),
                'title': s.title or (s.routine.name if s.routine else 'Session'),
                'volume_kg': round(s.total_volume_kg(), 1),
            }
            for s in recent_sessions[-8:]
        ]

        last_7_days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        nutrition_days_map = {
            nd.date: nd for nd in NutritionDay.objects.filter(
                user=user, date__gte=last_7_days[0], date__lte=last_7_days[-1]
            ).prefetch_related('meals')
        }
        nutrition_trend = [
            {
                'date': d.strftime('%Y-%m-%d'),
                'label': d.strftime('%a'),
                'calories': nutrition_days_map[d].total_calories() if d in nutrition_days_map else 0,
                'calories_target': timeline.on(d).daily_calories,
                'protein': nutrition_days_map[d].total_protein() if d in nutrition_days_map else 0,
                'protein_target': timeline.on(d).protein_g,
            }
            for d in last_7_days
        ]

        pacing_data = calculate_journey_pacing(user, program)
        resolved_starting_weight = (pacing_data.get('velocity') or {}).get('start_weight') or starting_weight
        resolved_starting_waist = pacing_data.get('starting_waist') or starting_waist
        resolved_current_waist = pacing_data.get('current_waist') or current_waist
        weekly_workouts_target = resolve_weekly_workouts(target, program)

        # Server-computed adherence payload
        adh_pacing = pacing_data.get('adherence') or {}
        workout_adh_pct = adh_pacing.get('adherence_pct')
        if workout_adh_pct is None:
            workout_adh_pct = min(100.0, round((workouts_this_week / max(1, weekly_workouts_target)) * 100.0, 1))

        cal_target = target.daily_calories or 0
        cal_pct = min(100.0, round((calories_consumed / max(1, cal_target)) * 100.0, 1)) if cal_target else 0.0

        protein_target = target.protein_g or 0
        protein_pct = min(100.0, round((protein_consumed / max(1, protein_target)) * 100.0, 1)) if protein_target else 0.0

        water_target = target.water_ml or DEFAULT_MACRO_TARGETS['water_ml']
        water_pct = min(100.0, round((water_consumed / max(1, water_target)) * 100.0, 1)) if water_target else 0.0

        cardio_pct = min(100.0, round((cardio_minutes / max(1, target_cardio)) * 100.0, 1)) if target_cardio else 0.0

        adherence_data = {
            'workout': {
                'label': 'Workout Adherence' if program else 'Weekly Workouts',
                'actual': adh_pacing.get('completed_sessions', workouts_this_week),
                'target': adh_pacing.get('scheduled_sessions', weekly_workouts_target),
                'percent': workout_adh_pct,
                'unit': 'sessions',
                'status': adh_pacing.get('status', 'EXCELLENT' if workout_adh_pct >= 85 else 'WARN'),
                'is_program': bool(program),
                'message': adh_pacing.get('message', ''),
            },
            'weekly_workouts': {
                'label': 'Weekly Workouts',
                'actual': workouts_this_week,
                'target': weekly_workouts_target,
                'percent': min(100.0, round((workouts_this_week / max(1, weekly_workouts_target)) * 100.0, 1)),
                'unit': 'sessions',
            },
            'calories': {
                'label': 'Calories',
                'actual': calories_consumed,
                'target': cal_target,
                'percent': cal_pct,
                'unit': 'kcal',
            },
            'protein': {
                'label': 'Protein',
                'actual': protein_consumed,
                'target': protein_target,
                'percent': protein_pct,
                'unit': 'g',
            },
            'water': {
                'label': 'Water',
                'actual': water_consumed,
                'target': water_target,
                'actual_cups': round(water_consumed / 250),
                'target_cups': round(water_target / 250),
                'percent': water_pct,
                'unit': 'cups',
            },
            'cardio': {
                'label': 'Weekly Cardio',
                'actual': cardio_minutes,
                'target': target_cardio,
                'percent': cardio_pct,
                'unit': 'min',
            },
            'steps': {
                'label': 'Daily Steps',
                'actual': steps_today,
                'target': target.daily_steps,
                'percent': min(100.0, round((steps_today / max(1, target.daily_steps)) * 100.0, 1)),
                'unit': 'steps',
            },
            'sleep': {
                'label': 'Nightly Sleep',
                'actual': sleep_today,
                'target': target.sleep_hours,
                'percent': min(100.0, round((sleep_today / target.sleep_hours) * 100.0, 1)),
                'unit': 'hours',
            },
        }

        # Sheet 11: Automated Weekly Review & Adaptive Decision Protocol
        weekly_review = []
        if program and program.start_date:
            weekly_review = build_weekly_review(
                user, program,
                start_weight=resolved_starting_weight,
                start_waist=resolved_starting_waist,
                today=today,
                timeline=timeline,
            )

        # One shared "this week" summary for the Dashboard strip and the Review page.
        weekly_health = build_weekly_health(
            user, weekly_review,
            weekly_workouts_target=weekly_workouts_target,
            cardio_target=target_cardio,
            calories_target=target.daily_calories,
            protein_target=target.protein_g,
            today=today,
            steps_target=target.daily_steps,
            sleep_target=target.sleep_hours,
        )

        # Calendar days (last 90 days to today + 14 days)
        cal_start = today - timedelta(days=90)
        cal_end = today + timedelta(days=14)
        cal_sessions = user_sessions.filter(
            started_at__date__gte=cal_start,
            started_at__date__lte=cal_end
        ).prefetch_related('exercises__sets', 'routine')

        sessions_by_date = {}
        for s in cal_sessions:
            d_key = s.started_at.strftime('%Y-%m-%d')
            if d_key not in sessions_by_date:
                sessions_by_date[d_key] = []
            sessions_by_date[d_key].append(s)

        daily_logs_map = {
            dl.date.strftime('%Y-%m-%d'): dl
            for dl in DailyLog.objects.filter(user=user, date__gte=cal_start, date__lte=cal_end)
        }

        program_days_map = {}
        if program and program.start_date:
            for pd in program.days.select_related('routine').all():
                p_date = program.start_date + timedelta(days=pd.day_number - 1)
                program_days_map[p_date.strftime('%Y-%m-%d')] = pd

        calendar_days = {}
        curr_d = cal_start
        while curr_d <= cal_end:
            k = curr_d.strftime('%Y-%m-%d')
            s_list = sessions_by_date.get(k, [])
            dl = daily_logs_map.get(k)
            pd = program_days_map.get(k)

            c_status = 'UPCOMING'
            workout_title = None
            duration_min = 0
            volume_kg = 0.0
            exercises_count = 0

            if s_list:
                c_status = 'COMPLETED'
                first_s = s_list[0]
                workout_title = first_s.title or (first_s.routine.name if first_s.routine else 'Workout Session')
                duration_min = round(sum(s.duration_seconds for s in s_list) / 60)
                volume_kg = round(sum(s.total_volume_kg() for s in s_list), 1)
                exercises_count = sum(s.exercises.count() for s in s_list)
            elif dl and dl.day_status:
                c_status = dl.day_status
            elif dl and dl.recovery_notes:
                rn = dl.recovery_notes.lower()
                if 'rest' in rn or 'recovery' in rn:
                    c_status = 'REST'
                elif 'skip' in rn or 'missed' in rn:
                    c_status = 'SKIPPED'
                elif 'completed' in rn:
                    c_status = 'COMPLETED'
            elif pd:
                r_name = (pd.routine.name if pd.routine else pd.label).lower()
                is_rest = 'rest' in r_name or 'recovery' in r_name or pd.is_optional
                if pd.status == 'COMPLETED':
                    c_status = 'REST' if is_rest else 'COMPLETED'
                elif pd.status == 'REST':
                    c_status = 'REST'
                elif pd.status == 'MISSED':
                    c_status = 'SKIPPED'

            calendar_days[k] = {
                'date': k,
                'status': c_status,
                'has_workout': len(s_list) > 0,
                'sessions_count': len(s_list),
                'workout_title': workout_title,
                'duration_min': duration_min,
                'volume_kg': volume_kg,
                'exercises_count': exercises_count,
                'notes': dl.recovery_notes if dl else '',
                'steps': dl.steps if dl else None,
                'sleep_hours': dl.sleep_hours if dl else None,
                'program_day': {
                    'day_number': pd.day_number,
                    'label': pd.label or (pd.routine.name if pd.routine else f'Day {pd.day_number}'),
                    'routine_id': str(pd.routine_id) if pd.routine_id else None,
                    'routine_name': pd.routine.name if pd.routine else '',
                    'status': pd.status,
                    'is_optional': pd.is_optional,
                } if pd else None,
            }
            curr_d += timedelta(days=1)

        return Response({
            'streak_days': streak,
            'workouts_this_week': workouts_this_week,
            'workouts_this_month': workouts_this_month,
            'weekly_workouts_target': weekly_workouts_target,
            'total_volume_kg_week': round(total_volume_week, 1),
            'nutrition': {
                'calories_consumed': calories_consumed,
                'calories_target': target.daily_calories,
                'protein_consumed': protein_consumed,
                'protein_target': target.protein_g,
                'carbs_consumed': carbs_consumed,
                'carbs_target': target.carbs_g,
                'fat_consumed': fat_consumed,
                'fat_target': target.fat_g,
                'water_consumed_ml': water_consumed,
                'water_target_ml': target.water_ml,
            },
            'daily_log': {
                'steps': steps_today,
                'sleep_hours': sleep_today,
                'sleep_quality': sleep_quality_today,
                'energy_level': energy_level_today,
                'recovery_notes': recovery_notes_today,
                'weight_kg': weights[-1].weight_kg if weights and weights[-1].date == today else None,
            },
            'activity_heatmap': activity_dates,
            'calendar_days': calendar_days,
            'pending_assigned_workout': pending_workout_data,
            'recent_prs': prs_data,
            'journey': {
                'mode': program.mode if program else 'CUT',
                'mode_label': dict(JourneyProgram.MODE_CHOICES).get(program.mode, program.mode) if program else 'Cut Mode',
                'start_date': program.start_date.isoformat() if program and program.start_date else None,
                'copilot_insight': pacing_data.get('copilot_insight', ''),
                'current_weight': current_weight,
                'starting_weight': resolved_starting_weight,
                'target_weight': pacing_data.get('target_weight'),
                'weight_change': round(current_weight - resolved_starting_weight, 2) if current_weight is not None and resolved_starting_weight is not None else None,
                'seven_day_average': rolling,
                'weekly_weight_change': weekly_change,
                'current_waist': resolved_current_waist,
                'starting_waist': resolved_starting_waist,
                'waist_change': round(resolved_current_waist - resolved_starting_waist, 1) if resolved_current_waist is not None and resolved_starting_waist is not None else None,
                'cardio_minutes': cardio_minutes,
                'cardio_target': target_cardio,
                'weekly_workouts_target': weekly_workouts_target,
                'program_day': program.current_day if program else None,
                'program_length': program.duration_days if program else None,
                'program_completion_percent': round(((program.current_day - 1) / program.duration_days) * 100, 1) if program else 0,
            },
            'journey_pacing': pacing_data,
            'weekly_review': weekly_review,
            'weekly_health': weekly_health,
            'adherence': adherence_data,
            'trends': {
                'weight': weight_trend,
                'volume': volume_trend,
                'nutrition': nutrition_trend,
            }
        })


class JourneyPacingStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        pacing = calculate_journey_pacing(request.user)
        return Response(pacing)


class CalendarDayStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        date_str = request.data.get('date')
        new_status = request.data.get('status')
        notes = request.data.get('notes', '')

        if not date_str:
            return Response({'error': 'Date is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_status not in ('COMPLETED', 'REST', 'SKIPPED', 'CLEAR'):
            return Response({'error': 'Invalid status. Choose COMPLETED, REST, SKIPPED, or CLEAR.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return Response({'error': 'Invalid date format (use YYYY-MM-DD).'}, status=status.HTTP_400_BAD_REQUEST)

        dl, _ = DailyLog.objects.get_or_create(user=user, date=target_date)
        dl.day_status = new_status if new_status != 'CLEAR' else ''
        if notes:
            dl.recovery_notes = notes
        elif new_status == 'REST' and not dl.recovery_notes:
            dl.recovery_notes = 'Rest day & recovery'
        elif new_status == 'SKIPPED' and not dl.recovery_notes:
            dl.recovery_notes = 'Workout skipped'
        dl.save()

        # Update program day if active program matches date
        program = JourneyProgram.objects.filter(user=user, active=True).first()
        if program and program.start_date:
            day_num = (target_date - program.start_date).days + 1
            if 1 <= day_num <= program.duration_days:
                pd = program.days.filter(day_number=day_num).first()
                if pd:
                    if new_status == 'COMPLETED':
                        pd.status = 'COMPLETED'
                    elif new_status == 'REST':
                        pd.status = 'REST'
                    elif new_status == 'SKIPPED':
                        pd.status = 'MISSED'
                    elif new_status == 'CLEAR':
                        pd.status = 'UPCOMING'
                    pd.save(update_fields=['status', 'updated_at'])

        return Response({
            'success': True,
            'date': date_str,
            'status': new_status,
            'notes': dl.recovery_notes,
        })

