"""Pure-Python plan calculation engine (FitLog Plan Builder spec v1.6, section 4-5).

This package has NO Django/DB dependency and no wall-clock access. It is
importable and testable without a database. It is deliberately NOT wired
into any existing view, serializer or the ``plans`` app in this pass -- see
the implementation report for what is deferred.

Public entry point: :func:`compute_plan_targets`.
"""

from .domain import (
    Mode,
    Experience,
    Equipment,
    RecompDirection,
    MacroOverride,
    Macros,
    Message,
    PlanInputs,
    PlanTargets,
)
from .engine import compute_plan_targets
from .serialization import serialize_plan_targets
from .rounding import round_half_up

__all__ = [
    "Mode",
    "Experience",
    "Equipment",
    "RecompDirection",
    "MacroOverride",
    "Macros",
    "Message",
    "PlanInputs",
    "PlanTargets",
    "compute_plan_targets",
    "serialize_plan_targets",
    "round_half_up",
]
