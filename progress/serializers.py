from rest_framework import serializers
from .models import WeightEntry, BodyMeasurement, PersonalRecord, DailyLog, ProgressPhoto
from exercises.serializers import ExerciseSerializer

class WeightEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = WeightEntry
        fields = ['id', 'user', 'date', 'weight_kg', 'body_fat_pct', 'notes', 'created_at']
        read_only_fields = ['user', 'created_at']

class BodyMeasurementSerializer(serializers.ModelSerializer):
    class Meta:
        model = BodyMeasurement
        fields = [
            'id', 'user', 'date',
            'neck_cm', 'shoulders_cm', 'chest_cm', 'waist_cm', 'hips_cm',
            'arms_cm', 'biceps_left_cm', 'biceps_right_cm', 'forearms_cm',
            'thighs_cm', 'thigh_left_cm', 'thigh_right_cm', 'calves_cm', 'calf_left_cm', 'calf_right_cm',
            'notes', 'created_at'
        ]
        read_only_fields = ['user', 'created_at']

class PersonalRecordSerializer(serializers.ModelSerializer):
    exercise_name = serializers.CharField(source='exercise.name', read_only=True)
    primary_muscle = serializers.CharField(source='exercise.primary_muscle.name', read_only=True)

    class Meta:
        model = PersonalRecord
        fields = ['id', 'exercise', 'exercise_name', 'primary_muscle', 'max_weight_kg', 'reps', 'estimated_one_rep_max', 'achieved_at']
        read_only_fields = ['user']
        extra_kwargs = {
            'estimated_one_rep_max': {'required': False},
            'achieved_at': {'required': False},
        }


class DailyLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyLog
        fields = [
            'id', 'user', 'date', 'steps', 'sleep_hours',
            'sleep_quality', 'energy_level', 'recovery_notes',
            'day_status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['user', 'created_at', 'updated_at']


class ProgressPhotoSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ProgressPhoto
        fields = [
            'id', 'date', 'photo', 'photo_url', 'url',
            'angle', 'notes', 'is_private', 'weight_kg', 'created_at',
        ]
        read_only_fields = ['user', 'created_at', 'url']
        extra_kwargs = {'photo': {'required': False}, 'photo_url': {'required': False}}

    def get_url(self, obj):
        request = self.context.get('request')
        url = obj.get_photo_url()
        if url and request and not url.startswith('http'):
            return request.build_absolute_uri(url)
        return url
