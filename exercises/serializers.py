from rest_framework import serializers
from .models import MuscleGroup, EquipmentType, Exercise

class MuscleGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = MuscleGroup
        fields = ['id', 'name', 'slug']

class EquipmentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentType
        fields = ['id', 'name', 'slug']

class ExerciseSerializer(serializers.ModelSerializer):
    primary_muscle_name = serializers.CharField(source='primary_muscle.name', read_only=True)
    equipment_name = serializers.CharField(source='equipment.name', read_only=True)
    gym_name = serializers.CharField(source='gym.name', read_only=True)
    is_global = serializers.BooleanField(read_only=True)

    class Meta:
        model = Exercise
        fields = [
            'id', 'name', 'slug', 'gym', 'gym_name', 'primary_muscle', 'primary_muscle_name',
            'secondary_muscles', 'equipment', 'equipment_name', 'instructions', 'video_url', 'is_global'
        ]
