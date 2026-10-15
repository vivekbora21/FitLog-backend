from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from .models import JourneyProgram, ProgramDay


def _scheduled_date(program, day):
    return day.scheduled_date or (program.start_date + timedelta(days=day.day_number - 1))


def _is_rest_day(day):
    if day.status == 'REST':
        return True
    routine_name = (day.routine.name if getattr(day, 'routine', None) else '').lower()
    return 'rest' in routine_name or 'recovery' in routine_name


@transaction.atomic
def reconcile_plan(program: JourneyProgram, today: date | None = None):
    """Reconcile overdue plan days once, using the user's active local date.

    Completed counts require a real completed session. Rest/optional days are
    never eligible for missed status, and future days are never touched.
    """
    today = today or timezone.localdate()
    original_end = program.original_end_date or program.start_date + timedelta(days=program.duration_days - 1)
    effective_end = program.effective_end_date or original_end
    changed_program = []
    if program.original_end_date != original_end:
        program.original_end_date = original_end
        changed_program.append('original_end_date')
    if program.effective_end_date != effective_end:
        program.effective_end_date = effective_end
        changed_program.append('effective_end_date')

    days = list(program.days.select_related('routine', 'completed_session').all())
    for day in days:
        scheduled = _scheduled_date(program, day)
        if day.scheduled_date is None:
            day.scheduled_date = scheduled
            day.save(update_fields=['scheduled_date', 'updated_at'])

        if _is_rest_day(day):
            continue

        # Current and future program days are not overdue/missed;
        # restore any that were mistakenly marked MISSED in the past.
        if day.day_number >= program.current_day:
            if day.status == 'MISSED' and not day.completed_session_id:
                day.status = 'UPCOMING'
                day.save(update_fields=['status', 'updated_at'])
            continue

        # Past days (day_number < current_day) that were never completed:
        if scheduled < today and day.status == 'UPCOMING' and not day.completed_session_id:
            day.status = 'MISSED'
            day.save(update_fields=['status', 'updated_at'])

    if today >= effective_end and program.plan_status != 'COMPLETED':
        program.plan_status = 'COMPLETED'
        changed_program.append('plan_status')
    if changed_program:
        changed_program.append('updated_at')
        program.save(update_fields=changed_program)
    return build_plan_state(program, today=today, days=days)


def build_plan_state(program: JourneyProgram, today: date | None = None, days=None):
    today = today or timezone.localdate()
    original_end = program.original_end_date or program.start_date + timedelta(days=program.duration_days - 1)
    effective_end = program.effective_end_date or original_end
    days = list(days if days is not None else program.days.select_related('routine', 'completed_session').all())
    eligible = [d for d in days if not _is_rest_day(d)]
    completed = [d for d in eligible if d.status == 'COMPLETED' and d.completed_session_id]
    missed = [d for d in eligible if d.status == 'MISSED' and not d.completed_session_id]
    scheduled = [d for d in eligible if _scheduled_date(program, d) <= effective_end]
    elapsed = max(0, min((today - program.start_date).days + 1, (effective_end - program.start_date).days + 1))
    total_calendar_days = max(1, (effective_end - program.start_date).days + 1)
    return {
        'start_date': program.start_date.isoformat(),
        'original_end_date': original_end.isoformat(),
        'effective_end_date': effective_end.isoformat(),
        'duration_days': program.duration_days,
        'effective_duration_days': total_calendar_days,
        'elapsed_calendar_days': elapsed,
        'remaining_calendar_days': max(0, (effective_end - today).days),
        'calendar_progress_percent': round(min(100, max(0, elapsed / total_calendar_days * 100)), 1),
        'completed_workout_count': len(completed),
        'missed_workout_count': len(missed),
        'scheduled_workout_count': len(scheduled),
        'completed_workout_dates': [_scheduled_date(program, d).isoformat() for d in completed],
        'plan_status': program.plan_status,
        'extension_status': program.extension_status,
        'extension_days': program.extension_days,
        'extension_eligible': program.plan_status == 'COMPLETED' and bool(missed) and program.extension_status == 'NONE',
        'near_completion': program.plan_status == 'ACTIVE' and (effective_end - today).days == 3,
    }
