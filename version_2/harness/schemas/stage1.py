from pydantic import BaseModel, Field
from typing import Literal, List
from enum import Enum

class RoleEnum(str, Enum):
    dominant_anchor = "dominant-anchor"
    strong_supporting = "strong-supporting"
    localized_supporting = "localized-supporting"
    edge_limited = "edge-limited"

class OverloadRisk(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"

class USIDEntry(BaseModel):
    usid: str
    role: RoleEnum
    role_confidence: Literal["low", "medium", "high"]
    dominant_pixel_fraction: float = Field(ge=0, le=1)
    rsrp_p50_dbm: float = Field(ge=-130, le=-30)
    rsrp_spatial_pattern: str = Field(min_length=10)

class PerBackup(BaseModel):
    backup_usid: str
    absorption_fraction_of_target: float = Field(ge=0, le=1)
    handover_quality: Literal["good", "partial", "poor"]
    rsrp_p50_in_zone_dbm: float = Field(ge=-130, le=-30)
    sinr_regime_impact_note: Literal["mostly_severe", "mixed", "mostly_mild"]
    post_outage_load_factor: float = Field(ge=0)
    overload_risk: OverloadRisk
    assessment: str = Field(min_length=20)

class TargetLoadAnalysis(BaseModel):
    target_usid: str
    dominant_area_impact_regime: Literal["mostly_severe", "mixed", "mostly_mild"]
    coverage_hole_fraction: float = Field(ge=0, le=1)
    coverage_hole_assessment: str
    per_backup: List[PerBackup]
    load_redistribution_verdict: Literal["adequate", "strained", "overloaded"]
    verdict_reasoning: List[str] = Field(min_items=1)

class Stage1Output(BaseModel):
    usids: List[USIDEntry]
    target_load_analysis: TargetLoadAnalysis
    key_findings_for_stage3: List[str] = Field(min_items=2, max_items=4)
    uncertainty: dict

    class Config:
        extra = "forbid"
