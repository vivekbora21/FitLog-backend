from rest_framework import viewsets, permissions, filters
from django.db import models
from .models import MuscleGroup, EquipmentType, Exercise
from .serializers import MuscleGroupSerializer, EquipmentTypeSerializer, ExerciseSerializer

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
        gym_id = self.request.query_params.get('gym_id')
        muscle = self.request.query_params.get('muscle')
        equipment = self.request.query_params.get('equipment')

        # Global exercises (gym is NULL) + gym-specific exercises if gym_id provided
        if gym_id:
            qs = Exercise.objects.filter(models.Q(gym__isnull=True) | models.Q(gym_id=gym_id))
        else:
            qs = Exercise.objects.all()

        if muscle:
            qs = qs.filter(primary_muscle__slug=muscle)
        if equipment:
            qs = qs.filter(equipment__slug=equipment)

        return qs.select_related('primary_muscle', 'equipment', 'gym').distinct()

