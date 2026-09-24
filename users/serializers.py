from django.contrib.auth import password_validation
from rest_framework import serializers
from .models import User, UserProfile

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['id', 'date_of_birth', 'height_cm', 'weight_kg', 'sex', 'activity_level', 'fitness_goal', 'unit_preference', 'bio']

class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)
    full_name = serializers.SerializerMethodField()
    memberships = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'first_name', 'last_name', 'full_name', 'avatar_url', 'profile', 'memberships']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_memberships(self, obj):
        from memberships.models import GymMembership
        memberships = GymMembership.objects.filter(user=obj, status='ACTIVE').select_related('gym')
        return [
            {
                'id': str(m.id),
                'gym_id': str(m.gym.id),
                'gym_name': m.gym.name,
                'gym_slug': m.gym.slug,
                'role': m.role,
                'status': m.status,
                'share_workouts_with_trainers': m.share_workouts_with_trainers,
                'share_progress_with_trainers': m.share_progress_with_trainers,
            }
            for m in memberships
        ]

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, user=self.context['request'].user)
        return value

    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    username = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['email', 'username', 'password', 'first_name', 'last_name']

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data['email'],
            username=validated_data.get('username') or validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )
        UserProfile.objects.create(user=user)
        return user
