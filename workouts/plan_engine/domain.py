"""Domain model for the plan engine (spec section 3).

Plain dataclasses/enums, adapted from the spec's Python-ish pseudocode to
concrete Python. No Django imports here.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Literal, Optional


class Mode(str, Enum):
    CUT = "cut"
    BULK = "bulk"
    RECOMP = "recomp"
    FOCUS = "focus"
    # Treated identically to FOCUS throughout engine.py (same maintenance
    # formula, same precision, same null predicted/pace fields, same protein
    # g/kg) -- kept as its own enum member (not aliased to FOCUS) so
    # JourneyProgram.mode round-trips losslessly. See config.py and the
    # implementation report.
    HABIT = "habit"


class Experience(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class Equipment(str, Enum):
    FULL_GYM = "full_gym"
    HOME_BASIC = "home_basic"
    MINIMAL = "minimal"


class RecompDirection(str, Enum):
    LEAN_OUT = "lean_out"
    MAINTAIN = "maintain"
    LEAN_GAIN = "lean_gain"


Severity = Literal["block", "warn", "info"]
Precision = Literal["calorie_projected", "directional", "maintenance"]
PaceStatus = Literal["gentle", "typical", "aggressive", "not_applicable"]
OverrideSource = Literal["calories", "macros"]


@dataclass(frozen=True)
class MacroOverride:
    protein_g: int
    fat_g: int
    carbs_g: int


@dataclass(frozen=True)
class Macros:
    protein_g: int
    fat_g: int
    carbs_g: int


@dataclass(frozen=True)
class Message:
    code: str
    severity: Severity
    params: Dict = field(default_factory=dict)

    def __eq__(self, other):
        if not isinstance(other, Message):
            return NotImplemented
        return (
            self.code == other.code
            and self.severity == other.severity
            and self.params == other.params
        )


@dataclass(frozen=True)
class PlanInputs:
    mode: Mode
    sex: Literal["male", "female"]
    age: int
    height_cm: float
    weight_kg: float
    goal_weight_kg: Optional[float]
    duration_days: int                     # 7..365
    days_per_week: int                     # 3..6
    training_weekdays: List[int]            # 0=Mon .. 6=Sun, len == days_per_week
    experience: Experience
    equipment: Equipment
    recomp_direction: Optional[RecompDirection] = None   # only used when mode == RECOMP
    calorie_override: Optional[int] = None
    macro_override: Optional[MacroOverride] = None
    override_for_mode: Optional[Mode] = None  # required whenever either override is present
    split_id: Optional[str] = None            # None = use the recommended split


@dataclass(frozen=True)
class PlanTargets:
    # Internal values are full-precision floats unless typed int; see
    # serialization.py (4.9) for the final rounded/serialized form.
    engine_version: str
    can_start: bool
    bmr: float
    activity_factor: float
    tdee: float
    # None only when the mode requires a goal weight (Cut/Bulk) that is
    # missing, and no override supplies calories either -- see engine.py
    # and the implementation report for this judgment call.
    target_calories: Optional[int]
    calorie_delta: Optional[float]           # target_calories - tdee, full precision
    macros: Optional[Macros]
    precision: Precision
    predicted_weekly_change_kg: Optional[float]
    predicted_total_change_kg: Optional[float]
    projected_end_weight_kg: Optional[float]
    weekly_change_pct_bodyweight: Optional[float]   # FINAL pace, from target_calories
    requested_weekly_change_pct: Optional[float]    # REQUESTED pace, from goal and duration
    days_needed: Optional[int]
    override_source: Optional[OverrideSource]
    suggested_calories: Optional[int]
    suggested_macros: Optional[Macros]
    pace_status: PaceStatus
    calories_clamped: bool
    messages: List[Message] = field(default_factory=list)
