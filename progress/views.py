from core.query_params import apply_date_range
from django.db import transaction, IntegrityError
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
        user = self.request.user
        date_val = serializer.validated_data['date']
        # A retried weigh-in write (same user, same date — the one-entry-per-day case an
        # offline queue would hit on reconnect, or a user correcting today's weight by
        # logging again) must not 500 on the unique(user, date) constraint. Upsert instead:
        # the retry's values become the day's entry, same as if the first attempt had
        # simply been edited afterward.
        try:
            with transaction.atomic():
                serializer.save(user=user)
        except IntegrityError:
            existing = WeightEntry.objects.get(user=user, date=date_val)
            for field in ('weight_kg', 'body_fat_pct', 'notes'):
                if field in serializer.validated_data:
                    setattr(existing, field, serializer.validated_data[field])
            existing.save()
            serializer.instance = existing

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
        user = self.request.user
        meas_date = serializer.validated_data.get('date')
        existing = BodyMeasurement.objects.filter(user=user, date=meas_date).first()
        if existing:
            for attr, val in serializer.validated_data.items():
                setattr(existing, attr, val)
            existing.save()
            serializer.instance = existing
        else:
            serializer.save(user=user)

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        """
        Computes body measurement KPI summary, ratios, deltas, and symmetry balance on the backend.
        """
        user = request.user
        client_id = request.query_params.get('client_id')
        if client_id and client_id != str(user.id):
            if can_view_progress(user, client_id, 'share_body_measurements'):
                target_user_id = client_id
            else:
                return Response({'detail': 'Not authorized to view measurements.'}, status=status.HTTP_403_FORBIDDEN)
        else:
            target_user_id = user.id

        measurements = list(BodyMeasurement.objects.filter(user_id=target_user_id).order_by('date'))
        if not measurements:
            return Response({
                'has_data': False,
                'total_logs': 0,
                'kpis': None,
                'overview': [],
                'symmetry': [],
                'dates': [],
                'baseline_date': None,
                'latest_date': None,
            })

        baseline = measurements[0]
        latest = measurements[-1]

        # 1. Waist change calculation
        waist_baseline = baseline.waist_cm
        waist_latest = latest.waist_cm
        waist_diff = round(float(waist_latest - waist_baseline), 1) if (waist_latest is not None and waist_baseline is not None) else None
        waist_diff_pct = round(abs(waist_diff / float(waist_baseline)) * 100, 1) if (waist_diff is not None and waist_baseline) else None
        waist_sparkline = [float(m.waist_cm) for m in measurements if m.waist_cm is not None]

        # 2. Shoulder to Waist ratio
        shoulder_val = latest.shoulders_cm
        shoulder_to_waist = round(float(shoulder_val / waist_latest), 2) if (shoulder_val and waist_latest) else None
        shoulder_target = 1.45
        shoulder_progress_pct = min(100, round((shoulder_to_waist / shoulder_target) * 100)) if shoulder_to_waist else 83

        # 3. Chest to Waist ratio
        chest_val = latest.chest_cm
        chest_to_waist = round(float(chest_val / waist_latest), 2) if (chest_val and waist_latest) else None
        chest_target = 1.20
        chest_progress_pct = min(100, round((chest_to_waist / chest_target) * 100)) if chest_to_waist else 94

        # 4. Total checkins
        total_logs = len(measurements)

        # 5. Anatomical site overviews
        sites = [
            ('shoulders_cm', 'Shoulders', 'torso', 'hypertrophy', 'shoulders'),
            ('chest_cm', 'Chest', 'torso', 'hypertrophy', 'chest'),
            ('waist_cm', 'Waist', 'torso', 'reduction', 'waist'),
            ('hips_cm', 'Hips', 'torso', 'reduction', 'hips'),
            ('arms_cm', 'Arms', 'arms', 'hypertrophy', 'arms'),
            ('thighs_cm', 'Thighs', 'legs', 'hypertrophy', 'thighs'),
            ('calves_cm', 'Calves', 'legs', 'hypertrophy', 'calves'),
            ('neck_cm', 'Neck', 'torso', 'neutral', 'neck'),
        ]
        overview = []
        for field, label, category, target_type, icon_type in sites:
            cur = getattr(latest, field, None)
            base = getattr(baseline, field, None)
            cur_f = float(cur) if cur is not None else None
            base_f = float(base) if base is not None else None
            diff_f = round(cur_f - base_f, 1) if (cur_f is not None and base_f is not None) else None
            diff_pct_f = round((diff_f / base_f) * 100, 1) if (diff_f is not None and base_f) else None
            overview.append({
                'key': field,
                'label': label,
                'category': category,
                'target_type': target_type,
                'icon_type': icon_type,
                'current_cm': cur_f,
                'baseline_cm': base_f,
                'diff_cm': diff_f,
                'diff_pct': diff_pct_f,
            })

        # 6. Bilateral Symmetry calculation
        def calc_sym(left, right, label, icon_type):
            if left is None or right is None:
                return None
            l_val = float(left)
            r_val = float(right)
            diff = round(abs(l_val - r_val), 1)
            is_balanced = diff <= 0.4
            max_v = max(l_val, r_val) or 1
            return {
                'label': label,
                'icon_type': icon_type,
                'left_cm': l_val,
                'right_cm': r_val,
                'diff_cm': diff,
                'is_balanced': is_balanced,
                'left_ratio': round((l_val / max_v) * 100),
                'right_ratio': round((r_val / max_v) * 100),
            }

        symmetry = [
            calc_sym(latest.biceps_left_cm, latest.biceps_right_cm, 'Arms / Biceps', 'arms'),
            calc_sym(latest.thigh_left_cm, latest.thigh_right_cm, 'Thighs / Quads', 'thighs'),
            calc_sym(latest.calf_left_cm, latest.calf_right_cm, 'Calves', 'calves'),
        ]
        symmetry = [s for s in symmetry if s is not None]

        # MEAS-002: Dynamic measurement frequency comparison vs previous 30-day window
        today_date = timezone.localdate()
        thirty_days_ago = today_date - timedelta(days=30)
        sixty_days_ago = today_date - timedelta(days=60)
        recent_count = sum(1 for m in measurements if m.date >= thirty_days_ago)
        prev_count = sum(1 for m in measurements if sixty_days_ago <= m.date < thirty_days_ago)
        delta_month = recent_count - prev_count
        if prev_count == 0 and recent_count == 0:
            recent_pill = None
        elif delta_month > 0:
            recent_pill = f"↑ +{delta_month} vs last month"
        elif delta_month < 0:
            recent_pill = f"↓ {delta_month} vs last month"
        else:
            recent_pill = "Same as last month"

        return Response({
            'has_data': True,
            'total_logs': total_logs,
            'kpis': {
                'waist_change': {
                    'baseline_cm': float(waist_baseline) if waist_baseline else None,
                    'current_cm': float(waist_latest) if waist_latest else None,
                    'diff_cm': waist_diff,
                    'diff_pct': waist_diff_pct,
                    'sparkline': waist_sparkline,
                },
                'shoulder_to_waist': {
                    'ratio': shoulder_to_waist,
                    'target': shoulder_target,
                    'progress_pct': shoulder_progress_pct,
                },
                'chest_to_waist': {
                    'ratio': chest_to_waist,
                    'target': chest_target,
                    'progress_pct': chest_progress_pct,
                },
                'measurements_logged': {
                    'total': total_logs,
                    'recent_pill': recent_pill,
                },
            },
            'overview': overview,
            'symmetry': symmetry,
            'baseline_date': baseline.date.isoformat(),
            'latest_date': latest.date.isoformat(),
            'dates': [m.date.isoformat() for m in measurements],
        })

    @action(detail=False, methods=['get'], url_path='compare')
    def compare(self, request):
        """
        Compares body measurements between two dates on the backend.
        """
        user = request.user
        client_id = request.query_params.get('client_id')
        if client_id and client_id != str(user.id):
            if can_view_progress(user, client_id, 'share_body_measurements'):
                target_user_id = client_id
            else:
                return Response({'detail': 'Not authorized to view measurements.'}, status=status.HTTP_403_FORBIDDEN)
        else:
            target_user_id = user.id

        date_a_str = request.query_params.get('date_a')
        date_b_str = request.query_params.get('date_b')

        measurements = list(BodyMeasurement.objects.filter(user_id=target_user_id).order_by('date'))
        if not measurements:
            return Response({'rows': []})

        date_map = {m.date.isoformat(): m for m in measurements}
        m_a = date_map.get(date_a_str) or measurements[0]
        m_b = date_map.get(date_b_str) or measurements[-1]

        sites = [
            ('shoulders_cm', 'Shoulders', 'hypertrophy'),
            ('chest_cm', 'Chest', 'hypertrophy'),
            ('waist_cm', 'Waist', 'reduction'),
            ('hips_cm', 'Hips', 'reduction'),
            ('arms_cm', 'Arms / Biceps', 'hypertrophy'),
            ('thighs_cm', 'Thighs', 'hypertrophy'),
            ('calves_cm', 'Calves', 'hypertrophy'),
            ('neck_cm', 'Neck', 'neutral'),
        ]

        rows = []
        for field, label, target_type in sites:
            val_a = getattr(m_a, field, None)
            val_b = getattr(m_b, field, None)
            val_a_f = float(val_a) if val_a is not None else None
            val_b_f = float(val_b) if val_b is not None else None
            diff_f = round(val_b_f - val_a_f, 1) if (val_b_f is not None and val_a_f is not None) else None
            diff_pct_f = round((diff_f / val_a_f) * 100, 1) if (diff_f is not None and val_a_f) else None

            rows.append({
                'key': field,
                'site': label,
                'target_type': target_type,
                'val_a_cm': val_a_f,
                'val_b_cm': val_b_f,
                'diff_cm': diff_f,
                'diff_pct': diff_pct_f,
            })

        return Response({
            'date_a': m_a.date.isoformat(),
            'date_b': m_b.date.isoformat(),
            'rows': rows,
        })

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
                existing.is_manual = True
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
        serializer.save(user=self.request.user, estimated_one_rep_max=est, is_manual=True)


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


class PersonalRecordTrendView(APIView):
    """Returns a per-exercise estimated-1RM progression over time, derived from logged
    sets (PersonalRecord only stores the current best, not its history). Used to power
    a "strength growth" line chart on mobile/web and in the data export PDF."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .records import compute_pr_trend

        exercise_id = request.query_params.get('exercise_id')
        if not exercise_id:
            return Response({'detail': 'exercise_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        client_id = request.query_params.get('client_id')
        user = request.user
        if client_id and client_id != str(user.id):
            if not can_view_progress(user, client_id, 'share_progress_with_trainers'):
                return Response({'exercise_id': exercise_id, 'trend': []})
            user = type(user).objects.get(id=client_id)

        return Response({'exercise_id': exercise_id, 'trend': compute_pr_trend(user, exercise_id)})
