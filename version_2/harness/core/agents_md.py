"""
agents_md.py — loads hot and warm tier context

The hot tier is fixed — loaded from AGENTS.md file.
The warm tier is stage-specific — loaded from playbook.json.

Both are injected into every Claude API call by the harness.
The agent cannot skip either. The harness enforces this.
"""

from pathlib import Path
from harness.core.playbook import PlaybookManager

AGENTS_MD_PATH = Path("/workspace/AGENTS.md")
_playbook = PlaybookManager()


def load_hot_tier() -> str:
    """
    Loads the hot tier from AGENTS.md.
    This is the fixed kernel — never changes between runs.
    Contains: 3GPP thresholds, role definitions,
              severity rules, constraint rules C1-C5.
    """
    if AGENTS_MD_PATH.exists():
        # In production: read from the actual AGENTS.md file
        return AGENTS_MD_PATH.read_text()
    else:
        # Fallback: inline the essential thresholds
        # (same content as your current SKILL.md threshold section)
        return """
## REFERENCE THRESHOLDS (3GPP TS 38.133 / 36.133)
RSRP: Excellent > -80 dBm | Good -90 to -80 | Moderate -100 to -90 | Poor < -100
SINR: Excellent > 20 dB | Good 13-20 | Moderate 0-13 | Poor < 0

## DOMINANCE ROLE THRESHOLDS
dominant-anchor:      dom_frac >= 0.30
strong-supporting:    0.10 to 0.30
localized-supporting: 0.03 to 0.10
edge-limited:         < 0.03

## LOAD RISK THRESHOLDS
post_outage_load_factor > 0.8 → high
post_outage_load_factor > 0.5 → medium
else                          → low

## TOWER TYPE THRESHOLDS
height < 25m  → micro
height 25-45m → macro
height > 45m  → tall_macro

## SEVERITY RULE TABLE
[... full rule table from your SKILL.md ...]

## CONSTRAINT RULES C1-C5
C1: hole_fraction < 0.05 AND all overload_risk = low → level <= 2
C2: any is_critical_infrastructure = true            → level >= 3
C3: dominant_area_impact_regime = mostly_mild        → reduce one level
C4: load_redistribution_verdict = overloaded         → increase one level
C5: nsa_5g flagged AND affected_fraction > 0.20      → add to breakdown
"""


def load_warm_tier(stage_id: str) -> str:
    """
    Loads stage-specific lessons from the evolving playbook.
    Returns empty string if no lessons exist yet (first run).
    """
    return _playbook.get_warm_tier(stage_id)
