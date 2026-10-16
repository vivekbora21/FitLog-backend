from datetime import date, timedelta
from django.db import transaction, IntegrityError
from django.db.models import F
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.response import Response
from .models import MacroTarget, NutritionDay, MealEntry
from .serializers import MacroTargetSerializer, NutritionDaySerializer, MealEntrySerializer, FoodSerializer, foods_visible_to
from .targets import calculate_recommended_targets, get_or_create_macro_target, resolve_target_update, targets_payload, exercise_calories_today, TargetTimeline
from .indian_meals import meal_plan_options, TEMPLATES
from workouts.models import JourneyProgram

# BUG-31: a client-supplied log date had no server-side bound at all — a manipulated
# device clock/timezone could create or view entries for an arbitrary past or future
# date. Generous on purpose (years of real backfilling is legitimate; a bad clock is not).
MAX_LOG_DATE_PAST_YEARS = 5
MAX_LOG_DATE_FUTURE_DAYS = 1


class InvalidLogDate(ValueError):
    pass


def parse_bounded_log_date(date_str, today=None):
    """Parses a client-supplied YYYY-MM-DD date for nutrition logging, bounded to a
    plausible range around `today` (the server's resolved local today). Raises
    InvalidLogDate on a malformed string or an implausible date; callers turn that into a
    clean 400 instead of silently creating/looking up data for a nonsense date."""
    today = today or timezone.localdate()
    try:
        parsed = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        raise InvalidLogDate(f'Invalid date format: {date_str!r} (use YYYY-MM-DD).')
    earliest = today - timedelta(days=365 * MAX_LOG_DATE_PAST_YEARS)
    latest = today + timedelta(days=MAX_LOG_DATE_FUTURE_DAYS)
    if parsed < earliest or parsed > latest:
        raise InvalidLogDate(f'Date must be between {earliest.isoformat()} and {latest.isoformat()}.')
    return parsed


class NutritionDayView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, date_str=None):
        if not date_str or date_str == 'today':
            target_date = timezone.localdate()
        else:
            try:
                target_date = parse_bounded_log_date(date_str)
            except InvalidLogDate as err:
                return Response({'detail': str(err)}, status=status.HTTP_400_BAD_REQUEST)

        day, _ = NutritionDay.objects.get_or_create(user=request.user, date=target_date)
        target = TargetTimeline(request.user).on(target_date)

        yesterday = target_date - timedelta(days=1)
        yesterday_day = NutritionDay.objects.filter(user=request.user, date=yesterday).first()
        yesterday_meals = MealEntrySerializer(yesterday_day.meals.all(), many=True).data if yesterday_day else []

        program = JourneyProgram.objects.filter(user=request.user, active=True).first()
        profile = getattr(request.user, 'profile', None)

        mode = 'CUT'
        if program and program.mode:
            mode = program.mode
        elif profile and profile.fitness_goal:
            if profile.fitness_goal == 'FAT_LOSS':
                mode = 'CUT'
            elif profile.fitness_goal in ('HYPERTROPHY', 'STRENGTH'):
                mode = 'BULK'
            elif profile.fitness_goal in ('RECOMP',):
                mode = 'RECOMP'
            elif profile.fitness_goal in ('GENERAL_FITNESS', 'ENDURANCE'):
                mode = 'MAINTAIN'

        target_type = 'MAX' if mode == 'CUT' else ('MIN' if mode == 'BULK' else 'TARGET')
        mode_label = dict(JourneyProgram.MODE_CHOICES).get(
            mode, 'Cut Mode' if mode == 'CUT' else ('Bulk Mode' if mode == 'BULK' else mode.capitalize())
        )

        # Backend calculations for macro summary & breakdown
        consumed_calories = day.total_calories()
        consumed_protein = day.total_protein()
        consumed_carbs = day.total_carbs()
        consumed_fat = day.total_fat()
        consumed_water = day.water_consumed_ml

        target_calories = target.daily_calories
        target_protein = target.protein_g
        target_carbs = target.carbs_g
        target_fat = target.fat_g
        target_water = target.water_ml

        cal_pct = round((consumed_calories / max(1, target_calories)) * 100) if target_calories else 0
        pro_pct = round((consumed_protein / max(1, target_protein)) * 100) if target_protein else 0
        carbs_pct = round((consumed_carbs / max(1, target_carbs)) * 100) if target_carbs else 0
        fat_pct = round((consumed_fat / max(1, target_fat)) * 100) if target_fat else 0
        water_pct = round((consumed_water / max(1, target_water)) * 100) if target_water else 0

        pro_kcal = round(consumed_protein * 4)
        carbs_kcal = round(consumed_carbs * 4)
        fat_kcal = round(consumed_fat * 9)
        total_macro_kcal = max(1, pro_kcal + carbs_kcal + fat_kcal)

        pro_dist_pct = round((pro_kcal / total_macro_kcal) * 100)
        carbs_dist_pct = round((carbs_kcal / total_macro_kcal) * 100)
        fat_dist_pct = max(0, 100 - pro_dist_pct - carbs_dist_pct)

        # Reassuring non-punitive indicator:
        calorie_budget_intact = consumed_calories <= target_calories
        rec_targets = calculate_recommended_targets(request.user, target_date)

        macro_summary = {
            'calories': {
                'consumed': consumed_calories,
                'target': target_calories,
                'remaining': max(0, target_calories - consumed_calories),
                'excess': max(0, consumed_calories - target_calories),
                'percentage': cal_pct,
                'is_exceeded': consumed_calories > target_calories,
            },
            'protein': {
                'consumed': consumed_protein,
                'target': target_protein,
                'remaining': max(0.0, round(target_protein - consumed_protein, 1)),
                'excess': max(0.0, round(consumed_protein - target_protein, 1)),
                'percentage': pro_pct,
                'is_exceeded': consumed_protein > target_protein,
                'calories': pro_kcal,
                'pct_of_calories': pro_dist_pct,
            },
            'carbs': {
                'consumed': consumed_carbs,
                'target': target_carbs,
                'remaining': max(0.0, round(target_carbs - consumed_carbs, 1)),
                'excess': max(0.0, round(consumed_carbs - target_carbs, 1)),
                'percentage': carbs_pct,
                'is_exceeded': consumed_carbs > target_carbs,
                'calories': carbs_kcal,
                'pct_of_calories': carbs_dist_pct,
            },
            'fat': {
                'consumed': consumed_fat,
                'target': target_fat,
                'remaining': max(0.0, round(target_fat - consumed_fat, 1)),
                'excess': max(0.0, round(consumed_fat - target_fat, 1)),
                'percentage': fat_pct,
                'is_exceeded': consumed_fat > target_fat,
                'calories': fat_kcal,
                'pct_of_calories': fat_dist_pct,
            },
            'hydration': {
                'consumed_ml': consumed_water,
                'target_ml': target_water,
                'consumed_l': round(consumed_water / 1000.0, 2),
                'target_l': round(target_water / 1000.0, 2),
                'remaining_ml': max(0, target_water - consumed_water),
                'remaining_l': round(max(0, target_water - consumed_water) / 1000.0, 2),
                'percentage': water_pct,
            },
            'calorie_budget_intact': calorie_budget_intact,
        }

        macro_breakdown = {
            'total_calories': consumed_calories or total_macro_kcal,
            'protein_g': consumed_protein,
            'protein_pct': pro_dist_pct,
            'protein_kcal': pro_kcal,
            'carbs_g': consumed_carbs,
            'carbs_pct': carbs_dist_pct,
            'carbs_kcal': carbs_kcal,
            'fat_g': consumed_fat,
            'fat_pct': fat_dist_pct,
            'fat_kcal': fat_kcal,
        }

        return Response({
            'day': NutritionDaySerializer(day).data,
            'targets': {
                **MacroTargetSerializer(target).data,
                'exercise_calories': exercise_calories_today(request.user, target_date),
            },
            'macro_summary': macro_summary,
            'macro_breakdown': macro_breakdown,
            'target_derivation': rec_targets,
            'yesterday_meals': yesterday_meals,
            'plan': {
                'mode': mode,
                'mode_label': mode_label,
                'target_type': target_type,
                'program_name': program.name if program else None,
            },
        })

    def patch(self, request, date_str=None):
        if not date_str or date_str == 'today':
            target_date = timezone.localdate()
        else:
            try:
                target_date = parse_bounded_log_date(date_str)
            except InvalidLogDate as err:
                return Response({'detail': str(err)}, status=status.HTTP_400_BAD_REQUEST)
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
        if date_str:
            try:
                target_date = parse_bounded_log_date(date_str)
            except InvalidLogDate as err:
                raise DRFValidationError({'date': [str(err)]})
        else:
            target_date = timezone.localdate()
        day, _ = NutritionDay.objects.get_or_create(user=self.request.user, date=target_date)

        idempotency_key = serializer.validated_data.get('idempotency_key')
        if idempotency_key:
            existing = MealEntry.objects.filter(nutrition_day=day, idempotency_key=idempotency_key).first()
            if existing:
                serializer.instance = existing
                return

        try:
            with transaction.atomic():
                serializer.save(nutrition_day=day)
        except IntegrityError:
            # A concurrent retry with the same key won the race between our check above
            # and this insert — replay its entry instead of failing.
            if idempotency_key:
                existing = MealEntry.objects.filter(nutrition_day=day, idempotency_key=idempotency_key).first()
                if existing:
                    serializer.instance = existing
                    return
            raise

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


class MealPlanOptionsView(APIView):
    """Real, Indian meal-plan options scaled to the member's own calorie/
    protein target (`calculate_recommended_targets`, falling back to their
    saved `MacroTarget` if the profile is incomplete) -- replaces the fixed
    Western day totals baked into `plans.Blueprint.meal_templates`. Returns
    every template for the requested diet preference (2 per preference) so
    the member picks one, rather than being handed a single generated plan.

    GET params: `diet_preference` (VEG/EGG/NON_VEG, optional -- defaults to
    the member's profile value; omit entirely, including an unrecognised
    value, to get options across all three)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        recommended = calculate_recommended_targets(request.user)
        if recommended['available']:
            target_calories = recommended['daily_calories']
            target_protein_g = recommended['protein_g']
        else:
            target = get_or_create_macro_target(request.user)
            target_calories = target.daily_calories
            target_protein_g = target.protein_g

        diet_preference = request.query_params.get('diet_preference')
        if diet_preference not in TEMPLATES:
            profile = getattr(request.user, 'profile', None)
            diet_preference = profile.diet_preference if profile else None

        return Response({
            'target_calories': target_calories,
            'target_protein_g': target_protein_g,
            'diet_preference': diet_preference if diet_preference in TEMPLATES else None,
            'options': meal_plan_options(target_calories, target_protein_g, diet_preference),
        })


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
                target_date = parse_bounded_log_date(target_date_str)
            except InvalidLogDate as err:
                return Response({'detail': str(err)}, status=status.HTTP_400_BAD_REQUEST)
        else:
            target_date = timezone.localdate()

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


class NutritionHistoryView(APIView):
    """
    Returns a daily stream of nutrition history for the user,
    with totals, targets, meals summary, and journey program day alignment.
    Accepts ?days=N (default 30, max 90).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        range_param = request.query_params.get('range')
        range_map = {'7D': 7, '30D': 30, '90D': 90}
        if range_param in range_map:
            days = range_map[range_param]
        else:
            try:
                days = int(request.query_params.get('days', 30))
            except (ValueError, TypeError):
                days = 30
        days = min(max(1, days), 90)

        today = timezone.localdate()
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        try:
            range_start = date.fromisoformat(date_from) if date_from else today - timedelta(days=days - 1)
            range_end = date.fromisoformat(date_to) if date_to else today
        except ValueError:
            return Response({'detail': 'date_from and date_to must use YYYY-MM-DD.'}, status=400)
        start_date = min(range_start, range_end)
        today = min(max(range_end, start_date), timezone.localdate())

        # Prefetch days and meals for user in range
        nutrition_days = (
            NutritionDay.objects.filter(
                user=request.user,
                date__gte=start_date,
                date__lte=today,
            )
            .prefetch_related('meals')
            .order_by('-date')
        )
        nutrition_days_map = {nd.date: nd for nd in nutrition_days}

        timeline = TargetTimeline(request.user)
        program = JourneyProgram.objects.filter(user=request.user, active=True).first()
        profile = getattr(request.user, 'profile', None)

        mode = 'CUT'
        if program and program.mode:
            mode = program.mode
        elif profile and profile.fitness_goal:
            if profile.fitness_goal == 'FAT_LOSS':
                mode = 'CUT'
            elif profile.fitness_goal in ('HYPERTROPHY', 'STRENGTH'):
                mode = 'BULK'
            elif profile.fitness_goal in ('RECOMP',):
                mode = 'RECOMP'
            elif profile.fitness_goal in ('GENERAL_FITNESS', 'ENDURANCE'):
                mode = 'MAINTAIN'

        target_type = 'MAX' if mode == 'CUT' else ('MIN' if mode == 'BULK' else 'TARGET')
        mode_label = dict(JourneyProgram.MODE_CHOICES).get(
            mode, 'Cut Mode' if mode == 'CUT' else ('Bulk Mode' if mode == 'BULK' else mode.capitalize())
        )

        history_list = []
        for i in range(days):
            d = today - timedelta(days=i)
            nd = nutrition_days_map.get(d)
            day_target = timeline.on(d)

            prog_day_num = None
            if program and program.start_date:
                diff_days = (d - program.start_date).days
                day_num = diff_days + 1
                if 1 <= day_num <= program.duration_days:
                    prog_day_num = day_num

            meals_data = []
            if nd:
                for m in nd.meals.all():
                    meals_data.append({
                        'id': str(m.id),
                        'name': m.name,
                        'meal_type': m.meal_type,
                        'calories': m.calories,
                        'protein_g': m.protein_g,
                        'carbs_g': m.carbs_g,
                        'fat_g': m.fat_g,
                        'servings': m.servings,
                    })

            history_list.append({
                'date': d.isoformat(),
                'program_day_number': prog_day_num,
                'total_calories': nd.total_calories() if nd else 0,
                'total_protein': nd.total_protein() if nd else 0.0,
                'total_carbs': nd.total_carbs() if nd else 0.0,
                'total_fat': nd.total_fat() if nd else 0.0,
                'water_consumed_ml': nd.water_consumed_ml if nd else 0,
                'meal_count': len(meals_data),
                'meals': meals_data,
                'has_logged': bool(meals_data or (nd and nd.water_consumed_ml > 0)),
                'target_calories': day_target.daily_calories,
                'target_protein': day_target.protein_g,
                'target_carbs': day_target.carbs_g,
                'target_fat': day_target.fat_g,
                'target_water': day_target.water_ml,
                'target_type': target_type,
                'mode': mode,
            })

        # Calculate weekly nutrition summaries (Monday-Sunday weeks)
        weeks = build_weekly_nutrition_summaries(history_list, today, mode, target_type, timeline)

        # Precalculate period analytics in backend
        logged_items = [h for h in history_list if h['has_logged']]
        logged_count = len(logged_items)
        avg_cal = round(sum(h['total_calories'] for h in logged_items) / logged_count) if logged_count else 0
        avg_pro = round(sum(h['total_protein'] for h in logged_items) / logged_count, 1) if logged_count else 0.0
        avg_carbs = round(sum(h['total_carbs'] for h in logged_items) / logged_count, 1) if logged_count else 0.0
        avg_fat = round(sum(h['total_fat'] for h in logged_items) / logged_count, 1) if logged_count else 0.0
        avg_water = round(sum(h['water_consumed_ml'] for h in logged_items) / logged_count) if logged_count else 0

        latest_target = timeline.current
        period_analytics = {
            'range': f"{days}D",
            'total_days': days,
            'logged_days_count': logged_count,
            'avg_calories': avg_cal,
            'avg_protein': avg_pro,
            'avg_carbs': avg_carbs,
            'avg_fat': avg_fat,
            'avg_water_ml': avg_water,
            'target_calories': latest_target.daily_calories,
            'target_protein': latest_target.protein_g,
            'target_carbs': latest_target.carbs_g,
            'target_fat': latest_target.fat_g,
            'target_water_ml': latest_target.water_ml,
            'calorie_adherence_pct': round((avg_cal / max(1, latest_target.daily_calories)) * 100) if logged_count else 0,
        }

        return Response({
            'history': history_list,
            'weeks': weeks,
            'analytics': period_analytics,
            'targets': MacroTargetSerializer(timeline.current).data,
            'program': {
                'start_date': program.start_date.isoformat() if program and program.start_date else None,
                'duration_days': program.duration_days if program else 30,
                'name': program.name if program else 'Fitness Journey',
                'mode': mode,
                'target_type': target_type,
            } if program else None,
            'plan': {
                'mode': mode,
                'mode_label': mode_label,
                'target_type': target_type,
            },
        })


def build_weekly_nutrition_summaries(history_list, today, mode, target_type, timeline):
    history_by_date = {item['date']: item for item in history_list}
    current_monday = today - timedelta(days=today.weekday())
    earliest_date_str = history_list[-1]['date'] if history_list else today.isoformat()
    earliest_date = date.fromisoformat(earliest_date_str)
    earliest_monday = earliest_date - timedelta(days=earliest_date.weekday())

    weeks = []
    w_monday = current_monday
    week_idx = 0

    while w_monday >= earliest_monday:
        w_sunday = w_monday + timedelta(days=6)
        days_in_week = []
        for i in range(7):
            d = w_monday + timedelta(days=i)
            d_str = d.isoformat()
            hist_item = history_by_date.get(d_str)
            is_future = d > today
            is_today = d == today

            if hist_item:
                days_in_week.append({
                    'date': d_str,
                    'weekday': d.strftime('%a'),
                    'day_number': d.day,
                    'total_calories': hist_item['total_calories'],
                    'total_protein': hist_item['total_protein'],
                    'total_carbs': hist_item['total_carbs'],
                    'total_fat': hist_item['total_fat'],
                    'water_consumed_ml': hist_item['water_consumed_ml'],
                    'has_logged': hist_item['has_logged'],
                    'is_today': is_today,
                    'is_future': is_future,
                    'target_calories': hist_item['target_calories'],
                })
            else:
                # Outside the fetched history range (e.g. the oldest partial week, whose
                # Monday predates the requested window) — still resolve this day's real
                # target from the user's target history instead of a fixed fallback value.
                days_in_week.append({
                    'date': d_str,
                    'weekday': d.strftime('%a'),
                    'day_number': d.day,
                    'total_calories': 0,
                    'total_protein': 0.0,
                    'total_carbs': 0.0,
                    'total_fat': 0.0,
                    'water_consumed_ml': 0,
                    'has_logged': False,
                    'is_today': is_today,
                    'is_future': is_future,
                    'target_calories': timeline.on(d).daily_calories,
                })

        logged_days = [d for d in days_in_week if d['has_logged']]
        logged_count = len(logged_days)

        avg_calories = round(sum(d['total_calories'] for d in logged_days) / logged_count) if logged_count > 0 else 0
        avg_protein = round(sum(d['total_protein'] for d in logged_days) / logged_count, 1) if logged_count > 0 else 0.0
        avg_carbs = round(sum(d['total_carbs'] for d in logged_days) / logged_count, 1) if logged_count > 0 else 0.0
        avg_fat = round(sum(d['total_fat'] for d in logged_days) / logged_count, 1) if logged_count > 0 else 0.0
        avg_water_ml = round(sum(d['water_consumed_ml'] for d in logged_days) / logged_count) if logged_count > 0 else 0

        first_day_hist = next((history_by_date.get((w_monday + timedelta(days=i)).isoformat()) for i in range(7) if (w_monday + timedelta(days=i)).isoformat() in history_by_date), None)
        # In practice every week in this loop overlaps the fetched history range (it's
        # derived from that same range's bounds), so first_day_hist is always found — but
        # if that ever stops holding, resolve the week's real target instead of a fixed
        # placeholder rather than silently showing a number that isn't this user's target.
        week_target = timeline.on(w_monday)
        t_cal = first_day_hist['target_calories'] if first_day_hist else week_target.daily_calories
        t_pro = first_day_hist['target_protein'] if first_day_hist else week_target.protein_g
        t_carb = first_day_hist['target_carbs'] if first_day_hist else week_target.carbs_g
        t_fat = first_day_hist['target_fat'] if first_day_hist else week_target.fat_g
        t_water = first_day_hist['target_water'] if first_day_hist else week_target.water_ml

        cal_diff = avg_calories - t_cal if logged_count > 0 else 0
        net_calorie_diff = cal_diff * logged_count

        cal_adherence = round((avg_calories / max(1, t_cal)) * 100) if logged_count > 0 else 0
        pro_adherence = round((avg_protein / max(1, t_pro)) * 100) if logged_count > 0 else 0
        adherence_rate = round((logged_count / 7) * 100)

        if week_idx == 0:
            label = "This Week"
        elif week_idx == 1:
            label = "Last Week"
        else:
            label = f"{w_monday.strftime('%b %d')} – {w_sunday.strftime('%b %d')}"

        if logged_count == 0:
            copilot_insight = "No meals logged yet for this week. Start logging your fuel to track weekly averages."
        elif mode == 'CUT':
            if avg_calories <= t_cal:
                copilot_insight = f"Weekly avg {avg_calories:,} kcal is {abs(cal_diff):,} kcal below your {t_cal:,} kcal ceiling. Deficit on track across {logged_count} logged day{'s' if logged_count > 1 else ''}!"
            else:
                copilot_insight = f"Weekly avg {avg_calories:,} kcal is {cal_diff:,} kcal above deficit ceiling. Aim to tighten remaining days to protect your deficit."
        elif mode == 'BULK':
            if avg_calories >= t_cal:
                copilot_insight = f"Weekly avg {avg_calories:,} kcal meets your {t_cal:,} kcal surplus floor. Growth targets hit across {logged_count} day{'s' if logged_count > 1 else ''}!"
            else:
                copilot_insight = f"Weekly avg {avg_calories:,} kcal is {abs(cal_diff):,} kcal below your minimum floor. Lift intake to sustain muscle hypertrophy."
        else:
            copilot_insight = f"Weekly avg {avg_calories:,} kcal ({cal_adherence}% of target) with {avg_protein}g protein across {logged_count}/7 logged days."

        weeks.append({
            'week_start': w_monday.isoformat(),
            'week_end': w_sunday.isoformat(),
            'label': label,
            'logged_count': logged_count,
            'total_days': 7,
            'avg_calories': avg_calories,
            'avg_protein': avg_protein,
            'avg_carbs': avg_carbs,
            'avg_fat': avg_fat,
            'avg_water_ml': avg_water_ml,
            'target_calories': t_cal,
            'target_protein': t_pro,
            'target_carbs': t_carb,
            'target_fat': t_fat,
            'target_water': t_water,
            'net_calorie_diff': net_calorie_diff,
            'calorie_adherence_pct': cal_adherence,
            'protein_adherence_pct': pro_adherence,
            'adherence_rate_pct': adherence_rate,
            'copilot_insight': copilot_insight,
            'days': days_in_week,
        })

        w_monday -= timedelta(days=7)
        week_idx += 1

    return weeks
