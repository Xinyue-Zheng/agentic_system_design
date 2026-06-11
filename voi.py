"""VoI routing core: estimation chain interval math + action registry + scoring.

This is the deterministic 'Gini analogue': score(a) = U(var_a) * r_a / c_a,
where U is the variable's contribution to the final estimate's interval
width (tornado analysis on RRC_loss = B * (H + O)).
All pure Python -- no LLM calls. Fully traceable.
"""

THETA = 0.02           # stop when no action scores above this
SATURATION_R = 0.15    # r_actual below this marks the variable saturated

# ---- estimation chain definition ----------------------------------------
# RRC_loss = B * (H + O)
#   B: baseline RRC connected users of the target cell(s)
#   H: fraction of traffic in coverage holes (no usable backup)
#   O: fraction lost due to neighbor overload (cannot absorb)
INITIAL_CHAIN = {
    "B": {"low": 50.0, "high": 800.0, "desc": "baseline RRC connected users"},
    "H": {"low": 0.05, "high": 0.60, "desc": "coverage-hole traffic fraction"},
    "O": {"low": 0.00, "high": 0.50, "desc": "neighbor-overload loss fraction"},
}


def rrc_loss_interval(chain):
    lo = chain["B"]["low"] * (chain["H"]["low"] + chain["O"]["low"])
    hi = chain["B"]["high"] * (chain["H"]["high"] + chain["O"]["high"])
    return lo, hi


def _width(chain):
    lo, hi = rrc_loss_interval(chain)
    return hi - lo


def uncertainty_contribution(chain):
    """Tornado analysis: for each var, fix it at midpoint and measure how
    much the output interval shrinks. Returns {var: normalized share}."""
    base = _width(chain)
    contrib = {}
    for var, iv in chain.items():
        mid = (iv["low"] + iv["high"]) / 2
        fixed = {k: dict(v) for k, v in chain.items()}
        fixed[var]["low"] = fixed[var]["high"] = mid
        contrib[var] = max(base - _width(fixed), 0.0)
    total = sum(contrib.values()) or 1.0
    return {v: c / total for v, c in contrib.items()}


# ---- action registry ------------------------------------------------------
# The human-seeded, living table: action -> (worker, target var, r, cost).
# r values are PRIORS; every execution logs (r_pred, r_actual) for calibration.
ACTION_REGISTRY = {
    "kpi_baseline_daily": {
        "worker": "kpi_analyst", "var": "B", "r": 0.7, "cost": 1.0,
        "budget_key": "kpi_calls",
        "params": {"kpis": ["rrc_connected_users"], "time_granularity": "day",
                   "spatial_level": "cell", "scope": "target_cells",
                   "window": "baseline_4w"},
        "prereq": None,
        "desc": "4-week daily baseline for target cell(s)",
    },
    "kpi_baseline_hourly": {
        "worker": "kpi_analyst", "var": "B", "r": 0.5, "cost": 3.0,
        "budget_key": "kpi_calls",
        "params": {"kpis": ["rrc_connected_users"], "time_granularity": "hour",
                   "spatial_level": "cell", "scope": "target_cells",
                   "window": "outage_window_padded"},
        "prereq": "kpi_baseline_daily",
        "desc": "hourly baseline around the outage window",
    },
    "attr_neighbor_lookup": {
        "worker": "attribute_lookup", "var": "H", "r": 0.2, "cost": 0.5,
        "budget_key": None,
        "params": {"radius_km": 5},
        "prereq": None,
        "desc": "candidate neighbor set from attributes (band/tech match)",
    },
    "coverage_ring_scan": {
        "worker": "coverage_surveyor", "var": "H", "r": 0.5, "cost": 3.0,
        "budget_key": "coverage_calls",
        "params": {"strategy": "ring_scan", "radii_km": [1, 3, 5, 8]},
        "prereq": "attr_neighbor_lookup",
        "desc": "coarse coverage scan around target site",
    },
    "coverage_refine": {
        "worker": "coverage_surveyor", "var": "H", "r": 0.4, "cost": 6.0,
        "budget_key": "coverage_calls",
        "params": {"strategy": "refine"},
        "prereq": "coverage_ring_scan",
        "desc": "refine edge bins where target is dominant / gap small",
    },
    "kpi_neighbor_prb_daily": {
        "worker": "kpi_analyst", "var": "O", "r": 0.6, "cost": 1.5,
        "budget_key": "kpi_calls",
        "params": {"kpis": ["dl_prb_utilization"], "time_granularity": "day",
                   "spatial_level": "enodeb", "scope": "neighbor_enodebs",
                   "window": "baseline_4w"},
        "prereq": "attr_neighbor_lookup",
        "desc": "neighbor PRB headroom, daily per site",
    },
    "kpi_neighbor_prb_hourly": {
        "worker": "kpi_analyst", "var": "O", "r": 0.5, "cost": 3.0,
        "budget_key": "kpi_calls",
        "params": {"kpis": ["dl_prb_utilization"], "time_granularity": "hour",
                   "spatial_level": "cell", "scope": "neighbor_cells",
                   "window": "outage_window_padded"},
        "prereq": "kpi_neighbor_prb_daily",
        "desc": "neighbor PRB at outage hours, per cell",
    },
}


def score_actions(chain, done_actions, saturated_vars, budget):
    """Deterministic scoring of every available action. Returns
    ({action_id: score}, should_submit)."""
    contrib = uncertainty_contribution(chain)
    scores = {}
    for aid, a in ACTION_REGISTRY.items():
        if aid in done_actions:
            continue
        if a["prereq"] and a["prereq"] not in done_actions:
            continue
        if a["var"] in saturated_vars:
            scores[aid] = 0.0
            continue
        if a["budget_key"] and budget.get(a["budget_key"], 0) <= 0:
            scores[aid] = 0.0
            continue
        scores[aid] = round(contrib[a["var"]] * a["r"] / a["cost"], 4)
    should_submit = (not scores) or max(scores.values()) < THETA
    return scores, should_submit
