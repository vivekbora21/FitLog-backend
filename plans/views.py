from datetime import date
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction
from workouts.models import JourneyProgram, ProgramDay, Routine
from .models import Blueprint
from .serializers import BlueprintSerializer, PlanPreviewRequestSerializer, PlanCreateRequestSerializer
from .services.plan_generator import generate_roadmap

class PlanViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def _resolve_blueprint(self, data):
        blueprint_slug = data.get('blueprint_slug')
        if blueprint_slug:
            return Blueprint.objects.filter(slug=blueprint_slug, is_active=True).first()
        mode = data.get('mode')
        return Blueprint.objects.filter(mode=mode, is_active=True).order_by('display_order', 'name').first()

    @action(detail=False, methods=['get'], url_path='blueprints')
    def blueprints(self, request):
        qs = Blueprint.objects.filter(is_active=True)
        return Response({'blueprints': BlueprintSerializer(qs, many=True).data})

    @action(detail=False, methods=['post'], url_path='preview')
    def preview(self, request):
        serializer = PlanPreviewRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        blueprint = self._resolve_blueprint(data)
        if not blueprint:
            return Response({'detail': 'No matching blueprint found.'}, status=status.HTTP_400_BAD_REQUEST)

        roadmap = generate_roadmap(blueprint, data)
        return Response(roadmap)

    @transaction.atomic
    def create(self, request):
        serializer = PlanCreateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        blueprint = self._resolve_blueprint(data)
        if not blueprint:
            return Response({'detail': 'No matching blueprint found.'}, status=status.HTTP_400_BAD_REQUEST)

        roadmap = generate_roadmap(blueprint, data)
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
            start_date=date.today(),
            duration_days=duration_days,
            current_day=1,
            active=True,
            start_weight_kg=data['current_weight_kg'],
            target_weight_kg=goal_weight_kg,
            target_weekly_rate_kg=roadmap['summary']['weekly_rate_kg'],
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
            label = 'Rest Day' if day['is_rest'] else f"{day['phase']}"
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
