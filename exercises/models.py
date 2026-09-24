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
    instructions = models.TextField(blank=True, default='')
    video_url = models.URLField(max_length=500, blank=True, null=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['gym', 'slug'],
                name='unique_gym_exercise_slug'
            )
        ]

    def is_global(self):
        return self.gym is None

    def __str__(self):
        prefix = f"[{self.gym.name}] " if self.gym else ""
        return f"{prefix}{self.name} ({self.primary_muscle.name})"
