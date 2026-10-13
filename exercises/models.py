from django.db import models
from core.models import UUIDTimeStampedModel

class MuscleGroup(UUIDTimeStampedModel):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)

    def __str__(self):
        return self.name

class EquipmentType(UUIDTimeStampedModel):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)

    def __str__(self):
        return self.name

class Exercise(UUIDTimeStampedModel):
    """
    Exercise model supporting both global catalog (gym=None)
    and gym-specific custom movements/equipment (gym=gym_id).
    """
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150)
    gym = models.ForeignKey(
        'gyms.Gym',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='custom_exercises'
    )
    # Set for a member's own custom movement; global catalog rows leave it empty.
    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='custom_exercises'
    )
    primary_muscle = models.ForeignKey(
        MuscleGroup,
        on_delete=models.PROTECT,
        related_name='primary_exercises'
    )
    secondary_muscles = models.ManyToManyField(
        MuscleGroup,
        blank=True,
        related_name='secondary_exercises'
    )
    equipment = models.ForeignKey(
        EquipmentType,
        on_delete=models.PROTECT,
        related_name='exercises'
    )
    # Additional equipment this exercise can also be performed with/on,
    # beyond the single required `equipment` above (e.g. a barbell bench
    # press that is also doable with dumbbells). Used by future
    # split-generation / equipment-availability logic (spec section 6);
    # additive and optional, so existing rows are unaffected.
    secondary_equipment = models.ManyToManyField(
        EquipmentType,
        blank=True,
        related_name='exercises_secondary'
    )
    # Ordered list of alternative exercises the generator can swap in when
    # this one is unavailable (e.g. wrong equipment level). See
    # `ExerciseSubstitute` below for the ordering field. Additive/optional;
    # existing rows start with no substitutes.
    substitutes = models.ManyToManyField(
        'self',
        through='ExerciseSubstitute',
        through_fields=('exercise', 'substitute'),
        symmetrical=False,
        related_name='substitute_for',
        blank=True,
    )
    instructions = models.TextField(blank=True, default='')
    video_url = models.URLField(max_length=500, blank=True, null=True)
    # Metabolic Equivalent of Task (Compendium of Physical Activities). Used to
    # estimate calories burned from a logged set/session duration.
    met_value = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['gym', 'slug'],
                name='unique_gym_exercise_slug'
            )
        ]

    def is_global(self):
        return self.gym is None and self.created_by_id is None

    def estimated_calories_burned(self, weight_kg, duration_minutes):
        """Calories = MET * weight (kg) * duration (hours). Returns None if
        no MET value is set for this exercise."""
        if self.met_value is None:
            return None
        return round(self.met_value * weight_kg * (duration_minutes / 60), 1)

    def __str__(self):
        prefix = f"[{self.gym.name}] " if self.gym else ""
        return f"{prefix}{self.name} ({self.primary_muscle.name})"


class ExerciseSubstitute(UUIDTimeStampedModel):
    """Ordered substitute mapping: `substitute` is an acceptable swap for
    `exercise`, in preference order (lowest `order` first). Purely additive
    content; no existing code reads or writes this table yet (it is laid
    down now for the section 6 split/exercise-selection work, out of scope
    for this pass)."""
    exercise = models.ForeignKey(
        Exercise, on_delete=models.CASCADE, related_name='substitute_links'
    )
    substitute = models.ForeignKey(
        Exercise, on_delete=models.CASCADE, related_name='substitute_of_links'
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order']
        constraints = [
            models.UniqueConstraint(
                fields=['exercise', 'substitute'], name='unique_exercise_substitute'
            ),
            models.CheckConstraint(
                check=~models.Q(exercise=models.F('substitute')),
                name='exercise_substitute_not_self'
            ),
        ]

    def __str__(self):
        return f"{self.exercise.name} -> {self.substitute.name} (#{self.order})"
