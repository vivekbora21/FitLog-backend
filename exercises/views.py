from rest_framework import viewsets, permissions, filters
from rest_framework.exceptions import PermissionDenied
from django.db import models
from django.utils.text import slugify
from .models import MuscleGroup, EquipmentType, Exercise
from .serializers import MuscleGroupSerializer, EquipmentTypeSerializer, ExerciseSerializer
from memberships.models import GymMembership

class MuscleGroupViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MuscleGroup.objects.all().order_by('name')
    serializer_class = MuscleGroupSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

class EquipmentTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = EquipmentType.objects.all().order_by('name')
    serializer_class = EquipmentTypeSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

class ExerciseViewSet(viewsets.ModelViewSet):
    serializer_class = ExerciseSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'instructions', 'primary_muscle__name']
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        gym_id = self.request.query_params.get('gym_id')
        muscle = self.request.query_params.get('muscle')
        equipment = self.request.query_params.get('equipment')

        # Global catalog + the user's own custom movements + exercises of gyms they belong to.
        gym_ids = GymMembership.objects.filter(user=user, status='ACTIVE').values_list('gym_id', flat=True)
        visible = (
            models.Q(gym__isnull=True, created_by__isnull=True)
            | models.Q(created_by=user)
            | models.Q(gym_id__in=gym_ids)
        )
        qs = Exercise.objects.filter(visible)
        if gym_id:
            qs = qs.filter(models.Q(gym__isnull=True) | models.Q(gym_id=gym_id))

        if muscle:
            qs = qs.filter(primary_muscle__slug=muscle)
        if equipment:
            qs = qs.filter(equipment__slug=equipment)

        return qs.select_related('primary_muscle', 'equipment', 'gym').distinct()

    def perform_create(self, serializer):
        name = serializer.validated_data['name'].strip()
        slug = serializer.validated_data.get('slug') or slugify(name)[:140] or 'exercise'
        # Member-created movements are personal; gym catalogs are managed elsewhere.
        serializer.save(created_by=self.request.user, gym=None, name=name, slug=slug)

    def _require_owner(self, instance):
        if instance.created_by_id != self.request.user.id:
            raise PermissionDenied('Only your own custom exercises can be changed.')

    def perform_update(self, serializer):
        self._require_owner(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_owner(instance)
        instance.delete()
