from django.db.models import Q
from rest_framework import serializers
from .models import MacroTarget, NutritionDay, MealEntry, Food


def foods_visible_to(user):
    return Food.objects.filter(Q(owner__isnull=True) | Q(owner=user))


class FoodSerializer(serializers.ModelSerializer):
    is_custom = serializers.SerializerMethodField()

    class Meta:
        model = Food
        fields = ['id', 'name', 'serving_label', 'serving_grams', 'calories', 'protein_g', 'carbs_g', 'fat_g', 'is_custom']

    def get_is_custom(self, obj):
        return obj.owner_id is not None


class MealEntrySerializer(serializers.ModelSerializer):
    food = serializers.PrimaryKeyRelatedField(queryset=Food.objects.none(), required=False, allow_null=True)
    servings = serializers.FloatField(required=False, min_value=0.01)
    quantity = serializers.FloatField(source='servings', required=False, min_value=0.01)
    # Required only for free-text entries; computed from the food otherwise.
    calories = serializers.IntegerField(required=False, min_value=0)
    protein_g = serializers.FloatField(required=False, min_value=0)
    carbs_g = serializers.FloatField(required=False, min_value=0)
    fat_g = serializers.FloatField(required=False, min_value=0)
    name = serializers.CharField(required=False, allow_blank=True, max_length=150)

    class Meta:
        model = MealEntry
        fields = ['id', 'meal_type', 'name', 'food', 'servings', 'quantity', 'calories', 'protein_g', 'carbs_g', 'fat_g', 'time_logged']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is not None and request.user.is_authenticated:
            self.fields['food'].queryset = foods_visible_to(request.user)

    def validate(self, attrs):
        food = attrs.get('food', getattr(self.instance, 'food', None))
        servings = attrs.get('servings', getattr(self.instance, 'servings', 1.0))
        if food is not None:
            attrs.update(food.macros_for(servings))
            if not attrs.get('name'):
                attrs['name'] = food.name
        elif self.instance is None:
            if not attrs.get('name'):
                raise serializers.ValidationError({'name': 'Enter a food name or pick a food.'})
            if attrs.get('calories') is None:
                raise serializers.ValidationError({'calories': 'Calories are required when no food is picked.'})
        return attrs


class NutritionDaySerializer(serializers.ModelSerializer):
    meals = MealEntrySerializer(many=True, read_only=True)
    total_calories = serializers.IntegerField(read_only=True)
    total_protein = serializers.FloatField(read_only=True)
    total_carbs = serializers.FloatField(read_only=True)
    total_fat = serializers.FloatField(read_only=True)

    class Meta:
        model = NutritionDay
        fields = [
            'id', 'user', 'date', 'water_consumed_ml', 'notes',
            'meals', 'total_calories', 'total_protein', 'total_carbs', 'total_fat'
        ]
        read_only_fields = ['user']

class MacroTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = MacroTarget
        fields = ['id', 'user', *MacroTarget.FIELDS]
        read_only_fields = ['user']
