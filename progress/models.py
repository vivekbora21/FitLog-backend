from django.db import models
from django.conf import settings
from core.models import UUIDTimeStampedModel

class WeightEntry(UUIDTimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='weight_entries'
    )
    date = models.DateField()
    weight_kg = models.FloatField()
    body_fat_pct = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-date']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'date'],
                name='unique_user_weight_date'
            )
        ]

    def __str__(self):
        return f"{self.user.email} - {self.date}: {self.weight_kg}kg"

class BodyMeasurement(UUIDTimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='body_measurements'
    )
    date = models.DateField()
    # Torso & Core
    neck_cm = models.FloatField(null=True, blank=True)
    shoulders_cm = models.FloatField(null=True, blank=True)
    chest_cm = models.FloatField(null=True, blank=True)
    waist_cm = models.FloatField(null=True, blank=True)
    hips_cm = models.FloatField(null=True, blank=True)

    # Arms
    arms_cm = models.FloatField(null=True, blank=True)
    biceps_left_cm = models.FloatField(null=True, blank=True)
    biceps_right_cm = models.FloatField(null=True, blank=True)
    forearms_cm = models.FloatField(null=True, blank=True)

    # Legs
    thighs_cm = models.FloatField(null=True, blank=True)
    thigh_left_cm = models.FloatField(null=True, blank=True)
    thigh_right_cm = models.FloatField(null=True, blank=True)
    calves_cm = models.FloatField(null=True, blank=True)
    calf_left_cm = models.FloatField(null=True, blank=True)
    calf_right_cm = models.FloatField(null=True, blank=True)

    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"Measurements {self.user.email} on {self.date}"

class PersonalRecord(UUIDTimeStampedModel):
    """
    Tracks all-time personal bests and calculated 1RM for exercises.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='personal_records'
    )
    exercise = models.ForeignKey(
        'exercises.Exercise',
        on_delete=models.CASCADE,
        related_name='prs'
    )
    max_weight_kg = models.FloatField()
    reps = models.PositiveIntegerField(default=1)
    estimated_one_rep_max = models.FloatField()
    achieved_at = models.DateField()

    class Meta:
        ordering = ['-estimated_one_rep_max']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'exercise'],
                name='unique_user_exercise_pr'
            )
        ]

    @staticmethod
    def calculate_epley_1rm(weight: float, reps: int) -> float:
        """Epley 1RM formula: weight * (1 + reps / 30)"""
        if reps <= 1:
            return round(weight, 1)
        return round(weight * (1 + (reps / 30.0)), 1)

    def __str__(self):
        return f"PR: {self.exercise.name} - {self.max_weight_kg}kg x {self.reps} (1RM: {self.estimated_one_rep_max}kg)"


class DailyLog(UUIDTimeStampedModel):
    """
    Daily lifestyle, recovery, and NEAT activity log.
    Captures steps (Pillar 9 target: 8,000–10,000), sleep duration (Pillar 7 target: 7.5–8.5h),
    energy/recovery score, and subjective fatigue notes.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='daily_logs'
    )
    date = models.DateField()
    steps = models.PositiveIntegerField(null=True, blank=True, help_text="Daily step count")
    sleep_hours = models.FloatField(null=True, blank=True, help_text="Sleep duration in hours")
    sleep_quality = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Subjective sleep quality 1-5")
    energy_level = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Subjective energy rating 1-5")
    recovery_notes = models.TextField(blank=True, default='', help_text="Subjective recovery and fatigue notes")
    day_status = models.CharField(
        max_length=20,
        blank=True,
        default='',
        choices=[
            ('COMPLETED', 'Completed'),
            ('REST', 'Rest Day'),
            ('SKIPPED', 'Skipped'),
        ],
        help_text="Optional manual status: REST, SKIPPED, COMPLETED"
    )

    class Meta:
        ordering = ['-date']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'date'],
                name='unique_user_daily_log'
            )
        ]

    def __str__(self):
        return f"DailyLog {self.user.email} on {self.date}: {self.steps or 0} steps, {self.sleep_hours or 0}h sleep"

