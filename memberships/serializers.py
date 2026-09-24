from rest_framework import serializers
from .models import GymMembership, TrainerClientAssignment, GymInvitation
from users.serializers import UserSerializer

class GymMembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    gym_name = serializers.CharField(source='gym.name', read_only=True)

    class Meta:
        model = GymMembership
        fields = [
            'id', 'user', 'gym', 'gym_name', 'role', 'status',
            'share_workouts_with_trainers', 'share_progress_with_trainers',
            'share_nutrition_with_trainers', 'share_body_measurements', 'created_at'
        ]

class TrainerClientAssignmentSerializer(serializers.ModelSerializer):
    trainer_name = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    client_email = serializers.EmailField(source='client_membership.user.email', read_only=True)
    client_id = serializers.CharField(source='client_membership.user.id', read_only=True)

    class Meta:
        model = TrainerClientAssignment
        fields = ['id', 'trainer_membership', 'client_membership', 'trainer_name', 'client_name', 'client_email', 'client_id', 'is_active', 'start_date', 'notes']

    def get_trainer_name(self, obj):
        u = obj.trainer_membership.user
        return u.get_full_name() or u.username

    def get_client_name(self, obj):
        u = obj.client_membership.user
        return u.get_full_name() or u.username

class GymInvitationSerializer(serializers.ModelSerializer):
    gym_name = serializers.CharField(source='gym.name', read_only=True)
    invited_by_name = serializers.SerializerMethodField()

    class Meta:
        model = GymInvitation
        fields = ['id', 'gym', 'gym_name', 'email', 'role', 'token', 'status', 'expires_at', 'invited_by_name', 'created_at']
        read_only_fields = ['token', 'status', 'expires_at']

    def get_invited_by_name(self, obj):
        return obj.invited_by.get_full_name() or obj.invited_by.email
