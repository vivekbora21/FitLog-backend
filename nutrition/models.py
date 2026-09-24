from datetime import date

from django.db import models
from django.conf import settings
from core.models import UUIDTimeStampedModel
from .defaults import DEFAULT_MACRO_TARGETS, DEFAULT_LIFESTYLE_TARGETS


class TargetValues(models.Model):
    """The member's daily/weekly targets. Shared by the live row and its history."""
    daily_calories = models.PositiveIntegerField(default=DEFAULT_MACRO_TARGETS['daily_calories'])
    protein_g = models.PositiveIntegerField(default=DEFAULT_MACRO_TARGETS['protein_g'])
    carbs_g = models.PositiveIntegerField(default=DEFAULT_MACRO_TARGETS['carbs_g'])
    fat_g = models.PositiveIntegerField(default=DEFAULT_MACRO_TARGETS['fat_g'])
    water_ml = models.PositiveIntegerField(default=DEFAULT_MACRO_TARGETS['water_ml'])
    daily_steps = models.PositiveIntegerField(default=DEFAULT_LIFESTYLE_TARGETS['daily_steps'])
    sleep_hours = models.FloatField(default=DEFAULT_LIFESTYLE_TARGETS['sleep_hours'])
    # Null means "follow the active plan" (its scheduled days / cardio phase).
    weekly_workouts = models.PositiveSmallIntegerField(null=True, blank=True)
    weekly_cardio_minutes = models.PositiveSmallIntegerField(null=True, blank=True)

    FIELDS = (
        'daily_calories', 'protein_g', 'carbs_g', 'fat_g', 'water_ml',
        'daily_steps', 'sleep_hours', 'weekly_workouts', 'weekly_cardio_minutes',
    )

    class Meta:
        abstract = True

    def values(self):
        return {f: getattr(self, f) for f in self.FIELDS}


class MacroTarget(UUIDTimeStampedModel, TargetValues):
    """The member's current targets. Every save is also recorded in TargetHistory."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='macro_target'
    )

    def __str__(self):
        return f"Targets for {self.user.email}: {self.daily_calories} kcal"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        TargetHistory.record(self.user, self.values())


class TargetHistory(UUIDTimeStampedModel, TargetValues):
    """
    Targets as they stood from `effective_from` until the next row. Past days are
    judged against the target that applied on that day, so changing a target
    today never rewrites last month's adherence.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='target_history')
    effective_from = models.DateField()

    class Meta:
        ordering = ['effective_from']
        constraints = [models.UniqueConstraint(fields=['user', 'effective_from'], name='unique_target_history_day')]

    @classmethod
    def record(cls, user, values, day=None):
        day = day or date.today()
        latest = cls.objects.filter(user=user, effective_from__lte=day).order_by('-effective_from').first()
        if latest and latest.values() == values:
            return latest
        row, _ = cls.objects.update_or_create(user=user, effective_from=day, defaults=values)
        return row


class NutritionDay(UUIDTimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='nutrition_days'
    )
    date = models.DateField()
    water_consumed_ml = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-date']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'date'],
                name='unique_user_nutrition_day'
            )
        ]

    def total_calories(self):
        return sum(m.calories for m in self.meals.all())

    def total_protein(self):
        return round(sum(m.protein_g for m in self.meals.all()), 1)

    def total_carbs(self):
        return round(sum(m.carbs_g for m in self.meals.all()), 1)

    def total_fat(self):
        return round(sum(m.fat_g for m in self.meals.all()), 1)

    def __str__(self):
        return f"{self.user.email} - {self.date}"

class Food(UUIDTimeStampedModel):
    """
    A reusable food with macros for one serving. owner=None means a shared catalog
    item (seeded from the Diet Plan sheet); otherwise it's a user's own saved food.
    """
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='foods'
    )
    name = models.CharField(max_length=150)
    serving_label = models.CharField(max_length=150, help_text="What one serving is, e.g. '40g dry weighed'")
    serving_grams = models.FloatField(null=True, blank=True, help_text="Weight of one serving, if it is weighed")
    calories = models.PositiveIntegerField()
    protein_g = models.FloatField(default=0.0)
    carbs_g = models.FloatField(default=0.0)
    fat_g = models.FloatField(default=0.0)

    class Meta:
        ordering = ['name']

    def macros_for(self, servings):
        return {
            'calories': round(self.calories * servings),
            'protein_g': round(self.protein_g * servings, 1),
            'carbs_g': round(self.carbs_g * servings, 1),
            'fat_g': round(self.fat_g * servings, 1),
        }

    def __str__(self):
        return f"{self.name} ({self.serving_label}, {self.calories} kcal)"

class MealEntry(UUIDTimeStampedModel):
    MEAL_TYPES = [
        ('BREAKFAST', 'Breakfast'),
        ('LUNCH', 'Lunch'),
        ('DINNER', 'Dinner'),
        ('SNACK', 'Snack / Pre-Workout'),
    ]

    nutrition_day = models.ForeignKey(NutritionDay, on_delete=models.CASCADE, related_name='meals')
    meal_type = models.CharField(max_length=20, choices=MEAL_TYPES, default='BREAKFAST')
    name = models.CharField(max_length=150)
    # When food is set, the macro fields below are computed from food x servings
    # at log time (a snapshot, so later edits to the food don't rewrite history).
    food = models.ForeignKey(Food, on_delete=models.SET_NULL, null=True, blank=True, related_name='entries')
    servings = models.FloatField(default=1.0)
    calories = models.PositiveIntegerField()
    protein_g = models.FloatField(default=0.0)
    carbs_g = models.FloatField(default=0.0)
    fat_g = models.FloatField(default=0.0)
    time_logged = models.TimeField(auto_now_add=True)

    class Meta:
        ordering = ['time_logged']

    @property
    def quantity(self):
        return self.servings

    @quantity.setter
    def quantity(self, value):
        self.servings = value

    def __str__(self):
        return f"[{self.meal_type}] {self.name} ({self.calories} kcal)"
