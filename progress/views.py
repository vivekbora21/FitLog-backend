from core.query_params import apply_date_range
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import WeightEntry, BodyMeasurement, PersonalRecord, DailyLog, ProgressPhoto
from .serializers import WeightEntrySerializer, BodyMeasurementSerializer, PersonalRecordSerializer, DailyLogSerializer, ProgressPhotoSerializer
from memberships.models import TrainerClientAssignment

def can_view_progress(requester, client_id, permission_field):
    return TrainerClientAssignment.objects.filter(
        trainer_membership__user=requester, client_membership__user_id=client_id,
        is_active=True, **{f'client_membership__{permission_field}': True}
    ).exists()

class WeightEntryViewSet(viewsets.ModelViewSet):
    serializer_class = WeightEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        client_id = self.request.query_params.get('client_id')
        user = self.request.user
        if client_id and client_id != str(user.id):
            if can_view_progress(user, client_id, 'share_progress_with_trainers'):
                return WeightEntry.objects.filter(user_id=client_id).order_by('-date')
            return WeightEntry.objects.none()
        return apply_date_range(WeightEntry.objects.filter(user=user), self.request, 'date').order_by('-date')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class BodyMeasurementViewSet(viewsets.ModelViewSet):
    serializer_class = BodyMeasurementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        client_id = self.request.query_params.get('client_id')
        if client_id and client_id != str(self.request.user.id):
            if can_view_progress(self.request.user, client_id, 'share_body_measurements'):
                return BodyMeasurement.objects.filter(user_id=client_id).order_by('-date')
            return BodyMeasurement.objects.none()
        return apply_date_range(BodyMeasurement.objects.filter(user=self.request.user), self.request, 'date').order_by('-date')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class PersonalRecordViewSet(viewsets.ModelViewSet):
    serializer_class = PersonalRecordSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        client_id = self.request.query_params.get('client_id')
        user = self.request.user
        if client_id and client_id != str(user.id):
            if can_view_progress(user, client_id, 'share_progress_with_trainers'):
                return PersonalRecord.objects.filter(user_id=client_id).select_related('exercise__primary_muscle').order_by('-estimated_one_rep_max')
            return PersonalRecord.objects.none()
        return PersonalRecord.objects.filter(user=user).select_related('exercise__primary_muscle').order_by('-estimated_one_rep_max')

    def create(self, request, *args, **kwargs):
        exercise_id = request.data.get('exercise')
        max_weight = float(request.data.get('max_weight_kg', 0))
        reps = int(request.data.get('reps', 1))
        achieved_at = request.data.get('achieved_at')
        if not achieved_at:
            from django.utils import timezone
            achieved_at = timezone.now().date()

        est_1rm = float(request.data.get('estimated_one_rep_max') or 0)
        if not est_1rm and max_weight:
            est_1rm = PersonalRecord.calculate_epley_1rm(max_weight, reps)

        existing = PersonalRecord.objects.filter(user=request.user, exercise_id=exercise_id).first()
        if existing:
            if est_1rm >= existing.estimated_one_rep_max:
                existing.max_weight_kg = max_weight
                existing.reps = reps
                existing.estimated_one_rep_max = est_1rm
                existing.achieved_at = achieved_at
                existing.save()
            serializer = self.get_serializer(existing)
            return Response(serializer.data, status=status.HTTP_200_OK)

        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        max_weight = serializer.validated_data.get('max_weight_kg', 0)
        reps = serializer.validated_data.get('reps', 1)
        est = serializer.validated_data.get('estimated_one_rep_max')
        if not est and max_weight:
            est = PersonalRecord.calculate_epley_1rm(max_weight, reps)
        serializer.save(user=self.request.user, estimated_one_rep_max=est)


class DailyLogViewSet(viewsets.ModelViewSet):
    """
    ViewSet for logging and retrieving daily steps, sleep, and recovery metrics.
    """
    serializer_class = DailyLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        client_id = self.request.query_params.get('client_id')
        user = self.request.user
        qs = DailyLog.objects.none()
        if client_id and client_id != str(user.id):
            if can_view_progress(user, client_id, 'share_progress_with_trainers'):
                qs = DailyLog.objects.filter(user_id=client_id)
        else:
            qs = DailyLog.objects.filter(user=user)

        date_param = self.request.query_params.get('date')
        if date_param:
            qs = qs.filter(date=date_param)

        return apply_date_range(qs, self.request, 'date').order_by('-date')

    def create(self, request, *args, **kwargs):
        date_val = request.data.get('date')
        if date_val:
            existing = DailyLog.objects.filter(user=request.user, date=date_val).first()
            if existing:
                serializer = self.get_serializer(existing, data=request.data, partial=True)
                serializer.is_valid(raise_exception=True)
                self.perform_update(serializer)
                return Response(serializer.data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ProgressPhotoViewSet(viewsets.ModelViewSet):
    """
    CRUD for a member's progress photos.
    Supports both file upload (multipart/form-data) and external photo_url.
    GET /progress/photos/?client_id=<id>  — trainers can view non-private photos of consenting clients.
    GET /progress/photos/by_date/         — returns photos bucketed by date.
    """
    serializer_class = ProgressPhotoSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        user = self.request.user
        client_id = self.request.query_params.get('client_id')
        if client_id and client_id != str(user.id):
            if can_view_progress(user, client_id, 'share_progress_with_trainers'):
                return ProgressPhoto.objects.filter(user_id=client_id, is_private=False).order_by('-date')
            return ProgressPhoto.objects.none()
        return ProgressPhoto.objects.filter(user=user).order_by('-date', 'angle')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def _require_owner(self, instance):
        if instance.user_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You can only modify your own photos.')

    def perform_update(self, serializer):
        self._require_owner(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_owner(instance)
        instance.delete()

    @action(detail=False, methods=['get'], url_path='by-date')
    def by_date(self, request):
        """Group photos by date, descending. Each date bucket lists the photos for that day."""
        qs = self.get_queryset()
        from collections import defaultdict
        grouped = defaultdict(list)
        for photo in qs:
            grouped[photo.date.isoformat()].append(photo)
        serializer = self.get_serializer
        result = [
            {
                'date': date_str,
                'photos': ProgressPhotoSerializer(photos, many=True, context={'request': request}).data,
            }
            for date_str, photos in sorted(grouped.items(), reverse=True)
        ]
        return Response(result)
