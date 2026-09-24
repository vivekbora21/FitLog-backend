import uuid
from django.db import models
from django.conf import settings

class UUIDTimeStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('WORKOUT_ASSIGNED', 'Workout Assigned'),
        ('WORKOUT_UPDATED', 'Workout Updated'),
        ('WORKOUT_COMPLETED', 'Workout Completed'),
        ('TRAINER_ASSIGNED', 'Trainer Assigned'),
        ('TRAINER_REMOVED', 'Trainer Removed'),
        ('MEMBER_INVITED', 'Member Invited'),
        ('MEMBER_ACCEPTED', 'Member Accepted Invitation'),
        ('MEMBER_SUSPENDED', 'Member Suspended'),
        ('FEEDBACK_POSTED', 'Trainer Feedback Posted'),
        ('PROGRESS_SHARED', 'Progress Shared'),
        ('PROGRESS_UNSHARED', 'Progress Unshared'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_actions'
    )
    gym = models.ForeignKey(
        'gyms.Gym',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    resource_type = models.CharField(max_length=60)
    resource_id = models.CharField(max_length=60)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['gym', 'action']),
            models.Index(fields=['actor', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.action}] {self.resource_type}:{self.resource_id} by {self.actor}"
