from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
import secrets
from datetime import timedelta
from django.contrib.auth import password_validation
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from .models import User, UserProfile, PasswordResetCode
from .serializers import (
    UserSerializer,
    RegisterSerializer,
    UserProfileSerializer,
    ChangePasswordSerializer,
    FitLogTokenObtainPairSerializer,
)

class LoginView(TokenObtainPairView):
    permission_classes = [permissions.AllowAny]
    serializer_class = FitLogTokenObtainPairSerializer

class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                'user': UserSerializer(user).data,
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                }
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile_data = request.data.get('profile', {})
        if profile_data:
            profile_serializer = UserProfileSerializer(profile, data=profile_data, partial=True)
            if profile_serializer.is_valid():
                profile_serializer.save()

        user_serializer = UserSerializer(request.user, data=request.data, partial=True)
        if user_serializer.is_valid():
            user_serializer.save()
            return Response(user_serializer.data)
        return Response(user_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response({'detail': 'Password updated successfully.'})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


RESET_CODE_TTL = timedelta(minutes=15)
RESET_RESEND_COOLDOWN = timedelta(seconds=60)
RESET_GENERIC_REPLY = {'detail': 'If an account exists for that email, a reset code is on its way.'}


class PasswordResetRequestView(APIView):
    """Emails a 6-digit code. Always answers the same way so emails can't be probed."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first() if email else None
        if not user:
            return Response(RESET_GENERIC_REPLY)

        now = timezone.now()
        latest = user.password_reset_codes.first()
        if latest and not latest.used and latest.created_at > now - RESET_RESEND_COOLDOWN:
            return Response(RESET_GENERIC_REPLY)

        code = f'{secrets.randbelow(1_000_000):06d}'
        user.password_reset_codes.filter(used=False).update(used=True)
        PasswordResetCode.objects.create(user=user, code_hash=make_password(code), expires_at=now + RESET_CODE_TTL)
        send_mail(
            subject='Your FitLog password reset code',
            message=(
                f'Your FitLog reset code is {code}.\n\n'
                'It expires in 15 minutes. If you did not ask to reset your password, you can ignore this email.'
            ),
            from_email=None,
            recipient_list=[user.email],
            fail_silently=True,
        )
        return Response(RESET_GENERIC_REPLY)


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = str(request.data.get('email', '')).strip().lower()
        code = str(request.data.get('code', '')).strip()
        new_password = str(request.data.get('new_password', ''))
        invalid = Response({'detail': 'That code is invalid or has expired. Request a new one.'},
                           status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email__iexact=email, is_active=True).first() if email else None
        reset = user.password_reset_codes.filter(used=False).first() if user else None
        if not reset or reset.expires_at < timezone.now() or reset.attempts >= PasswordResetCode.MAX_ATTEMPTS:
            return invalid
        if not check_password(code, reset.code_hash):
            reset.attempts += 1
            reset.save(update_fields=['attempts', 'updated_at'])
            return invalid

        try:
            password_validation.validate_password(new_password, user=user)
        except DjangoValidationError as err:
            return Response({'new_password': list(err.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=['password'])
        reset.used = True
        reset.save(update_fields=['used', 'updated_at'])
        return Response({'detail': 'Password updated. You can sign in now.'})


class DeleteAccountView(APIView):
    """Permanently deletes the signed-in account and its data (App Store / Play requirement)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not request.user.check_password(str(request.data.get('password', ''))):
            return Response({'password': ['Password is incorrect.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                request.user.delete()
        except ProtectedError:
            return Response(
                {'detail': 'This account still owns data other members depend on. Contact support to delete it.'},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
