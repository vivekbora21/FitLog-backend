from rest_framework import serializers
from workouts.models import JourneyProgram
from .models import Blueprint, TrainingSplit
from .split_approval import EQUIPMENT_LEVELS, DEFAULT_EQUIPMENT_LEVEL

class BlueprintSerializer(serializers.ModelSerializer):
    default_training_split_slug = serializers.SlugRelatedField(
        source='default_training_split', slug_field='slug', read_only=True
    )

    class Meta:
        model = Blueprint
        fields = [
            'id', 'slug', 'name', 'mode', 'description', 'difficulty',
            'default_duration_days', 'default_days_per_week', 'pacing_kg_per_week',
            'phases', 'workout_templates', 'meal_templates',
            'default_training_split_slug', 'is_active',
            'display_order', 'created_at', 'updated_at',
        ]

class TrainingSplitSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingSplit
        fields = [
            'id', 'slug', 'name', 'description', 'days_per_week',
            'workout_templates', 'is_active', 'display_order',
        ]

# Modes where a large goal-weight swing doesn't make sense (strength/skill focus
# or a fixed-habit reset) - allow only a trivial change over the plan.
TRIVIAL_GOAL_MODES = ('FOCUS', 'HABIT')
TRIVIAL_GOAL_DELTA_KG = 2.0

# Spec v1.6 section 4.3/V-05 GOAL_WEIGHT_REQUIRED, and defect #3 from
# section 1: Cut/Bulk cannot compute a calorie_delta without a goal weight
# (the plan_engine itself leaves target_calories null + fires a `block`
# message in that case -- see workouts/plan_engine/engine.py). Mirrors the
# engine's own behavior at the request layer instead of letting the request
# through to get a null, "can_start: false" preview/plan.
GOAL_WEIGHT_REQUIRED_MODES = ('CUT', 'BULK')

# Spec v1.6 section 4.3: only meaningful for RECOMP (the engine ignores it
# for every other mode -- see workouts/plan_engine/engine.py), matching the
# engine's own `RecompDirection` enum values exactly (lower snake_case), so
# no case-mapping is needed on the way in (see .services.engine_adapter).
RECOMP_DIRECTION_CHOICES = ['lean_out', 'maintain', 'lean_gain']


class MacroOverrideSerializer(serializers.Serializer):
    """Spec v1.6 section 4.8: a macro override is always a full triple --
    the client must send all three values (filling in the other two from
    what is currently displayed when the member edits just one), so the
    engine never has to guess a missing gram value."""
    protein_g = serializers.IntegerField(min_value=0)
    fat_g = serializers.IntegerField(min_value=0)
    carbs_g = serializers.IntegerField(min_value=0)


class PlanPreviewRequestSerializer(serializers.Serializer):
    blueprint_slug = serializers.CharField(required=False)
    mode = serializers.ChoiceField(choices=JourneyProgram.MODE_CHOICES, required=False)
    split_slug = serializers.CharField(required=False)
    duration_days = serializers.IntegerField(
        min_value=JourneyProgram.MIN_DURATION_DAYS, max_value=JourneyProgram.MAX_DURATION_DAYS
    )
    days_per_week = serializers.IntegerField(min_value=3, max_value=6)
    # New field (spec v1.6 section 6.2/6.7): which equipment the member has
    # access to, used only to gate split selection through SPLIT_APPROVAL
    # (V-21 NO_SUPPORTED_SPLIT) -- see plans/split_approval.py. Optional with
    # a default of 'full_gym' so existing callers that never send this field
    # see no behavior change (full gym is approved for every split today).
    equipment_level = serializers.ChoiceField(
        choices=list(EQUIPMENT_LEVELS), required=False, default=DEFAULT_EQUIPMENT_LEVEL
    )
    # New field (spec v1.6 section 6.2/6.4): training experience, used only
    # to pick the weekly-hard-sets-per-muscle-group range for the volume
    # check (plan_generator.EXPERIENCE_VOLUME_RANGES / VOLUME_OUTSIDE_RANGE).
    # Optional with a default of 'INTERMEDIATE' so existing callers that
    # never send this field see no behavior change beyond that default tier.
    experience = serializers.ChoiceField(
        choices=['BEGINNER', 'INTERMEDIATE', 'ADVANCED'], required=False, default='INTERMEDIATE'
    )
    weekdays = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=7), required=False
    )
    # New field (spec v1.6 section 6.6): an injected plan start date. Optional
    # -- when omitted, generate_roadmap defaults it to the first selected
    # training weekday on or after today (server timezone, via
    # core.middleware.TimezoneMiddleware).
    start_date = serializers.DateField(required=False)
    current_weight_kg = serializers.FloatField()
    goal_weight_kg = serializers.FloatField(required=False)
    height_cm = serializers.FloatField()
    age = serializers.IntegerField()
    sex = serializers.ChoiceField(choices=['MALE', 'FEMALE'])
    # Spec v1.6 section 4.3: pre-selected by the client from the goal weight
    # on switching to Recomp, but always overridable; ignored by the engine
    # outside Recomp. Optional -- the engine defaults to lean_out (4.3) when
    # omitted.
    recomp_direction = serializers.ChoiceField(choices=RECOMP_DIRECTION_CHOICES, required=False)
    # Spec v1.6 section 4.8 (overrides). The client sends at most one of
    # calorie_override / macro_override, never both -- the engine rejects
    # both at once with block OVERRIDE_CONFLICT (V-23) rather than guessing
    # which edit was last (see workouts/plan_engine/engine.py). Whenever
    # either is present, override_for_mode is mandatory (V-22
    # OVERRIDE_MODE_REQUIRED) and must match the current `mode`, or the
    # engine treats it as stale from a prior mode and ignores it (V-20
    # OVERRIDE_CLEARED_MODE_CHANGED).
    calorie_override = serializers.IntegerField(required=False)
    macro_override = MacroOverrideSerializer(required=False)
    override_for_mode = serializers.ChoiceField(choices=JourneyProgram.MODE_CHOICES, required=False)

    def validate(self, attrs):
        blueprint_slug = attrs.get('blueprint_slug')
        mode = attrs.get('mode')
        if not blueprint_slug and not mode:
            raise serializers.ValidationError('Either blueprint_slug or mode is required.')

        weekdays = attrs.get('weekdays')
        if weekdays and len(weekdays) != attrs['days_per_week']:
            raise serializers.ValidationError('weekdays must contain exactly days_per_week entries.')

        goal_weight_kg = attrs.get('goal_weight_kg')
        if mode in GOAL_WEIGHT_REQUIRED_MODES and goal_weight_kg is None:
            raise serializers.ValidationError(
                {'goal_weight_kg': f'goal_weight_kg is required for {mode} mode.'}
            )

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
