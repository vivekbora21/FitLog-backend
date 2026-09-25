"""
Personal records derived from logged sets.

Creating a session only ever raises a PR, but editing or deleting one can lower it,
so those paths rebuild the affected exercises' records from the remaining history.
"""
from .models import PersonalRecord


def recompute_personal_records(user, exercise_ids):
    from workouts.models import WorkoutSet

    for exercise_id in set(exercise_ids):
        sets = (
            WorkoutSet.objects
            .filter(
                workout_exercise__session__user=user,
                workout_exercise__exercise_id=exercise_id,
                completed=True,
                weight_kg__gt=0,
                reps__gt=0,
            )
            .select_related('workout_exercise__session')
        )
        best = None
        best_1rm = 0.0
        for s in sets:
            est = PersonalRecord.calculate_epley_1rm(s.weight_kg, s.reps)
            if est > best_1rm:
                best, best_1rm = s, est

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
            },
        )
