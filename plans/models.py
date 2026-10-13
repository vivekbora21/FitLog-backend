from django.db import models
from core.models import UUIDTimeStampedModel
from workouts.models import JourneyProgram

DIFFICULTY_CHOICES = [
    ('BEGINNER', 'Beginner'),
    ('INTERMEDIATE', 'Intermediate'),
    ('ADVANCED', 'Advanced'),
]

class TrainingSplit(UUIDTimeStampedModel):
    """
    How weekly training volume is organized across days (bro split, push/pull/legs,
    upper/lower, full body, ...) - independent of a Blueprint's nutrition `mode`.
    Same day_1..day_7 workout_templates shape as Blueprint, so generate_roadmap()
    can source a day's exercises from either one interchangeably.
    """
    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    days_per_week = models.PositiveSmallIntegerField()
    workout_templates = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return self.name


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
    # Fallback workout content, used only when the request doesn't pick a TrainingSplit.
    workout_templates = models.JSONField(default=dict)
    meal_templates = models.JSONField(default=dict)
    default_training_split = models.ForeignKey(
        TrainingSplit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_for_blueprints',
    )
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['display_order', 'name']

    def __str__(self):
        return f"{self.name} ({self.mode})"
