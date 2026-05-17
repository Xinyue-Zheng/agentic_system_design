from pydantic import BaseModel, Field
from typing import Literal, List
from enum import Enum

class SignalCondition(str, Enum):
    excellent = "excellent"
    good = "good"
    moderate = "moderate"
    weak = "weak"
    very_weak = "very_weak"
    no_coverage = "no_coverage"

class SinrRegime(str, Enum):
    noise_limited = "noise_limited"
    interference_limited = "interference_limited"
    mixed = "mixed"
    high_sinr = "high_sinr"

class ImpactSeverity(str, Enum):
    critical = "critical"
    high = "high"
    moderate = "moderate"
    low = "low"
    negligible = "negligible"

class LandUse(str, Enum):
    residential = "residential"
    commercial = "commercial"
    industrial = "industrial"
    road = "road"
    transport_hub = "transport_hub"
    hospital = "hospital"
    mixed = "mixed"
    open = "open"

class ImpactZone(BaseModel):
    zone_id: str
    zone_name: str
    signal_condition: SignalCondition
    sinr_regime: SinrRegime
    land_use: LandUse
    is_critical_infrastructure: bool
    impact_severity: ImpactSeverity
    rsrp_p50_in_zone_dbm: float = Field(ge=-130, le=-30)
    map_evidence: str = Field(min_length=10)
    sinr_scratchpad: str = Field(min_length=20)

class Stage3Output(BaseModel):
    target_usid: str
    geographic_character: str
    impact_zones: List[ImpactZone] = Field(min_items=2, max_items=5)
    coverage_hole_geographic_assessment: str
    worst_zone_severity: ImpactSeverity
    key_findings_for_stage4: List[str] = Field(min_items=2, max_items=4)
    uncertainty: dict

    class Config:
        extra = "forbid"
