"""Serialization rules (spec section 4.9).

Internal ``PlanTargets`` values are full-precision floats. This module is
the single, separate place where the final, display/API rounding happens
-- preview and the saved plan must both go through this function so they
match exactly.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from .domain import Macros, PlanTargets
from .rounding import round_half_up


def _round_places(x: Optional[float], places: int) -> Optional[float]:
    if x is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(x)).quantize(quantum, rounding=ROUND_HALF_UP))


def _kcal(x: Optional[float]) -> Optional[int]:
    return None if x is None else round_half_up(x)


def _macros_dict(m: Optional[Macros]) -> Optional[dict]:
    if m is None:
        return None
    return {
        "protein_g": round_half_up(m.protein_g),
        "fat_g": round_half_up(m.fat_g),
        "carbs_g": round_half_up(m.carbs_g),
    }


def serialize_plan_targets(targets: PlanTargets) -> dict:
    """API-response / stored-plan-record form of ``PlanTargets`` (4.9)."""
    return {
        "engine_version": targets.engine_version,
        "can_start": targets.can_start,
        "bmr": _kcal(targets.bmr),
        "activity_factor": _round_places(targets.activity_factor, 2),
        "tdee": _kcal(targets.tdee),
        "target_calories": _kcal(targets.target_calories),
        "calorie_delta": _kcal(targets.calorie_delta),
        "macros": _macros_dict(targets.macros),
        "precision": targets.precision,
        "predicted_weekly_change_kg": _round_places(targets.predicted_weekly_change_kg, 3),
        "predicted_total_change_kg": _round_places(targets.predicted_total_change_kg, 3),
        "projected_end_weight_kg": _round_places(targets.projected_end_weight_kg, 3),
        "weekly_change_pct_bodyweight": _round_places(targets.weekly_change_pct_bodyweight, 2),
        "requested_weekly_change_pct": _round_places(targets.requested_weekly_change_pct, 2),
        "days_needed": targets.days_needed,
        "override_source": targets.override_source,
        "suggested_calories": _kcal(targets.suggested_calories),
        "suggested_macros": _macros_dict(targets.suggested_macros),
        "pace_status": targets.pace_status,
        "calories_clamped": targets.calories_clamped,
        "messages": [
            {"code": m.code, "severity": m.severity, "params": dict(m.params)}
            for m in targets.messages
        ],
    }
