from datetime import date, timedelta
from django.db.models import F
from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from .models import MacroTarget, NutritionDay, MealEntry
from .serializers import MacroTargetSerializer, NutritionDaySerializer, MealEntrySerializer, FoodSerializer, foods_visible_to
from .targets import calculate_recommended_targets, get_or_create_macro_target, resolve_target_update, targets_payload

class NutritionDayView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, date_str=None):
        if not date_str or date_str == 'today':
            target_date = date.today()
        else:
            try:
                target_date = date.fromisoformat(date_str)
            except ValueError:
                target_date = date.today()

        day, _ = NutritionDay.objects.get_or_create(user=request.user, date=target_date)
        target = get_or_create_macro_target(request.user)

        yesterday = target_date - timedelta(days=1)
        yesterday_day = NutritionDay.objects.filter(user=request.user, date=yesterday).first()
        yesterday_meals = MealEntrySerializer(yesterday_day.meals.all(), many=True).data if yesterday_day else []

        return Response({
            'day': NutritionDaySerializer(day).data,
            'targets': MacroTargetSerializer(target).data,
            'yesterday_meals': yesterday_meals,
        })

    def patch(self, request, date_str=None):
        target_date = date.today() if not date_str or date_str == 'today' else date.fromisoformat(date_str)
        day, _ = NutritionDay.objects.get_or_create(user=request.user, date=target_date)
        
        water = request.data.get('water_consumed_ml')
        if water is not None:
            day.water_consumed_ml = water
            day.save()
            
        return Response(NutritionDaySerializer(day).data)

class MealEntryViewSet(viewsets.ModelViewSet):
    serializer_class = MealEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return MealEntry.objects.filter(nutrition_day__user=self.request.user)

    def perform_create(self, serializer):
        date_str = self.request.data.get('date')
        target_date = date.fromisoformat(date_str) if date_str else date.today()
        day, _ = NutritionDay.objects.get_or_create(user=self.request.user, date=target_date)
        serializer.save(nutrition_day=day)

class MacroTargetView(APIView):
    """
    GET: targets with suggestions, plan-resolved values and warnings.
    PUT: partial edit; send `dry_run: true` to preview carb rebalancing and warnings without saving.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(targets_payload(request.user))

    def put(self, request):
        target = get_or_create_macro_target(request.user)
        values, adjustments, errors = resolve_target_update(target, request.data)
        if errors:
            return Response({'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
        if not request.data.get('dry_run'):
            for field, value in values.items():
                setattr(target, field, value)
            target.save()
        return Response(targets_payload(request.user, values=values, adjustments=adjustments))

    patch = put


class FoodViewSet(viewsets.ModelViewSet):
    """Shared catalog foods plus the user's own saved foods. Only own foods are editable."""
    serializer_class = FoodSerializer
    permission_classes = [permissions.IsAuthenticated]
    # Search results are capped at 50 below; a plain list is simpler for the picker.
    pagination_class = None

    def get_queryset(self):
        qs = foods_visible_to(self.request.user)
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(name__icontains=search)
        # The user's own foods first: they're the ones they actually eat.
        return qs.order_by(F('owner').asc(nulls_last=True), 'name')[:50] if self.action == 'list' else qs

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def _check_owner(self, food):
        if food.owner_id != self.request.user.id:
            raise PermissionDenied('Catalog foods cannot be changed.')

    def perform_update(self, serializer):
        self._check_owner(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._check_owner(instance)
        instance.delete()

class RecommendedMacroTargetView(APIView):
    """GET shows the BMR -> TDEE -> goal derivation; POST applies it to the user's targets."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(calculate_recommended_targets(request.user))

    def post(self, request):
        rec = calculate_recommended_targets(request.user)
        if not rec['available']:
            return Response(rec, status=status.HTTP_400_BAD_REQUEST)
        target = get_or_create_macro_target(request.user)
        for field in ('daily_calories', 'protein_g', 'carbs_g', 'fat_g'):
            setattr(target, field, rec[field])
        target.save()
        return Response(MacroTargetSerializer(target).data)


class RecentFoodsView(APIView):
    """
    Returns foods previously logged by the user, deduplicated by food/name,
    ordered by most recent log date.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        entries = (
            MealEntry.objects.filter(nutrition_day__user=request.user)
            .select_related('food')
            .order_by('-nutrition_day__date', '-time_logged')
        )

        seen_keys = set()
        recent_foods = []

        for entry in entries:
            key = (entry.food_id, entry.name.strip().lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)

            if entry.food:
                recent_foods.append({
                    'id': str(entry.food.id),
                    'food_id': str(entry.food.id),
                    'name': entry.food.name,
                    'serving_label': entry.food.serving_label,
                    'serving_grams': entry.food.serving_grams,
                    'quantity': entry.servings,
                    'servings': entry.servings,
                    'calories': entry.food.calories,
                    'protein_g': entry.food.protein_g,
                    'carbs_g': entry.food.carbs_g,
                    'fat_g': entry.food.fat_g,
                    'meal_type': entry.meal_type,
                    'is_custom': entry.food.owner_id is not None,
                    'last_logged_date': str(entry.nutrition_day.date),
                })
            else:
                # Custom free-text entry
                unit_calories = round(entry.calories / (entry.servings or 1)) if entry.servings else entry.calories
                unit_protein = round(entry.protein_g / (entry.servings or 1), 1) if entry.servings else entry.protein_g
                unit_carbs = round(entry.carbs_g / (entry.servings or 1), 1) if entry.servings else entry.carbs_g
                unit_fat = round(entry.fat_g / (entry.servings or 1), 1) if entry.servings else entry.fat_g
                recent_foods.append({
                    'id': str(entry.id),
                    'food_id': None,
                    'name': entry.name,
                    'serving_label': f"{entry.servings:g} serving" if entry.servings and entry.servings != 1 else '1 serving',
                    'serving_grams': None,
                    'quantity': entry.servings,
                    'servings': entry.servings,
                    'calories': unit_calories,
                    'protein_g': unit_protein,
                    'carbs_g': unit_carbs,
                    'fat_g': unit_fat,
                    'meal_type': entry.meal_type,
                    'is_custom': True,
                    'last_logged_date': str(entry.nutrition_day.date),
                })

            if len(recent_foods) >= 20:
                break

        return Response(recent_foods)


class RepeatYesterdayView(APIView):
    """
    Copies meal entries from yesterday into target date (defaults to today).
    If meal_type is supplied (e.g. 'BREAKFAST'), only that meal type's entries are copied.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        meal_type = request.data.get('meal_type')
        target_date_str = request.data.get('date')
        if target_date_str:
            try:
                target_date = date.fromisoformat(target_date_str)
            except ValueError:
                target_date = date.today()
        else:
            target_date = date.today()

        yesterday = target_date - timedelta(days=1)
        yesterday_day = NutritionDay.objects.filter(user=request.user, date=yesterday).first()
        if not yesterday_day:
            return Response(
                {'detail': f'No nutrition log found for yesterday ({yesterday}).'},
                status=status.HTTP_404_NOT_FOUND
            )

        qs = yesterday_day.meals.all()
        if meal_type:
            qs = qs.filter(meal_type=meal_type)

        meals_to_copy = list(qs)
        if not meals_to_copy:
            meal_label = dict(MealEntry.MEAL_TYPES).get(meal_type, meal_type) if meal_type else 'meals'
            return Response(
                {'detail': f'No {meal_label.lower()} entries logged yesterday ({yesterday}) to repeat.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        today_day, _ = NutritionDay.objects.get_or_create(user=request.user, date=target_date)
        new_entries = []
        for m in meals_to_copy:
            new_entry = MealEntry.objects.create(
                nutrition_day=today_day,
                meal_type=m.meal_type,
                name=m.name,
                food=m.food,
                servings=m.servings,
                calories=m.calories,
                protein_g=m.protein_g,
                carbs_g=m.carbs_g,
                fat_g=m.fat_g,
            )
            new_entries.append(new_entry)

        return Response({
            'copied_count': len(new_entries),
            'meals': MealEntrySerializer(new_entries, many=True).data,
            'day': NutritionDaySerializer(today_day).data,
        }, status=status.HTTP_201_CREATED)
