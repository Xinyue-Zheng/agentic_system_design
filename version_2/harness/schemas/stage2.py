from pydantic import BaseModel, Field
from typing import Literal, List
from enum import Enum

class TowerType(str, Enum):
    micro = "micro"
    macro = "macro"
    tall_macro = "tall_macro"

class TechProfile(str, Enum):
    lte_only = "lte_only"
    nsa_5g = "nsa_5g"
    sa_5g = "sa_5g"

class CapacityVerdict(str, Enum):
    adequate = "adequate"
    marginal = "marginal"
    insufficient = "insufficient"

class USIDCapacityEntry(BaseModel):
    usid: str
    tower_type: TowerType
    tech_profile: TechProfile
    capacity_score: float = Field(ge=0)
    active_bands: int = Field(ge=0)
    four_g_cells: int = Field(ge=0)
    five_g_cells: int = Field(ge=0)

class NSA5GRisk(BaseModel):
    flagged: bool
    affected_fraction: float = Field(ge=0, le=1)
    primary_backup_has_5g: bool
    note: str

class Stage2Output(BaseModel):
    usids: List[USIDCapacityEntry]
    overall_capacity_verdict: CapacityVerdict
    nsa_5g_downgrade_risk: NSA5GRisk
    key_findings_for_stage4: List[str] = Field(min_items=1, max_items=4)
    uncertainty: dict

    class Config:
        extra = "forbid"
