"""
Double-progression engine shared by every surface that shows a prescribed load.

The Plan page and the Active Workout logger both read `RoutineExercise.progression`
from the API, so the number a member plans with is the number they log with.

Rule: hold the load until every prescribed working set reaches the top of the rep
range at (or under) the target RPE, then add one increment next session.
"""
import re

from .models import WorkoutExercise

WORKING_SET_TYPES = ('NORMAL', 'FAILURE')
RPE_TOLERANCE = 0.5
SESSIONS_SCANNED = 5


def parse_rep_range(target_reps):
    """'6-8' -> (6, 8); '10' -> (10, 10); anything unparseable -> (None, None)."""
    numbers = [int(n) for n in re.findall(r'\d+', target_reps or '')]
    if not numbers:
        return None, None
    return numbers[0], numbers[1] if len(numbers) > 1 else numbers[0]


def load_increment(weight_kg):
    # Light isolation / dumbbell loads can't absorb a full plate jump.
    return 2.5 if weight_kg >= 20 else 1.25


def _round_load(weight_kg):
    return round(round(weight_kg / 0.25) * 0.25, 2)


def last_working_sets(user, exercise_id):
    """Completed working sets from the most recent session that logged this exercise."""
    recent = (
        WorkoutExercise.objects
        .filter(session__user=user, exercise_id=exercise_id)
        .select_related('session')
        .prefetch_related('sets')
        .order_by('-session__started_at')[:SESSIONS_SCANNED]
    )
    for workout_exercise in recent:
        sets = [
            s for s in workout_exercise.sets.all()
            if s.completed and s.set_type in WORKING_SET_TYPES and s.weight_kg > 0 and s.reps > 0
        ]
        if sets:
            return workout_exercise.session, sets
    return None, []


def recommend(routine_exercise, session, sets):
    """Build the next-session prescription for one routine exercise."""
    target_sets = max(1, routine_exercise.target_sets)
    target_rpe = routine_exercise.target_rpe
    rep_label = routine_exercise.target_reps or 'the prescribed rep range'
    rpe_label = target_rpe or 8
    _, top_reps = parse_rep_range(routine_exercise.target_reps)

    if not sets:
        return {
            'action': 'START',
            'recommended_weight_kg': routine_exercise.suggested_weight_kg,
            'target_reps': [top_reps] * target_sets if top_reps else [],
            'note': f"First logged session: work up to {rep_label} at RPE {rpe_label} and record every working set.",
            'last_session': None,
        }

    working_weight = max(s.weight_kg for s in sets)
    top_sets = [s for s in sets if s.weight_kg == working_weight]
    last_session = {
        'date': session.started_at.date().isoformat(),
        'weight_kg': working_weight,
        'reps': [s.reps for s in top_sets],
    }

    hit_top = (
        top_reps is not None
        and len(top_sets) >= target_sets
        and all(s.reps >= top_reps for s in top_sets)
        and all(s.rpe is None or target_rpe is None or s.rpe <= target_rpe + RPE_TOLERANCE for s in top_sets)
    )
    if hit_top:
        increment = load_increment(working_weight)
        next_weight = _round_load(working_weight + increment)
        return {
            'action': 'INCREASE',
            'recommended_weight_kg': next_weight,
            'target_reps': [top_reps] * target_sets,
            'note': f"Every set reached {top_reps} at the intended effort last time — add {increment:g} kg to {next_weight:g} kg.",
            'last_session': last_session,
        }

    # Hold the load; nudge each set one rep toward the top of the range.
    padded = [s.reps for s in top_sets][:target_sets]
    padded += [padded[-1]] * (target_sets - len(padded))
    next_reps = [min(top_reps, r + 1) if top_reps else r + 1 for r in padded]
    reason = f"increase only once all {target_sets} sets reach {top_reps}" if top_reps else "add reps before adding load"
    return {
        'action': 'HOLD',
        'recommended_weight_kg': working_weight,
        'target_reps': next_reps,
        'note': f"Keep {working_weight:g} kg and aim for {' / '.join(map(str, next_reps))}; {reason}.",
        'last_session': last_session,
    }


def progression_for(user, routine_exercise, cache=None):
    """Recommendation for `user`, memoising history lookups per exercise in `cache`."""
    if cache is None:
        cache = {}
    key = routine_exercise.exercise_id
    if key not in cache:
        cache[key] = last_working_sets(user, key)
    session, sets = cache[key]
    return recommend(routine_exercise, session, sets)
