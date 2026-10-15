from datetime import date
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction
from workouts.models import JourneyProgram, ProgramDay, Routine
from exercises.models import Exercise
from .models import Blueprint, TrainingSplit
from .serializers import (
    BlueprintSerializer, TrainingSplitSerializer,
    PlanPreviewRequestSerializer, PlanCreateRequestSerializer, PlanOptionsRequestSerializer,
    GoalWeightRecommendationRequestSerializer,
)
from .services import plan_generator
from .services.exercise_lookup import muscle_group_by_exercise_name
from .services.plan_generator import generate_roadmap
from .split_approval import (
    DAYS_TO_SPLIT_SLUGS, DEFAULT_EQUIPMENT_LEVEL, approved_combinations, approved_slugs_for,
    is_split_approved, is_catalog_complete,
)

NO_SUPPORTED_SPLIT_CODE = 'NO_SUPPORTED_SPLIT'

class PlanViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def _resolve_blueprint(self, data):
        blueprint_slug = data.get('blueprint_slug')
        if blueprint_slug:
            return Blueprint.objects.filter(slug=blueprint_slug, is_active=True).first()
        mode = data.get('mode')
        return Blueprint.objects.filter(mode=mode, is_active=True).order_by('display_order', 'name').first()

    def _resolve_training_split(self, data):
        split_slug = data.get('split_slug')
        if split_slug:
            return TrainingSplit.objects.filter(slug=split_slug, is_active=True).first()
        equipment_level = data.get('equipment_level') or DEFAULT_EQUIPMENT_LEVEL
        days_per_week = data.get('days_per_week')
        for slug in approved_slugs_for(days_per_week, equipment_level):
            split = TrainingSplit.objects.filter(slug=slug, is_active=True).first()
            if split and is_catalog_complete(split):
                return split
        return None

    def _generate_roadmap(self, blueprint, data, training_split):
        """Builds the exercise -> muscle-group lookup the volume check
        (spec v1.6 section 6.4) needs from the real `Exercise` catalog, then
        delegates to the (otherwise DB-free) `generate_roadmap`. Kept here
        rather than inside `plan_generator.py`, whose own module docstring
        says it does no database access at all."""
        _, workout_templates = plan_generator.resolve_workout_templates(blueprint, training_split)
        exercise_names = plan_generator.exercise_names_in_workout_templates(workout_templates)
        muscle_map = muscle_group_by_exercise_name(exercise_names)
        # In a fully seeded environment, an approved template must resolve
        # every exercise against the active global library. The empty-library
        # escape hatch keeps legacy development/test fixtures usable before
        # the exercise seed command has run.
        if Exercise.objects.filter(gym__isnull=True).exists() and muscle_map:
            missing = sorted(exercise_names - set(muscle_map))
            if missing:
                raise ValueError(f"Template references unavailable exercises: {', '.join(missing)}")
        return generate_roadmap(blueprint, data, training_split=training_split, muscle_group_by_exercise=muscle_map)

    def _no_supported_split_payload(self, days_per_week, equipment_level):
        return {
            'code': NO_SUPPORTED_SPLIT_CODE,
            'detail': (
                f"No supported training split exists for {days_per_week} days/week "
                f"at '{equipment_level}' equipment."
            ),
            'supported_combinations': approved_combinations(),
        }

    def _check_split_approval(self, data):
        """Spec v1.6 section 6.7 bullets 2-3 (V-21 NO_SUPPORTED_SPLIT): the
        release gate. Returns a NO_SUPPORTED_SPLIT payload dict if the
        requested (or, absent an explicit split_slug, auto-selected) split
        for this days_per_week/equipment_level combination isn't in
        SPLIT_APPROVAL, else None.

        - If the client named a specific, existing split_slug, that exact
          split must be approved at the requested equipment_level.
        - Otherwise (no split_slug -- the existing fallback to the
          blueprint's own default_training_split/workout_templates), at
          least one TrainingSplit for the requested days_per_week must be
          approved at the requested equipment_level, or there is nothing
          this release can legitimately offer for that combination.
        """
        equipment_level = data.get('equipment_level') or DEFAULT_EQUIPMENT_LEVEL
        days_per_week = data.get('days_per_week')
        split_slug = data.get('split_slug')

        if split_slug:
            split = TrainingSplit.objects.filter(slug=split_slug, is_active=True).first()
            if split is not None and (not is_split_approved(split.slug, equipment_level) or not is_catalog_complete(split)):
                return self._no_supported_split_payload(days_per_week, equipment_level)
            return None

        available_catalog_rows = TrainingSplit.objects.filter(days_per_week=days_per_week, is_active=True)
        # Keep legacy callers working in installations that have not run the
        # split seed command yet; once catalog rows exist, fail closed.
        if days_per_week and available_catalog_rows.exists() and not any(
            is_catalog_complete(split)
            for split in available_catalog_rows
            if is_split_approved(split.slug, equipment_level)
        ):
            return self._no_supported_split_payload(days_per_week, equipment_level)
        return None

    @action(detail=False, methods=['get'], url_path='blueprints')
    def blueprints(self, request):
        qs = Blueprint.objects.filter(is_active=True)
        return Response({'blueprints': BlueprintSerializer(qs, many=True).data})

    @action(detail=False, methods=['get'], url_path='splits')
    def splits(self, request):
        equipment_level = request.query_params.get('equipment_level') or DEFAULT_EQUIPMENT_LEVEL
        days = request.query_params.get('days_per_week')
        qs = TrainingSplit.objects.filter(is_active=True, approval_status='APPROVED')
        if days:
            qs = qs.filter(days_per_week=days)
        qs = [split for split in qs if is_split_approved(split.slug, equipment_level) and is_catalog_complete(split)]
        return Response({'splits': TrainingSplitSerializer(qs, many=True).data})

    @action(detail=False, methods=['post'], url_path='preview')
    def preview(self, request):
        serializer = PlanPreviewRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        blueprint = self._resolve_blueprint(data)
        if not blueprint:
            return Response({'detail': 'No matching blueprint found.'}, status=status.HTTP_400_BAD_REQUEST)

        if data.get('split_slug') and not self._resolve_training_split(data):
            return Response({'detail': 'No matching training split found.'}, status=status.HTTP_400_BAD_REQUEST)

        split_error = self._check_split_approval(data)
        if split_error:
            return Response({'can_start': False, **split_error}, status=status.HTTP_200_OK)

        try:
            roadmap = self._generate_roadmap(blueprint, data, self._resolve_training_split(data))
        except ValueError as exc:
            return Response({'detail': str(exc), 'code': 'INVALID_EXERCISE_REFERENCE'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(roadmap)

    @action(detail=False, methods=['post'], url_path='recommended-goal-weight', permission_classes=[permissions.AllowAny])
    def recommended_goal_weight(self, request):
        serializer = GoalWeightRecommendationRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        goal_weight_kg = plan_generator.recommend_goal_weight(
            mode=data['mode'],
            current_weight_kg=data['current_weight_kg'],
            height_cm=data['height_cm'],
            duration_days=data['duration_days'],
        )
        return Response({'goal_weight_kg': goal_weight_kg})

    @action(detail=False, methods=['post'], url_path='options')
    def options(self, request):
        """"Choose from multiple" entry point: instead of the caller picking
        one days_per_week/split up front (`preview`/`create` always resolve
        to exactly one generated plan), this computes one full preview per
        approved (days_per_week, split) combination at the member's
        equipment level and mode, so the client can show them side by side
        before the member commits to one via `create`."""
        serializer = PlanOptionsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        mode = data['mode']
        equipment_level = data.get('equipment_level') or DEFAULT_EQUIPMENT_LEVEL
        blueprint = Blueprint.objects.filter(mode=mode, is_active=True).order_by('display_order', 'name').first()
        if not blueprint:
            return Response({'detail': 'No matching blueprint found.'}, status=status.HTTP_400_BAD_REQUEST)

        options = []
        for days_per_week, slugs in DAYS_TO_SPLIT_SLUGS.items():
            if data.get('days_per_week') and data['days_per_week'] != days_per_week:
                continue
            for slug in slugs:
                if not is_split_approved(slug, equipment_level):
                    continue
                split = TrainingSplit.objects.filter(slug=slug, is_active=True).first()
                if not split or not is_catalog_complete(split):
                    continue
                if data.get('experience') not in (split.experience_levels or ['BEGINNER', 'INTERMEDIATE', 'ADVANCED']):
                    continue
                if mode not in (split.compatible_goals or [mode]):
                    continue
                if data.get('session_duration_minutes') and split.estimated_session_minutes > data['session_duration_minutes']:
                    continue
                option_inputs = {**data, 'days_per_week': days_per_week, 'split_slug': slug}
                try:
                    roadmap = self._generate_roadmap(blueprint, option_inputs, split)
                except ValueError:
                    continue
                options.append({
                    'split_slug': slug,
                    'split_name': split.name,
                    'split_description': split.description,
                    'days_per_week': days_per_week,
                    'summary': roadmap['summary'],
                    'engine': roadmap['engine'],
                    'estimated_session_minutes': split.estimated_session_minutes,
                    'experience_levels': split.experience_levels,
                    'compatible_goals': split.compatible_goals,
                    'equipment_requirements': split.equipment_requirements,
                    'muscle_groups': split.muscle_groups,
                })

        if not options:
            return Response({
                'can_start': False,
                'code': NO_SUPPORTED_SPLIT_CODE,
                'detail': f"No supported training split exists at '{equipment_level}' equipment.",
                'supported_combinations': approved_combinations(),
            }, status=status.HTTP_200_OK)
        # Stable ranking is shared by both clients: experience-fit first, then
        # shorter sessions, with the catalog order as the final tie-breaker.
        options.sort(key=lambda option: (option['estimated_session_minutes'], option['days_per_week'], option['split_slug']))
        primary = options[0]
        primary['is_recommended'] = True
        primary['recommendation_reason'] = (
            f"Matches your {data.get('experience', 'INTERMEDIATE').lower()} experience, "
            f"{mode.lower()} goal, and available equipment."
        )
        return Response({'mode': mode, 'equipment_level': equipment_level, 'recommended': primary['split_slug'], 'options': options})

    @transaction.atomic
    def create(self, request):
        serializer = PlanCreateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        blueprint = self._resolve_blueprint(data)
        if not blueprint:
            return Response({'detail': 'No matching blueprint found.'}, status=status.HTTP_400_BAD_REQUEST)

        if data.get('split_slug') and not self._resolve_training_split(data):
            return Response({'detail': 'No matching training split found.'}, status=status.HTTP_400_BAD_REQUEST)

        split_error = self._check_split_approval(data)
        if split_error:
            return Response(split_error, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        try:
            roadmap = self._generate_roadmap(blueprint, data, self._resolve_training_split(data))
        except ValueError as exc:
            return Response({'can_start': False, 'code': 'INVALID_EXERCISE_REFERENCE', 'detail': str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        engine_meta = roadmap['engine']

        # Spec v1.6 section 5 (closing line): "every block rule returns
        # can_start = false from preview and HTTP 422 from the save
        # endpoint, with the stable code." Most block conditions (missing
        # goal weight, trivial-goal-delta, bad mode/blueprint) are already
        # rejected earlier (400) by the request serializer itself, but a few
        # -- notably the 4.8/4.10 override rules V-22 OVERRIDE_MODE_REQUIRED
        # and V-23 OVERRIDE_CONFLICT -- can only be detected by the engine
        # itself. Checked (and, crucially, placed) before the active-journey
        # archiving below, so a rejected create has no side effects.
        if not engine_meta.get('can_start', True):
            block_messages = [m for m in engine_meta['messages'] if m['severity'] == 'block']
            return Response({
                'can_start': False,
                'code': block_messages[0]['code'] if block_messages else None,
                'messages': engine_meta['messages'],
            }, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        user = request.user
        duration_days = data['duration_days']
        goal_weight_kg = data.get('goal_weight_kg')
        name = data.get('name') or blueprint.name

        # Non-destructive archiving of any existing active journey, matching start_journey's approach.
        JourneyProgram.objects.filter(user=user, active=True).update(
            active=False, archived_at=timezone.now()
        )

        new_program = JourneyProgram.objects.create(
            user=user,
            name=name,
            mode=blueprint.mode,
            # Spec v1.6 section 6.6: the plan's actual first scheduled day,
            # not necessarily "today" -- generate_roadmap snaps it forward
            # to the first selected training weekday on or after today when
            # no explicit start_date was requested (see
            # plan_generator._resolve_anchor_date).
            start_date=roadmap['summary']['start_date'],
            duration_days=duration_days,
            current_day=1,
            active=True,
            start_weight_kg=data['current_weight_kg'],
            target_weight_kg=goal_weight_kg,
            target_weekly_rate_kg=roadmap['summary']['weekly_rate_kg'],
            # --- Plan-engine fields (spec v1.6 section 7.1, migration 0013) ---
            engine_version=engine_meta['engine_version'],
            inputs=engine_meta['inputs'],
            target_calories=engine_meta['target_calories'],
            target_protein_g=engine_meta['target_protein_g'],
            target_fat_g=engine_meta['target_fat_g'],
            target_carbs_g=engine_meta['target_carbs_g'],
            activity_factor=engine_meta['activity_factor'],
            predicted_weekly_change_kg=engine_meta['predicted_weekly_change_kg'],
            precision=engine_meta['precision'],
            # Spec v1.6 section 4.8: the override as submitted (None if none
            # was active) -- `can_start` was already checked above, so by
            # this point any override present was validated and applied by
            # the engine for the current mode.
            calorie_override=data.get('calorie_override'),
            macro_override_protein_g=(data.get('macro_override') or {}).get('protein_g'),
            macro_override_fat_g=(data.get('macro_override') or {}).get('fat_g'),
            macro_override_carbs_g=(data.get('macro_override') or {}).get('carbs_g'),
        )

        # Every ProgramDay.routine is a required, protected FK; the actual guided-plan
        # content lives in the new JSON payload fields instead, so this routine is
        # intentionally left without RoutineExercise children.
        placeholder_routine = Routine.objects.create(
            user=user,
            name=f"{new_program.name} Plan",
            description='Auto-generated for a guided plan.',
        )

        program_days = []
        for day in roadmap['days']:
            workout = day['workout']
            # Spec v1.6 section 6.6: real weekday + date + session name
            # (e.g. "Mon 13 Oct: Foundation"), computed by generate_roadmap
            # -- replaces the old phase-name-only label.
            label = day['label']
            program_days.append(ProgramDay(
                program=new_program,
                day_number=day['day_number'],
                routine=placeholder_routine,
                label=label,
                is_optional=day['is_rest'],
                status='UPCOMING',
                workout_payload=workout,
                meal_payload=roadmap['meal_template'],
                macro_targets=day['targets'],
                expected_weight_kg=day['expected_weight_kg'],
            ))
        ProgramDay.objects.bulk_create(program_days)

        return Response({
            'message': f"Journey successfully started: {new_program.name}",
            'program': {
                'id': str(new_program.id),
                'name': new_program.name,
                'mode': new_program.mode,
                'mode_label': dict(JourneyProgram.MODE_CHOICES).get(new_program.mode, new_program.mode),
                'start_date': str(new_program.start_date),
                'duration_days': new_program.duration_days,
                'current_day': 1,
                'start_weight_kg': new_program.start_weight_kg,
                'target_weight_kg': new_program.target_weight_kg,
                'target_weekly_rate_kg': new_program.target_weekly_rate_kg,
            },
            'roadmap': roadmap,
        }, status=status.HTTP_201_CREATED)
