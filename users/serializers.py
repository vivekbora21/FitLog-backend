import re
from django.contrib.auth import password_validation, authenticate
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
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

class FitLogTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Enhanced login serializer with email normalization, format validation,
    case-insensitive matching, and descriptive error messages.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[self.username_field] = serializers.CharField(
            required=True,
            error_messages={
                'required': 'Email address is required.',
                'blank': 'Email address cannot be blank.'
            }
        )
        self.fields['password'] = serializers.CharField(
            required=True,
            write_only=True,
            error_messages={
                'required': 'Password is required.',
                'blank': 'Password cannot be blank.'
            }
        )

    def validate(self, attrs):
        raw_email = attrs.get(self.username_field) or attrs.get('email', '')
        if not raw_email or not str(raw_email).strip():
            raise serializers.ValidationError({self.username_field: ['Email address is required.']})

        email = str(raw_email).strip().lower()
        try:
            validate_email(email)
        except DjangoValidationError:
            raise serializers.ValidationError({self.username_field: ['Please enter a valid email address.']})

        raw_password = attrs.get('password', '')
        if not raw_password or not str(raw_password).strip():
            raise serializers.ValidationError({'password': ['Password is required.']})

        # Match user case-insensitively
        user_obj = User.objects.filter(email__iexact=email).first()
        if user_obj:
            attrs[self.username_field] = user_obj.email
            if not user_obj.is_active:
                raise serializers.ValidationError({'detail': 'This account is inactive. Please contact support.'})
        else:
            attrs[self.username_field] = email

        try:
            data = super().validate(attrs)
        except Exception:
            raise serializers.ValidationError({'detail': 'Invalid email or password.'})

        user = self.user
        data['user'] = {
            'id': str(user.id),
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': user.get_full_name() or user.username,
        }
        return data

class RegisterSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(
        required=True,
        max_length=50,
        error_messages={
            'required': 'First name is required.',
            'blank': 'First name cannot be blank.',
        }
    )
    last_name = serializers.CharField(
        required=True,
        max_length=50,
        error_messages={
            'required': 'Last name is required.',
            'blank': 'Last name cannot be blank.',
        }
    )
    email = serializers.EmailField(
        required=True,
        max_length=254,
        error_messages={
            'required': 'Email address is required.',
            'blank': 'Email address cannot be blank.',
            'invalid': 'Please enter a valid email address.'
        }
    )
    password = serializers.CharField(
        write_only=True,
        required=True,
        min_length=8,
        max_length=128,
        error_messages={
            'required': 'Password is required.',
            'blank': 'Password cannot be blank.',
            'min_length': 'Password must be at least 8 characters long.',
            'max_length': 'Password cannot exceed 128 characters.',
        }
    )
    confirm_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True
    )
    username = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['email', 'username', 'password', 'confirm_password', 'first_name', 'last_name']

    def validate_first_name(self, value):
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise serializers.ValidationError('First name must be at least 2 characters.')
        if re.search(r'[0-9<>{}\[\]\\]', cleaned):
            raise serializers.ValidationError('First name contains invalid characters.')
        return cleaned

    def validate_last_name(self, value):
        cleaned = value.strip()
        if len(cleaned) < 1:
            raise serializers.ValidationError('Last name cannot be blank.')
        if re.search(r'[0-9<>{}\[\]\\]', cleaned):
            raise serializers.ValidationError('Last name contains invalid characters.')
        return cleaned

    def validate_email(self, value):
        cleaned = value.strip().lower()
        try:
            validate_email(cleaned)
        except DjangoValidationError:
            raise serializers.ValidationError('Please enter a valid email address.')

        if User.objects.filter(email__iexact=cleaned).exists():
            raise serializers.ValidationError('An account with this email address already exists.')
        return cleaned

    def validate_password(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('Password cannot be empty or pure whitespace.')

        if not re.search(r'[A-Za-z]', value):
            raise serializers.ValidationError('Password must contain at least one letter.')
        if not re.search(r'[0-9!@#$%^&*(),.?":{}|<>]', value):
            raise serializers.ValidationError('Password must contain at least one number or special symbol.')

        return value

    def validate(self, attrs):
        password = attrs.get('password')
        confirm_password = attrs.get('confirm_password')

        if confirm_password is not None and confirm_password != '' and password != confirm_password:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})

        # Run Django password validators
        temp_user = User(
            email=attrs.get('email', ''),
            first_name=attrs.get('first_name', ''),
            last_name=attrs.get('last_name', '')
        )
        try:
            password_validation.validate_password(password, user=temp_user)
        except DjangoValidationError as err:
            raise serializers.ValidationError({'password': list(err.messages)})

        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password', None)
        email = validated_data['email']
        base_username = validated_data.get('username') or email
        username = base_username[:150]
        counter = 1
        original_username = username
        while User.objects.filter(username=username).exists():
            suffix = f"_{counter}"
            username = f"{original_username[:150-len(suffix)]}{suffix}"
            counter += 1

        user = User.objects.create_user(
            email=email,
            username=username,
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name']
        )
        UserProfile.objects.create(user=user)
        return user
