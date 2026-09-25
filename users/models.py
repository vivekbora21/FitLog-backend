from django.contrib.auth.models import AbstractUser
from django.db import models
from core.models import UUIDTimeStampedModel

class User(AbstractUser):
    """
    Pure global identity model.
    Gym-specific roles (Owner, Trainer, Member) belong strictly to GymMembership.
    """
    email = models.EmailField(unique=True)
    avatar_url = models.URLField(max_length=500, blank=True, null=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    def __str__(self):
        full_name = self.get_full_name()
        return full_name if full_name else self.email

class UserProfile(UUIDTimeStampedModel):
    GOAL_CHOICES = [
        ('STRENGTH', 'Strength & Power'),
        ('HYPERTROPHY', 'Muscle Hypertrophy'),
        ('FAT_LOSS', 'Fat Loss & Conditioning'),
        ('ENDURANCE', 'Endurance & Cardio'),
        ('GENERAL_FITNESS', 'General Health & Fitness'),
    ]

    SEX_CHOICES = [
        ('MALE', 'Male'),
        ('FEMALE', 'Female'),
    ]

    # Multipliers applied to BMR to estimate TDEE (see nutrition/targets.py).
    ACTIVITY_CHOICES = [
        ('SEDENTARY', 'Sedentary (desk job, little exercise)'),
        ('LIGHT', 'Light (1–3 sessions / week)'),
        ('MODERATE', 'Moderate (3–5 sessions / week)'),
        ('HIGH', 'High (6–7 sessions / week)'),
        ('ATHLETE', 'Athlete (twice-daily or physical job)'),
    ]

    UNIT_CHOICES = [
        ('METRIC', 'Metric (kg / cm)'),
        ('IMPERIAL', 'Imperial (lbs / inches)'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    date_of_birth = models.DateField(null=True, blank=True)
    height_cm = models.FloatField(null=True, blank=True)
    weight_kg = models.FloatField(null=True, blank=True)
    sex = models.CharField(max_length=10, choices=SEX_CHOICES, blank=True, default='')
    activity_level = models.CharField(max_length=15, choices=ACTIVITY_CHOICES, default='MODERATE')
    fitness_goal = models.CharField(max_length=30, choices=GOAL_CHOICES, default='HYPERTROPHY')
    unit_preference = models.CharField(max_length=15, choices=UNIT_CHOICES, default='METRIC')
    bio = models.TextField(blank=True, default='')

    def __str__(self):
        return f"Profile of {self.user.email}"


class PasswordResetCode(UUIDTimeStampedModel):
    """
    A short-lived 6-digit code emailed for resetting a password from the app,
    where a long link token would have to be copied between apps.
    Only a hash of the code is stored.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_codes')
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)

    MAX_ATTEMPTS = 5

    class Meta:
        ordering = ['-created_at']
