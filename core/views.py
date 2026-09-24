from rest_framework import viewsets, permissions
from .models import AuditLog
from .serializers import AuditLogSerializer
from memberships.models import GymMembership

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        gym_id = self.request.query_params.get('gym_id')
        user = self.request.user

        if gym_id:
            # Only owners and trainers of the gym can see its audit trail
            is_staff = GymMembership.objects.filter(
                user=user,
                gym_id=gym_id,
                role__in=['OWNER', 'TRAINER'],
                status='ACTIVE'
            ).exists()
            if is_staff:
                return AuditLog.objects.filter(gym_id=gym_id).order_by('-created_at')
        return AuditLog.objects.none()
