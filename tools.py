"""Tool layer: hard-constrained wrappers around the real data channels.

Real integrations plug in where marked TODO; MOCK_MODE generates synthetic
evidence so the whole graph runs end-to-end before any credential exists.
Budget enforcement lives HERE (not in prompts): a worker cannot overspend
even if the LLM asks to.
"""

import os
import random

MOCK_MODE = os.environ.get("OUTAGE_AGENT_MOCK", "1") == "1"

INITIAL_BUDGET = {"kpi_calls": 12, "coverage_calls": 30}


def make_evidence(eid, source, question, summary, var, cost, granularity=None):
    return {"id": eid, "source": source, "question_it_answers": question,
            "summary": summary, "var": var, "cost": cost,
            "granularity": granularity}


# ---------------- KPI channel ----------------
def run_kpi_action(action_id, action, case, evidence_count):
    """Execute a KPI data acquisition. Returns (evidence_entry, observed).

    REAL MODE (TODO): build SQL via kpi_pipeline.query_builder.KPIQueryBuilder
        builder.build(start, end, kpi_names=action["params"]["kpis"],
                      time_granularity=..., spatial_level=...,
                      enodebs=... or cells=...)
        df = run_query(sql, params)   # your Snowflake function (params bound!)
        then summarize df -> interval evidence for the target variable.
    """
    p = action["params"]
    if MOCK_MODE:
        summary = f"[mock] {action['desc']} -> stats over {p['time_granularity']}/{p['spatial_level']}"
        observed = {"shrink_factor": action["r"] * random.uniform(0.8, 1.05)}
    else:
        raise NotImplementedError("plug query_builder + run_query here")
    eid = f"E{evidence_count + 1:03d}"
    ev = make_evidence(eid, "snowflake_kpi", action["desc"], summary,
                       action["var"], action["cost"],
                       (p["time_granularity"], p["spatial_level"]))
    return ev, observed


# ---------------- Coverage channel ----------------
def run_coverage_action(action_id, action, case, evidence_count):
    """Execute a coverage scan. REAL MODE (TODO): call the coverage API with
    sampling strategy from params; respect per-call geo-bin limits."""
    p = action["params"]
    if MOCK_MODE:
        summary = f"[mock] {action['desc']} ({p.get('strategy')})"
        observed = {"shrink_factor": action["r"] * random.uniform(0.7, 1.0)}
    else:
        raise NotImplementedError("plug coverage API client here")
    eid = f"E{evidence_count + 1:03d}"
    ev = make_evidence(eid, "coverage_api", action["desc"], summary,
                       action["var"], action["cost"], p.get("strategy"))
    return ev, observed


# ---------------- Attribute channel ----------------
def run_attribute_action(action_id, action, case, evidence_count):
    """Cell/site attribute lookup. REAL MODE (TODO): query your attribute
    source; return neighbor candidate cells/enodebs with band/tech."""
    if MOCK_MODE:
        summary = "[mock] 6 candidate neighbor cells across 3 sites, band-compatible"
        observed = {"shrink_factor": action["r"], "neighbors_found": True}
    else:
        raise NotImplementedError("plug attribute source here")
    eid = f"E{evidence_count + 1:03d}"
    ev = make_evidence(eid, "attributes", action["desc"], summary,
                       action["var"], action["cost"])
    return ev, observed


WORKER_RUNNERS = {
    "kpi_analyst": run_kpi_action,
    "coverage_surveyor": run_coverage_action,
    "attribute_lookup": run_attribute_action,
}
