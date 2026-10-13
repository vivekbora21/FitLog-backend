"""Thin DB-touching helper used by `views.py` to resolve exercise name ->
muscle-group name before calling `plan_generator.generate_roadmap`'s volume
check (spec v1.6 section 6.4).

Deliberately kept out of `plan_generator.py`, whose own module docstring
says it is pure ("no database access here at all"); this is the one place
that bridges the exercise catalog (`exercises.models.Exercise`) into that
otherwise-pure roadmap-building code, exactly the same way `views.py`
already fetches the `Blueprint`/`TrainingSplit` ORM objects and passes plain
data into `generate_roadmap`.
"""
from exercises.models import Exercise


def muscle_group_by_exercise_name(exercise_names):
    """Returns {exercise_name: muscle_group_name} for every name in
    `exercise_names` found in the global catalog (gym=None). Names not
    found are simply absent from the result -- callers treat an unresolved
    exercise as contributing no muscle-group volume rather than erroring,
    since a generator content/catalog gap is a product decision (6.7), not
    a crash here.
    """
    if not exercise_names:
        return {}
    rows = Exercise.objects.filter(
        gym__isnull=True, name__in=list(exercise_names)
    ).values_list('name', 'primary_muscle__name')
    return dict(rows)
