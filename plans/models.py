from django.db import models
from core.models import UUIDTimeStampedModel
from workouts.models import JourneyProgram

DIFFICULTY_CHOICES = [
    ('BEGINNER', 'Beginner'),
    ('INTERMEDIATE', 'Intermediate'),
    ('ADVANCED', 'Advanced'),
]

class Blueprint(UUIDTimeStampedModel):
    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=150)
    mode = models.CharField(max_length=20, choices=JourneyProgram.MODE_CHOICES)
    description = models.TextField(blank=True, default='')
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='INTERMEDIATE')
    default_duration_days = models.PositiveSmallIntegerField()
    default_days_per_week = models.PositiveSmallIntegerField()
    pacing_kg_per_week = models.FloatField(
        help_text='Signed: negative = weight loss per week, positive = gain, 0 for recomp/focus/habit'
    )
    phases = models.JSONField(default=list)
    workout_templates = models.JSONField(default=dict)
    meal_templates = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.mode})"
