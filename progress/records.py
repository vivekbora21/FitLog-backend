"""
Personal records derived from logged sets.

Creating a session only ever raises a PR, but editing or deleting one can lower it,
so those paths rebuild the affected exercises' records from the remaining history.

A record only counts as a genuine PR — eligible for celebration and for the
"Personal Records" achievement tiers — once it has actually been beaten at
least once after its first (baseline) logging. Two guards keep that beat
meaningful rather than trivially easy:
  - MAX_PR_REPS: Epley's 1RM formula gets unreliable at high rep counts, so a
    single light set done for dozens of reps can't inflate an estimate past a
    real heavy single/double/triple.
  - MIN_PR_WEIGHT_RATIO: a "beat" must use at least this fraction of the
    previous best's weight, so stacking reps at a much lighter weight can't
    out-math a genuine strength gain.
"""
from .models import PersonalRecord

MAX_PR_REPS = 12
MIN_PR_WEIGHT_RATIO = 0.5


def recompute_personal_records(user, exercise_ids):
    from workouts.models import WorkoutSet
    from workouts.progression import WORKING_SET_TYPES

    for exercise_id in set(exercise_ids):
        sets = (
            WorkoutSet.objects
            .filter(
                workout_exercise__session__user=user,
                workout_exercise__exercise_id=exercise_id,
                completed=True,
                weight_kg__gt=0,
                reps__gt=0,
                reps__lte=MAX_PR_REPS,
                set_type__in=WORKING_SET_TYPES,
            )
            .select_related('workout_exercise__session')
            .order_by('workout_exercise__session__started_at')
        )

        best = None
        best_1rm = 0.0
        improvement_count = 0
        for s in sets:
            est = PersonalRecord.calculate_epley_1rm(s.weight_kg, s.reps)
            if best is None:
                best, best_1rm = s, est
                continue
            if est > best_1rm and s.weight_kg >= best.weight_kg * MIN_PR_WEIGHT_RATIO:
                best, best_1rm = s, est
                improvement_count += 1

        if best is None:
            PersonalRecord.objects.filter(user=user, exercise_id=exercise_id).delete()
            continue

        PersonalRecord.objects.update_or_create(
            user=user,
            exercise_id=exercise_id,
            defaults={
                'max_weight_kg': best.weight_kg,
                'reps': best.reps,
                'estimated_one_rep_max': best_1rm,
                'achieved_at': best.workout_exercise.session.started_at.date(),
                'is_improved': improvement_count > 0,
                'improvement_count': improvement_count,
            },
        )


def compute_pr_trend(user, exercise_id):
    """Running best estimated-1RM for one exercise over time, derived from logged sets
    (PersonalRecord only stores the current best, not its history). Shared by the
    mobile/web "strength progression" chart endpoint and the data export PDF."""
    from workouts.models import WorkoutSet
    from workouts.progression import WORKING_SET_TYPES

    sets = (
        WorkoutSet.objects
        .filter(
            workout_exercise__session__user=user,
            workout_exercise__exercise_id=exercise_id,
            completed=True,
            weight_kg__gt=0,
            reps__gt=0,
            reps__lte=MAX_PR_REPS,
            set_type__in=WORKING_SET_TYPES,
        )
        .select_related('workout_exercise__session')
        .order_by('workout_exercise__session__started_at')
    )

    best_weight = None
    best_1rm = 0.0
    by_date = {}
    for s in sets:
        est = PersonalRecord.calculate_epley_1rm(s.weight_kg, s.reps)
        if best_weight is None or (est > best_1rm and s.weight_kg >= best_weight * MIN_PR_WEIGHT_RATIO):
            best_weight, best_1rm = s.weight_kg, est
        date_key = s.workout_exercise.session.started_at.date().isoformat()
        # Keep the latest (highest, since best_1rm only grows) running-best for each date.
        by_date[date_key] = {
            'date': date_key,
            'estimated_one_rep_max': round(best_1rm, 1),
            'weight_kg': best_weight,
        }
    return sorted(by_date.values(), key=lambda row: row['date'])
