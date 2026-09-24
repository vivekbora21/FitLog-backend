"""
Port of the workbook's "Weekly Review" sheet: per-week averages plus the
Rules 1–5 adaptive decision protocol. The rule order, thresholds and wording
mirror the sheet's formulas (columns E, L, O, P):

- Week 1 weight/waist change is measured against the Day-1 baseline; every
  later week is measured against the previous week (week-over-week).
- Rule 5 (strength declining) > Rule 4 (drop > 0.8 kg/wk) > Rule 3 (weight and
  waist both within ±0.2) > Rule 1 / 2 (both non-increasing) > default.

On top of the sheet's generic text, each row gets a `personal_note` that ties the
triggered rule to the user's own calorie target and logged intake.
"""
from datetime import timedelta
from statistics import mean

from django.utils import timezone

from nutrition.models import NutritionDay
from progress.models import BodyMeasurement, DailyLog, PersonalRecord, WeightEntry
from nutrition.targets import TargetTimeline, sleep_target_label, steps_target_label, weekly_workouts_target as resolve_weekly_workouts
from workouts.models import CardioEntry, ProgramDay, WorkoutSet

RULE_TEXT = {
    'Rule 5': "Rule 5: Do not increase training volume. Assess sleep, calories, recovery and fatigue.",
    'Rule 4': "Rule 4: Weight dropping too fast. Increase calories slightly (+100–150 kcal) and/or reduce cardio.",
    'Rule 3': "Rule 3: Weight & waist unchanged for 2 wks. Consider small adjustment (~100–150 kcal/day) OR modest increase in activity.",
    'Rule 1 / 2': "Rule 1 & 2: Maintain current plan. Steady recomposition and waist reduction on track.",
    'Rule 1': "Maintain current plan; monitor 7-day trend.",
}
WEEK_ONE_ACTION = "Maintain current plan. Lock in daily logging habit and hit 90–120 min initial cardio target."

STRENGTH_BASELINE = "Baseline Set"
STRENGTH_OK = "Maintained / Increasing"
STRENGTH_DECLINING = "Declining"
STRENGTH_UNKNOWN = "Not enough data"
# Average e1RM change across exercises trained in both weeks at or below this = declining.
STRENGTH_DECLINE_THRESHOLD = -0.025


def _weekly_best_e1rm(user, prog_start, duration):
    """{week_index: {exercise_id: best Epley e1RM that week}} over working sets."""
    sets = (
        WorkoutSet.objects
        .filter(
            workout_exercise__session__user=user,
            workout_exercise__session__started_at__date__gte=prog_start,
            workout_exercise__session__started_at__date__lt=prog_start + timedelta(days=duration),
            completed=True,
            weight_kg__gt=0,
            reps__gt=0,
        )
        .exclude(set_type='WARMUP')
        .values_list('workout_exercise__exercise_id', 'workout_exercise__session__started_at', 'weight_kg', 'reps')
    )
    by_week = {}
    for exercise_id, started_at, weight, reps in sets:
        session_date = timezone.localtime(started_at).date() if timezone.is_aware(started_at) else started_at.date()
        w_idx = (session_date - prog_start).days // 7
        e1rm = PersonalRecord.calculate_epley_1rm(weight, reps)
        week = by_week.setdefault(w_idx, {})
        week[exercise_id] = max(week.get(exercise_id, 0), e1rm)
    return by_week


def _strength_trend(w_idx, current, previous):
    if w_idx == 0:
        return STRENGTH_BASELINE
    shared = (current or {}).keys() & (previous or {}).keys()
    if not shared:
        return STRENGTH_UNKNOWN
    avg_change = mean((current[e] - previous[e]) / previous[e] for e in shared)
    return STRENGTH_DECLINING if avg_change <= STRENGTH_DECLINE_THRESHOLD else STRENGTH_OK


def _decide_rule(avg_weight, weight_change, waist_change, strength_trend):
    if avg_weight is None:
        return None
    if strength_trend == STRENGTH_DECLINING:
        return 'Rule 5'
    if weight_change is not None and weight_change < -0.8:
        return 'Rule 4'
    if weight_change is not None and abs(weight_change) < 0.2 and waist_change is not None and abs(waist_change) < 0.2:
        return 'Rule 3'
    if weight_change is not None and weight_change <= 0 and waist_change is not None and waist_change <= 0:
        return 'Rule 1 / 2'
    return 'Rule 1'


def _personal_note(rule, target_kcal, avg_calories, avg_steps, avg_sleep, steps_target=8000, sleep_target=7.5):
    """Turns the sheet's generic advice into numbers for this user's week."""
    gap = avg_calories - target_kcal if avg_calories is not None and target_kcal else None

    if rule == 'Rule 4':
        if gap is not None and gap < -150:
            return (f"You averaged {avg_calories:,} kcal, {abs(gap):,} below your {target_kcal:,} kcal target. "
                    f"Eat to your existing target before raising it.")
        return (f"A +100–150 kcal step moves your target from {target_kcal:,} to "
                f"{target_kcal + 100:,}–{target_kcal + 150:,} kcal/day.")

    if rule == 'Rule 3':
        if gap is not None and gap > 150:
            return (f"You averaged {avg_calories:,} kcal against a {target_kcal:,} kcal target (+{gap:,}). "
                    f"Close that gap before cutting the target further.")
        note = (f"A 100–150 kcal cut moves your target from {target_kcal:,} to "
                f"{target_kcal - 150:,}–{target_kcal - 100:,} kcal/day")
        if avg_steps is not None and avg_steps < steps_target:
            note += f", or lift steps from {avg_steps:,}/day toward {steps_target_label(steps_target)}"
        return note + "."

    if rule == 'Rule 5':
        causes = []
        if avg_sleep is not None and avg_sleep < sleep_target - 0.5:
            causes.append(f"sleep averaged {avg_sleep}h (target {sleep_target_label(sleep_target)})")
        if gap is not None and gap < -300:
            causes.append(f"intake averaged {avg_calories:,} kcal, {abs(gap):,} under target")
        if causes:
            return "Likely contributors: " + "; ".join(causes) + "."
        return "Sleep and calories look on target, so check session fatigue and deload if it persists."

    return None


def load_window_logs(user, start, end):
    """Nutrition, daily and cardio logs for [start, end], for use with window_averages."""
    return {
        'nutrition': list(NutritionDay.objects.filter(user=user, date__range=(start, end)).prefetch_related('meals')),
        'daily_logs': list(DailyLog.objects.filter(user=user, date__range=(start, end))),
        'cardio': list(CardioEntry.objects.filter(user=user, completed=True, date__range=(start, end))),
    }


def window_averages(logs, w_start, w_end):
    """Per-day intake/lifestyle averages over logged days in [w_start, w_end], plus total cardio."""
    in_week = lambda d: w_start <= d <= w_end

    # Only days with food logged — visiting the nutrition page creates empty days.
    wk_nutrition = [nd for nd in logs['nutrition'] if in_week(nd.date) and nd.meals.all()]
    wk_daily = [dl for dl in logs['daily_logs'] if in_week(dl.date)]
    wk_steps = [dl.steps for dl in wk_daily if dl.steps is not None]
    wk_sleep = [dl.sleep_hours for dl in wk_daily if dl.sleep_hours is not None]
    return {
        'avg_calories': round(mean(nd.total_calories() for nd in wk_nutrition)) if wk_nutrition else None,
        'avg_protein': round(mean(nd.total_protein() for nd in wk_nutrition)) if wk_nutrition else None,
        'avg_steps': int(round(mean(wk_steps))) if wk_steps else None,
        'avg_sleep': round(mean(wk_sleep), 1) if wk_sleep else None,
        'cardio_minutes': sum(c.duration_minutes for c in logs['cardio'] if in_week(c.date)),
        'daily_logs': wk_daily,
    }


def build_weekly_review(user, program, start_weight, start_waist, today, timeline=None):
    """
    Each week is judged against the targets in effect on its last day (or today
    for the current week), so editing a target later never rewrites past weeks.
    """
    timeline = timeline or TargetTimeline(user)
    prog_start = program.start_date
    duration = program.duration_days
    num_weeks = (duration + 6) // 7
    prog_end = prog_start + timedelta(days=duration - 1)

    weights = list(WeightEntry.objects.filter(user=user, date__range=(prog_start, prog_end)))
    measurements = list(BodyMeasurement.objects.filter(user=user, date__range=(prog_start, prog_end), waist_cm__isnull=False).order_by('date'))
    logs = load_window_logs(user, prog_start, prog_end)
    # Program days advance per completed session, not per calendar day, so a user
    # running behind finishes "Day 5" in week 2. Bucket by when it was actually done.
    completed_dates = []
    for pd in ProgramDay.objects.filter(program=program, status='COMPLETED').select_related('completed_session'):
        if pd.completed_session:
            started = pd.completed_session.started_at
            completed_dates.append(timezone.localtime(started).date() if timezone.is_aware(started) else started.date())
        elif pd.day_number is not None:
            completed_dates.append(prog_start + timedelta(days=pd.day_number - 1))
    strength_by_week = _weekly_best_e1rm(user, prog_start, duration)

    rows = []
    prev_avg_weight = None
    prev_waist = None
    for w_idx in range(num_weeks):
        w_start = prog_start + timedelta(days=w_idx * 7)
        w_end = min(w_start + timedelta(days=6), prog_end)
        in_week = lambda d: w_start <= d <= w_end
        is_first, is_last = w_idx == 0, w_idx == num_weeks - 1 and num_weeks > 1

        wk_weights = [w.weight_kg for w in weights if in_week(w.date)]
        avg_weight = round(mean(wk_weights), 2) if wk_weights else None
        baseline_weight = start_weight if is_first else prev_avg_weight
        weight_change = round(avg_weight - baseline_weight, 2) if avg_weight is not None and baseline_weight is not None else None

        averages = window_averages(logs, w_start, w_end)
        avg_calories, avg_protein = averages['avg_calories'], averages['avg_protein']
        avg_steps, avg_sleep = averages['avg_steps'], averages['avg_sleep']
        cardio_minutes = averages['cardio_minutes']
        wk_daily = averages['daily_logs']

        wk_targets = timeline.on(min(w_end, today))
        target_kcal = wk_targets.daily_calories
        weekly_workouts_target = resolve_weekly_workouts(wk_targets, program)

        first_day, last_day = w_idx * 7 + 1, min((w_idx + 1) * 7, duration)
        completed = sum(1 for d in completed_dates if in_week(d))
        workouts_target = min(weekly_workouts_target, last_day - first_day + 1)
        workout_pct = round(completed / max(1, workouts_target), 2)

        wk_waists = [m.waist_cm for m in measurements if in_week(m.date)]
        waist = wk_waists[-1] if wk_waists else None
        baseline_waist = start_waist if is_first else prev_waist
        waist_change = round(waist - baseline_waist, 1) if waist is not None and baseline_waist is not None else None

        strength_trend = _strength_trend(w_idx, strength_by_week.get(w_idx), strength_by_week.get(w_idx - 1))

        notes = [dl.recovery_notes for dl in wk_daily if dl.recovery_notes]
        if notes:
            energy_notes = notes[0]
        elif is_first:
            energy_notes = "Return-to-training week; focus on clean form and consistent logging."
        elif is_last:
            energy_notes = f"Final days; prepare Day {duration} measurements and photos."
        else:
            energy_notes = f"Week {w_idx + 1} progression; maintain consistency across sleep and training."

        personal_note = None
        if is_first:
            rule_triggered, action = 'Return-to-Training Phase', WEEK_ONE_ACTION
        elif is_last:
            if avg_weight is None:
                rule_triggered, action = '—', "Awaiting final days daily entries"
            else:
                rule_triggered = 'Final Review'
                action = f"Program Complete! Compare Day {duration} metrics, waist, and photos against Day 1 baseline."
        else:
            rule = _decide_rule(avg_weight, weight_change, waist_change, strength_trend)
            if rule is None:
                rule_triggered, action = '—', f"Awaiting Week {w_idx + 1} daily entries"
            else:
                rule_triggered, action = rule, RULE_TEXT[rule]
                personal_note = _personal_note(rule, target_kcal, avg_calories, avg_steps, avg_sleep,
                                               wk_targets.daily_steps, wk_targets.sleep_hours)

        rows.append({
            'week': f"Week {w_idx + 1}",
            'week_index': w_idx,
            'date_range': f"{w_start.strftime('%b %d')} – {w_end.strftime('%b %d')}",
            'avg_weight': avg_weight,
            'weight_change': weight_change,
            'avg_calories': avg_calories,
            'avg_protein': avg_protein,
            'calorie_target': target_kcal,
            'protein_target': wk_targets.protein_g,
            'steps_target': wk_targets.daily_steps,
            'sleep_target': wk_targets.sleep_hours,
            'avg_steps': avg_steps,
            'avg_sleep': avg_sleep,
            'cardio_minutes': cardio_minutes,
            'workout_pct': workout_pct,
            'workouts_completed': completed,
            'workouts_target': workouts_target,
            'week_start': w_start.isoformat(),
            'week_end': w_end.isoformat(),
            'waist': waist,
            'waist_change': waist_change,
            'strength_trend': strength_trend,
            'energy_notes': energy_notes,
            'action_recommendation': action,
            'rule_triggered': rule_triggered,
            'personal_note': personal_note,
            'is_current': w_start <= today <= w_end,
        })

        prev_avg_weight = avg_weight
        # Sheet: Week 1 waist falls back to the Day-1 baseline; later weeks don't carry forward.
        prev_waist = waist if waist is not None or not is_first else start_waist

    return rows
