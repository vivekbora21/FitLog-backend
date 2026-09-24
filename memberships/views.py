from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import models
from django.shortcuts import get_object_or_404
from .models import GymMembership, TrainerClientAssignment, GymInvitation
from .serializers import GymMembershipSerializer, TrainerClientAssignmentSerializer, GymInvitationSerializer
from core.models import AuditLog
from core.permissions import IsGymOwner, IsTrainer
from notifications.models import Notification

class GymMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = GymMembershipSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        gym_id = self.request.query_params.get('gym_id')
        user = self.request.user

        if gym_id:
            # Check if user is owner/trainer of this gym
            is_staff = GymMembership.objects.filter(
                user=user,
                gym_id=gym_id,
                role__in=['OWNER', 'TRAINER'],
                status='ACTIVE'
            ).exists()

            if is_staff:
                return GymMembership.objects.filter(gym_id=gym_id).select_related('user', 'gym')
            # Members can only view their own membership
            return GymMembership.objects.filter(gym_id=gym_id, user=user).select_related('user', 'gym')

        # List all memberships of the authenticated user
        return GymMembership.objects.filter(user=user).select_related('user', 'gym')

class TrainerClientViewSet(viewsets.ModelViewSet):
    serializer_class = TrainerClientAssignmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        gym_id = self.request.query_params.get('gym_id')
        qs = TrainerClientAssignment.objects.filter(is_active=True).select_related(
            'trainer_membership__user', 'client_membership__user'
        )

        if gym_id:
            qs = qs.filter(trainer_membership__gym_id=gym_id)

        # Trainers see their assigned clients
        # Members see their assigned trainer
        # Gym owners see all assignments in their gym
        is_owner = GymMembership.objects.filter(user=user, role='OWNER', status='ACTIVE').exists()
        if is_owner:
            return qs
        return qs.filter(
            models.Q(trainer_membership__user=user) | models.Q(client_membership__user=user)
        )

    def perform_create(self, serializer):
        assignment = serializer.save()
        AuditLog.objects.create(
            actor=self.request.user,
            gym=assignment.trainer_membership.gym,
            action='TRAINER_ASSIGNED',
            resource_type='TrainerClientAssignment',
            resource_id=str(assignment.id),
            details={
                'trainer': assignment.trainer_membership.user.email,
                'client': assignment.client_membership.user.email,
            }
        )

class GymInvitationViewSet(viewsets.ModelViewSet):
    serializer_class = GymInvitationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        gym_id = self.request.query_params.get('gym_id')
        user = self.request.user

        if gym_id:
            # Check owner or trainer
            is_authorized = GymMembership.objects.filter(
                user=user,
                gym_id=gym_id,
                role__in=['OWNER', 'TRAINER'],
                status='ACTIVE'
            ).exists()
            if is_authorized:
                return GymInvitation.objects.filter(gym_id=gym_id).select_related('gym', 'invited_by')
        return GymInvitation.objects.none()

    def perform_create(self, serializer):
        invitation = serializer.save(invited_by=self.request.user)
        AuditLog.objects.create(
            actor=self.request.user,
            gym=invitation.gym,
            action='MEMBER_INVITED',
            resource_type='GymInvitation',
            resource_id=str(invitation.id),
            details={
                'email': invitation.email,
                'role': invitation.role,
                'token': str(invitation.token)
            }
        )

class AcceptInvitationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, token):
        invitation = get_object_or_404(GymInvitation, token=token)
        if not invitation.is_valid():
            return Response({'error': 'Invitation is invalid or has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        # Create or activate membership
        membership, created = GymMembership.objects.get_or_create(
            gym=invitation.gym,
            user=request.user,
            defaults={'role': invitation.role, 'status': 'ACTIVE'}
        )

        if not created and membership.status != 'ACTIVE':
            membership.status = 'ACTIVE'
            membership.role = invitation.role
            membership.save()

        invitation.status = 'ACCEPTED'
        invitation.save()

        AuditLog.objects.create(
            actor=request.user,
            gym=invitation.gym,
            action='MEMBER_ACCEPTED',
            resource_type='GymMembership',
            resource_id=str(membership.id),
            details={'email': request.user.email, 'role': invitation.role}
        )

        Notification.objects.create(
            recipient=invitation.invited_by,
            actor=request.user,
            gym=invitation.gym,
            verb='INVITATION_ACCEPTED',
            message=f"{request.user.get_full_name() or request.user.email} accepted invitation to join as {invitation.role}."
        )

        return Response(GymMembershipSerializer(membership).data, status=status.HTTP_200_OK)
