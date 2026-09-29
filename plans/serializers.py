from rest_framework import serializers
from workouts.models import JourneyProgram
from .models import Blueprint

class BlueprintSerializer(serializers.ModelSerializer):
    class Meta:
        model = Blueprint
        fields = [
            'id', 'slug', 'name', 'mode', 'description', 'difficulty',
            'default_duration_days', 'default_days_per_week', 'pacing_kg_per_week',
            'phases', 'workout_templates', 'meal_templates', 'is_active',
            'display_order', 'created_at', 'updated_at',
        ]

# Modes where a large goal-weight swing doesn't make sense (strength/skill focus
# or a fixed-habit reset) - allow only a trivial change over the plan.
TRIVIAL_GOAL_MODES = ('FOCUS', 'HABIT')
TRIVIAL_GOAL_DELTA_KG = 2.0

class PlanPreviewRequestSerializer(serializers.Serializer):
    blueprint_slug = serializers.CharField(required=False)
    mode = serializers.ChoiceField(choices=JourneyProgram.MODE_CHOICES, required=False)
    duration_days = serializers.IntegerField(
        min_value=JourneyProgram.MIN_DURATION_DAYS, max_value=JourneyProgram.MAX_DURATION_DAYS
    )
    days_per_week = serializers.IntegerField(min_value=3, max_value=6)
    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=7), required=False
    )
    current_weight_kg = serializers.FloatField()
    goal_weight_kg = serializers.FloatField(required=False)
    height_cm = serializers.FloatField()
    age = serializers.IntegerField()
    sex = serializers.ChoiceField(choices=['MALE', 'FEMALE'])

    def validate(self, attrs):
        blueprint_slug = attrs.get('blueprint_slug')
        mode = attrs.get('mode')
        if not blueprint_slug and not mode:
            raise serializers.ValidationError('Either blueprint_slug or mode is required.')

        weekdays = attrs.get('weekdays')
        if weekdays and len(weekdays) != attrs['days_per_week']:
            raise serializers.ValidationError('weekdays must contain exactly days_per_week entries.')

        goal_weight_kg = attrs.get('goal_weight_kg')
        if mode in TRIVIAL_GOAL_MODES and goal_weight_kg is not None:
            delta = abs(goal_weight_kg - attrs['current_weight_kg'])
            if delta > TRIVIAL_GOAL_DELTA_KG:
                raise serializers.ValidationError(
                    f"{mode} mode plans should not target more than a "
                    f"{TRIVIAL_GOAL_DELTA_KG}kg weight change over the plan."
                )
        return attrs

class PlanCreateRequestSerializer(PlanPreviewRequestSerializer):
    name = serializers.CharField(required=False)
