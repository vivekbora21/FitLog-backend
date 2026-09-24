from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import WeightEntry, BodyMeasurement, PersonalRecord, DailyLog
from .serializers import WeightEntrySerializer, BodyMeasurementSerializer, PersonalRecordSerializer, DailyLogSerializer
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
        return WeightEntry.objects.filter(user=user).order_by('-date')

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
        return BodyMeasurement.objects.filter(user=self.request.user).order_by('-date')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class PersonalRecordViewSet(viewsets.ReadOnlyModelViewSet):
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

        return qs.order_by('-date')

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

