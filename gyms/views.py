from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from django.utils.text import slugify
from .models import Gym
from .serializers import GymSerializer
from memberships.models import GymMembership
from core.models import AuditLog

class GymViewSet(viewsets.ModelViewSet):
    serializer_class = GymSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Return gyms where the user has an active membership
        return Gym.objects.filter(
            memberships__user=self.request.user,
            memberships__status='ACTIVE'
        ).distinct()

    def perform_create(self, serializer):
        name = serializer.validated_data.get('name')
        slug = slugify(name)
        base_slug = slug
        counter = 1
        while Gym.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        gym = serializer.save(slug=slug)

        # Creator automatically becomes ACTIVE OWNER
        GymMembership.objects.create(
            user=self.request.user,
            gym=gym,
            role='OWNER',
            status='ACTIVE'
        )

        AuditLog.objects.create(
            actor=self.request.user,
            gym=gym,
            action='MEMBER_ACCEPTED',
            resource_type='Gym',
            resource_id=str(gym.id),
            details={'message': f"Gym '{gym.name}' created by owner {self.request.user.email}"}
        )
