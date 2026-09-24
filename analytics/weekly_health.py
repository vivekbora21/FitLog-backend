"""
One row of traffic-light metrics for "how is this week going", computed once
and shown unchanged on both the Dashboard and the Weekly Review page.

With an active program the window is the current program week and the numbers
come straight from that week's Weekly Review row, so the strip and the review
table can never disagree. Without one, the window is Monday → today and uses the
same averaging helper.

Thresholds follow the recovery pillar in pacing.py and use the member's own
targets: sleep at target / 1h under, steps at target / 75% of target. Volume
targets (workouts, cardio) are pro-rated by the days already finished — today is still in progress — so an untouched Monday isn't red.
"""
import math
from datetime import date, timedelta

from nutrition.targets import sleep_target_label
from workouts.models import WorkoutSession
from .weekly_review import load_window_logs, window_averages

GOOD, WARN, BAD, PENDING = 'good', 'warn', 'bad', 'pending'
STATUS_LABEL = {GOOD: 'On target', WARN: 'Slightly off', BAD: 'Off target', PENDING: 'Not logged'}

# Focus sentence picks the worst metric; ties broken by this order.
FOCUS_PRIORITY = ['workouts', 'protein', 'calories', 'steps', 'cardio', 'sleep']


def _paced_status(actual, target, days_elapsed, days_in_week, whole_units=False):
    if not target:
        return PENDING
    if actual >= target:
        return GOOD
    expected = target * (days_elapsed - 1) / days_in_week
    if whole_units:
        expected = math.floor(expected)
    if actual >= 0.9 * expected:
        return GOOD
    return WARN if actual >= 0.6 * expected else BAD


def _metric(key, label, actual, target, unit, status, focus):
    return {
        'key': key,
        'label': label,
        'actual': actual,
        'target': target,
        'unit': unit,
        'status': status,
        'status_label': STATUS_LABEL[status],
        'focus': focus,
    }


def _build_metrics(stats, targets, days_elapsed, days_in_week):
    workouts, workouts_target = stats['workouts_completed'], stats['workouts_target']
    cardio, cardio_target = stats['cardio_minutes'], targets['cardio_minutes']
    avg_cal, cal_target = stats['avg_calories'], targets['calories']
    avg_protein, protein_target = stats['avg_protein'], targets['protein_g']
    avg_steps, avg_sleep = stats['avg_steps'], stats['avg_sleep']
    steps_target, sleep_target = targets['steps'], targets['sleep_hours']

    workout_status = _paced_status(workouts, workouts_target, days_elapsed, days_in_week, whole_units=True)
    cardio_status = _paced_status(cardio, cardio_target, days_elapsed, days_in_week)

    if avg_protein is None or not protein_target:
        protein_status = PENDING
    else:
        ratio = avg_protein / protein_target
        protein_status = GOOD if ratio >= 0.9 else WARN if ratio >= 0.75 else BAD

    if avg_cal is None or not cal_target:
        cal_status = PENDING
    else:
        deviation = abs(avg_cal - cal_target) / cal_target
        cal_status = GOOD if deviation <= 0.1 else WARN if deviation <= 0.2 else BAD

    if avg_steps is None:
        steps_status = PENDING
    else:
        steps_status = GOOD if avg_steps >= steps_target else WARN if avg_steps >= steps_target * 0.75 else BAD

    if avg_sleep is None:
        sleep_status = PENDING
    else:
        sleep_status = GOOD if avg_sleep >= sleep_target else WARN if avg_sleep >= sleep_target - 1 else BAD

    cal_direction = 'over' if avg_cal is not None and cal_target and avg_cal > cal_target else 'under'
    return [
        _metric('workouts', 'Workouts', workouts, workouts_target, 'sessions', workout_status,
                f"get to {workouts_target} workouts — {workouts} done so far"),
        _metric('protein', 'Protein', avg_protein, protein_target, 'g', protein_status,
                f"protein — averaging {avg_protein}g against a {protein_target}g target"
                if avg_protein is not None else "protein"),
        _metric('calories', 'Calories', avg_cal, cal_target, 'kcal', cal_status,
                f"calories — averaging {avg_cal:,} kcal, {cal_direction} your {cal_target:,} kcal target"
                if avg_cal is not None and cal_target else "calories"),
        _metric('steps', 'Steps', avg_steps, steps_target, 'steps', steps_status,
                f"steps — averaging {avg_steps:,}/day, aim for {steps_target:,}+"
                if avg_steps is not None else "steps"),
        _metric('cardio', 'Cardio', cardio, cardio_target, 'min', cardio_status,
                f"cardio — {cardio} of {cardio_target} min done"),
        _metric('sleep', 'Sleep', avg_sleep, sleep_target, 'h', sleep_status,
                f"sleep — averaging {avg_sleep}h, aim for {sleep_target_label(sleep_target)}"
                if avg_sleep is not None else "sleep"),
    ]


def _focus_sentence(metrics):
    by_key = {m['key']: m for m in metrics}
    for status in (BAD, WARN):
        for key in FOCUS_PRIORITY:
            if by_key[key]['status'] == status:
                return f"Focus this week: {by_key[key]['focus']}."
    pending = [m['label'].lower() for m in metrics if m['status'] == PENDING]
    if pending:
        return f"Focus this week: keep everything on track and start logging {', '.join(pending)}."
    return "Focus this week: everything is on target — keep doing exactly this."


def build_weekly_health(user, weekly_review, weekly_workouts_target, cardio_target,
                        calories_target, protein_target, today, steps_target=8000, sleep_target=7.5):
    targets = {'cardio_minutes': cardio_target, 'calories': calories_target, 'protein_g': protein_target,
               'steps': steps_target, 'sleep_hours': sleep_target}
    current = next((row for row in weekly_review if row.get('is_current')), None)

    if current:
        w_start = date.fromisoformat(current['week_start'])
        days_in_week = (date.fromisoformat(current['week_end']) - w_start).days + 1
        stats = current
        window = {
            'source': 'program',
            'label': f"{current['week']} · {current['date_range']}",
            'start': current['week_start'],
            'end': current['week_end'],
        }
    else:
        w_start = today - timedelta(days=today.weekday())
        w_end = w_start + timedelta(days=6)
        days_in_week = 7
        stats = window_averages(load_window_logs(user, w_start, today), w_start, today)
        stats['workouts_completed'] = WorkoutSession.objects.filter(
            user=user, started_at__date__range=(w_start, today)
        ).count()
        stats['workouts_target'] = weekly_workouts_target
        window = {
            'source': 'calendar',
            'label': f"This week · {w_start.strftime('%b %d')} – {w_end.strftime('%b %d')}",
            'start': w_start.isoformat(),
            'end': w_end.isoformat(),
        }

    days_elapsed = min(days_in_week, (today - w_start).days + 1)
    metrics = _build_metrics(stats, targets, days_elapsed, days_in_week)
    window.update({'days_elapsed': days_elapsed, 'days_in_week': days_in_week})
    return {
        'window': window,
        'metrics': metrics,
        'focus': _focus_sentence(metrics),
    }
