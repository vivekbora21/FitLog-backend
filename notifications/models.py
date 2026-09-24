from django.db import models
from django.conf import settings
from core.models import UUIDTimeStampedModel

class Notification(UUIDTimeStampedModel):
    VERB_CHOICES = [
        ('WORKOUT_ASSIGNED', 'Workout Assigned'),
        ('WORKOUT_COMPLETED', 'Workout Completed'),
        ('FEEDBACK_POSTED', 'Trainer Feedback Posted'),
        ('INVITATION_RECEIVED', 'Gym Invitation Received'),
        ('INVITATION_ACCEPTED', 'Gym Invitation Accepted'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications_triggered'
    )
    gym = models.ForeignKey(
        'gyms.Gym',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    verb = models.CharField(max_length=30, choices=VERB_CHOICES)
    message = models.CharField(max_length=255)
    target_type = models.CharField(max_length=50, blank=True, default='')
    target_id = models.CharField(max_length=50, blank=True, default='')
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"To {self.recipient.email}: {self.message}"

class NotificationPreference(UUIDTimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    notify_on_workout_assigned = models.BooleanField(default=True)
    notify_on_feedback = models.BooleanField(default=True)
    notify_on_client_completion = models.BooleanField(default=True)

    def __str__(self):
        return f"Preferences for {self.user.email}"
