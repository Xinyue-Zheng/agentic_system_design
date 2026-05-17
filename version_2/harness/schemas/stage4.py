from pydantic import BaseModel, Field
from typing import Literal, List
from enum import Enum


# ── Stage 4 ───────────────────────────────────────────────────

class ImpactSeverity(str, Enum):
    low = "low"
    moderate = "moderate"
    high = "high"
    critical = "critical"

class OverallRating(BaseModel):
    impact_severity: ImpactSeverity
    user_impact_level: int = Field(ge=1, le=4)
    confidence: Literal["low", "medium", "high"]

class ConstraintCheck(BaseModel):
    C1_applied: bool
    C1_note: str
    C2_applied: bool
    C2_note: str
    C3_applied: bool
    C3_note: str
    C4_applied: bool
    C4_note: str
    C5_applied: bool
    C5_note: str

class Stage4Output(BaseModel):
    target_usid: str
    shutdown_start: str
    shutdown_end: str
    shutdown_duration_hours: float = Field(ge=0)
    overall_rating: OverallRating
    impact_breakdown: dict
    constraint_check: ConstraintCheck
    most_affected_zones: List[dict]
    main_reasons: List[str] = Field(min_items=2, max_items=5)
    mitigating_factors: List[str]
    final_conclusion: str = Field(min_length=50)

    class Config:
        extra = "forbid"


# ── Stage 5B ──────────────────────────────────────────────────

class CheckResult(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    FAIL = "FAIL"

class VerificationCheck(BaseModel):
    check_id: str
    result: CheckResult
    expected: str
    found: str
    note: str

class VerificationSummary(BaseModel):
    overall_result: CheckResult
    pass_count: int
    flag_count: int
    fail_count: int

class Stage5BOutput(BaseModel):
    checks: List[VerificationCheck]
    verification_summary: VerificationSummary

    class Config:
        extra = "forbid"
