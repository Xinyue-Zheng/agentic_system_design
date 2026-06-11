"""Blackboard state -- the single source of truth shared by all nodes.

Design rule: every routing decision is WRITTEN INTO STATE (route_log,
current_decision); conditional edges only read state. This is what makes
each decision point inspectable in LangSmith traces and checkpoints.
"""

import operator
from typing import Annotated, Optional
from typing_extensions import TypedDict


class CaseState(TypedDict, total=False):
    # --- immutable case facts (set once by init_case) ---
    case: dict            # {case_id, target_cells, enodeb, outage_window, location}

    # --- estimation chain: variables with uncertainty intervals ---
    # {var: {"low": float, "high": float, "desc": str}}
    chain: dict

    # --- VoI routing ---
    action_scores: dict            # {action_id: score} from last score_actions
    current_decision: Optional[dict]
    done_actions: Annotated[list, operator.add]     # executed action ids
    saturated_vars: Annotated[list, operator.add]   # vars where drilling stopped paying
    should_submit: bool

    # --- evidence & audit ---
    evidence: Annotated[list, operator.add]   # ledger entries (see tools.py)
    route_log: Annotated[list, operator.add]  # one entry per decision/step
    hypotheses: Annotated[list, operator.add]

    # --- budget (replaced wholesale by nodes that spend) ---
    budget: dict           # {"kpi_calls": int, "coverage_calls": int}

    # --- review loop ---
    milestones: dict       # {"M1".."M5": bool}
    estimate: Optional[dict]
    judge_verdict: Optional[dict]   # {"verdict": ACCEPT|REVISE|ESCALATE, "directive": str}
    revise_count: int
    report: Optional[str]
