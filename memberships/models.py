import uuid
from datetime import timedelta
from django.utils import timezone
from django.db import models
from django.conf import settings
from core.models import UUIDTimeStampedModel

class GymMembership(UUIDTimeStampedModel):
    ROLE_CHOICES = [
        ('OWNER', 'Gym Owner'),
        ('TRAINER', 'Trainer / Coach'),
        ('MEMBER', 'Gym Member'),
    ]

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('SUSPENDED', 'Suspended'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    gym = models.ForeignKey(
        'gyms.Gym',
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='MEMBER')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')

    # Granular privacy controls for member-owned data
    share_workouts_with_trainers = models.BooleanField(default=True)
    share_progress_with_trainers = models.BooleanField(default=True)
    share_nutrition_with_trainers = models.BooleanField(default=True)
    share_body_measurements = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Ensure only one active OWNER per gym
            models.UniqueConstraint(
                fields=['gym', 'role'],
                condition=models.Q(role='OWNER', status='ACTIVE'),
                name='unique_active_gym_owner'
            ),
            # Single membership per user per gym
            models.UniqueConstraint(
                fields=['gym', 'user'],
                name='unique_user_gym_membership'
            ),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.role} @ {self.gym.name} ({self.status})"

class TrainerClientAssignment(UUIDTimeStampedModel):
    trainer_membership = models.ForeignKey(
        GymMembership,
        on_delete=models.CASCADE,
        related_name='client_assignments'
    )
    client_membership = models.ForeignKey(
        GymMembership,
        on_delete=models.CASCADE,
        related_name='trainer_assignments'
    )
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Prevent duplicate active trainer-client relationships
            models.UniqueConstraint(
                fields=['trainer_membership', 'client_membership'],
                condition=models.Q(is_active=True),
                name='unique_active_trainer_client'
            ),
        ]

    def __str__(self):
        return f"Coach {self.trainer_membership.user.get_full_name() or self.trainer_membership.user.email} -> {self.client_membership.user.get_full_name() or self.client_membership.user.email}"

class GymInvitation(UUIDTimeStampedModel):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('ACCEPTED', 'Accepted'),
        ('EXPIRED', 'Expired'),
        ('REVOKED', 'Revoked'),
    ]

    gym = models.ForeignKey(
        'gyms.Gym',
        on_delete=models.CASCADE,
        related_name='invitations'
    )
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=GymMembership.ROLE_CHOICES, default='MEMBER')
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_invitations'
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            # Prevent duplicate pending invitations for same gym/email/role
            models.UniqueConstraint(
                fields=['gym', 'email', 'role'],
                condition=models.Q(status='PENDING'),
                name='unique_pending_invitation'
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    def is_valid(self):
        return self.status == 'PENDING' and self.expires_at > timezone.now()

    def __str__(self):
        return f"Invite {self.email} as {self.role} to {self.gym.name} ({self.status})"
