from rest_framework import permissions
from memberships.models import GymMembership, TrainerClientAssignment

class HasActiveMembership(permissions.BasePermission):
    """
    Ensures request.user has an active membership in the specified gym.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        gym_id = view.kwargs.get('gym_id') or request.query_params.get('gym_id') or request.data.get('gym')
        if not gym_id:
            return True
        return GymMembership.objects.filter(
            user=request.user,
            gym_id=gym_id,
            status='ACTIVE'
        ).exists()

class IsGymOwner(permissions.BasePermission):
    """
    Ensures request.user is an ACTIVE OWNER of the specified gym.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        gym_id = view.kwargs.get('gym_id') or request.query_params.get('gym_id') or request.data.get('gym')
        if not gym_id:
            return GymMembership.objects.filter(user=request.user, role='OWNER', status='ACTIVE').exists()
        return GymMembership.objects.filter(
            user=request.user,
            gym_id=gym_id,
            role='OWNER',
            status='ACTIVE'
        ).exists()

class IsTrainer(permissions.BasePermission):
    """
    Ensures request.user is an ACTIVE TRAINER or OWNER in the gym.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        gym_id = view.kwargs.get('gym_id') or request.query_params.get('gym_id') or request.data.get('gym')
        if not gym_id:
            return GymMembership.objects.filter(user=request.user, role__in=['TRAINER', 'OWNER'], status='ACTIVE').exists()
        return GymMembership.objects.filter(
            user=request.user,
            gym_id=gym_id,
            role__in=['TRAINER', 'OWNER'],
            status='ACTIVE'
        ).exists()

class IsTrainerForClient(permissions.BasePermission):
    """
    Verifies that request.user is actively assigned to the client.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        client_user = getattr(obj, 'client', None) or getattr(obj, 'user', None)
        if not client_user:
            return False
        if client_user == request.user:
            return True
        return TrainerClientAssignment.objects.filter(
            trainer_membership__user=request.user,
            trainer_membership__status='ACTIVE',
            client_membership__user=client_user,
            client_membership__status='ACTIVE',
            is_active=True
        ).exists()
