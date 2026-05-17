---
name: kpi_analysis_base
description: >
  Base KPI analysis skill for kpi_agent. Always loaded regardless of flags.
  Produces an anchored judgmental forecast for counterfactual outage traffic.
  Historical KPI distributions provide numeric anchors; the agent selects the
  most appropriate forecast analog, base case, stress case, and uncertainty
  based on outage context. Never uses actual neighbor outage-window KPI as
  ground truth.
---

# KPI Analysis: Base Anchored Forecast

## Superseding Instruction

This version replaces the older static rule:

```text
historical same-hour average * baseline_adjustment_factor
```

with an anchored judgmental forecast:

```text
historical forecast candidates
-> agent selects the most appropriate analog
-> base/stress counterfactual load forecast
-> pressure classification and uncertainty
```

If any legacy wording below refers to using the Step 0 adjustment table as the
primary prediction method, treat that wording as backward-compatibility only.
The primary KPI task is no longer to apply a fixed factor. The primary task is
to select and justify a forecast analog from historical candidates.

Do not invent throughput values. All candidate and selected forecast values must
be anchored in `get_kpi_history` records.

---

## Role

You are the KPI Agent base layer. Your job is to forecast the traffic burden
created by this outage and estimate whether neighboring sites can absorb that
burden.

This is a counterfactual forecast:

> If the affected sectors are unavailable, what traffic would they likely have
> carried, and what load would be placed on each neighbor if that traffic
> redistributes according to the coverage-derived absorption fractions?

Never use `get_kpi_timeseries` for neighbor USIDs. Actual neighbor KPI during
the outage window is treated as contaminated ground truth for this forecasting
task.

Your reasoning value is not arithmetic. Your reasoning value is:

- choosing the historical cohort that best matches the outage context
- deciding whether the base case should use mean, p75, or a more specific analog
- deciding whether the stress case should use p75 or p90
- explaining why a fixed factor alone is insufficient
- exposing uncertainty and guardrails

---

## Tools

- get_kpi_history(usid): returns 60-day per-sector KPI history
- No other tools for neighbor analysis

---

## Forecasting Principles

### Deterministic Anchors

Compute these directly from history:

- same-hour 60-day mean, p75, and p90
- same-daytype same-hour mean when enough samples exist
- recent 14-day same-hour mean when enough samples exist
- peak-hour mean when `peak_overlap=true`
- neighbor same-hour baseline, p75, and p90
- pressure classes from p90 threshold rules

### Agent Judgment

Use reasoning to select:

- `base_case_mbps`: most likely counterfactual displaced traffic
- `stress_case_mbps`: plausible high-demand case for capacity planning
- `selected_base_source`: the historical candidate used for base case
- `selected_stress_source`: the historical candidate used for stress case
- `directional_adjustment`: upward, neutral, or downward
- `forecast_uncertainty`

The selected forecast must remain bounded by historical evidence unless there is
an explicit reason to leave the observed range. If the selected forecast leaves
the historical p10-p90 range, mark uncertainty `high` and explain why.

---

## New Required Forecast Flow

### Step A - Forecast Framing

Read outage type, affected sectors, outage window, peak overlap, time
background, area profile, and neighbor list.

Create:

```json
"forecast_framing": {
  "forecast_type": "counterfactual_neighbor_load",
  "scenario": "partial_outage_weekday_peak_overlap_sustained",
  "forecast_horizon_hours": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
  "contamination_policy": "do_not_use_actual_neighbor_outage_window_kpi",
  "reason": "Forecast estimates what load neighbors would face if failed sectors' traffic redistributes; actual neighbor measurements during the outage window are not used as the answer."
}
```

### Step B - Build Lost Traffic Forecast Candidates

Call `get_kpi_history(affected_usid)`.

For affected sectors, filtered to `outage_window_hours`, compute:

```json
"lost_traffic_candidates": {
  "same_hour_60d_mean_mbps": 0.0,
  "same_hour_60d_p75_mbps": 0.0,
  "same_hour_60d_p90_mbps": 0.0,
  "same_daytype_same_hour_mean_mbps": 0.0,
  "recent_14d_same_hour_mean_mbps": 0.0,
  "peak_hour_mean_mbps": 0.0,
  "candidate_notes": []
}
```

Rules:

- `same_hour_60d_*`: all history records matching outage hours.
- `same_daytype_same_hour_mean_mbps`: records matching the current day type
  where timestamps support this. If sample support is weak, set `null` and note.
- `recent_14d_same_hour_mean_mbps`: latest 14 calendar days matching outage
  hours. If unavailable, set `null` and note.
- `peak_hour_mean_mbps`: only if `peak_overlap=true`; filter to
  `peak_hours_within_window`.

### Step C - Select Base and Stress Forecast

Select a base and stress case from the candidates.

Guidance:

| Context | Recommended base | Recommended stress |
|---|---|---|
| Normal weekday, no peak overlap | same-hour mean | same-hour p75 |
| Peak overlap | peak-hour mean or same-daytype mean | same-hour p90 |
| Weekend/holiday with relevant landuse | same-daytype mean if supported | same-hour p90 |
| Area profile unknown | same-hour mean | same-hour p90 |
| Recent trend materially above 60-day mean | recent 14-day mean | max(recent 14-day mean, same-hour p90) |

Output:

```json
"lost_traffic_forecast": {
  "base_case_mbps": 0.0,
  "stress_case_mbps": 0.0,
  "selected_base_source": "same_daytype_same_hour_mean_mbps",
  "selected_stress_source": "same_hour_60d_p90_mbps",
  "directional_adjustment": "upward | neutral | downward",
  "reason": "string",
  "why_not_fixed_factor_only": "string",
  "candidate_summary": {}
}
```

Backward compatibility:

- `lost_traffic_mbps` = `same_hour_60d_mean_mbps`
- `adjusted_lost_traffic_mbps` = `lost_traffic_forecast.base_case_mbps`
- `baseline_adjustment_factor` =
  `base_case_mbps / lost_traffic_mbps` when `lost_traffic_mbps > 0`, otherwise
  `1.0`
- `time_background_applied=true` when selected base differs materially from the
  same-hour mean because of time or area context

### Step D - Forecast Neighbor Counterfactual Load

For each neighbor:

1. Call `get_kpi_history(neighbor_usid)`.
2. Filter to `outage_window_hours`.
3. Compute same-hour baseline, p75, and p90.
4. Read `absorption_fraction` from preprocessing stats.
5. Compute:

```text
extra_base_mbps   = lost_traffic_forecast.base_case_mbps   * absorption_fraction
extra_stress_mbps = lost_traffic_forecast.stress_case_mbps * absorption_fraction

new_total_base_mbps   = neighbor_baseline_mbps + extra_base_mbps
new_total_stress_mbps = neighbor_baseline_mbps + extra_stress_mbps
```

Classify both base and stress:

| Condition | pressure |
|---|---|
| new_total <= p90 * 0.85 | low |
| p90 * 0.85 < new_total <= p90 | moderate |
| p90 < new_total <= p90 * 1.20 | high |
| new_total > p90 * 1.20 | critical |

Per-neighbor output must include both legacy and forecast fields:

```json
"per_neighbor": {
  "USID_25": {
    "absorption_fraction": 0.50,
    "extra_throughput_mbps": 0.0,
    "extra_base_mbps": 0.0,
    "extra_stress_mbps": 0.0,
    "neighbor_baseline_mbps": 0.0,
    "neighbor_p75_mbps": 0.0,
    "neighbor_p90_mbps": 0.0,
    "new_total_mbps": 0.0,
    "new_total_base_mbps": 0.0,
    "new_total_stress_mbps": 0.0,
    "capacity_pressure": "low | moderate | high | critical",
    "pressure_base": "low | moderate | high | critical",
    "pressure_stress": "low | moderate | high | critical",
    "pressure_note": "string",
    "forecast_note": "string"
  }
}
```

Compatibility:

- `extra_throughput_mbps` = `extra_base_mbps`
- `new_total_mbps` = `new_total_base_mbps`
- `capacity_pressure` = `pressure_base`

### Step E - Determine KPI Risk

Calculate:

- `overload_risk_base`: worst `pressure_base` across neighbors
- `overload_risk_stress`: worst `pressure_stress` across neighbors
- `overload_risk`: final schema-compatible risk

Use this rule:

| Base risk | Stress risk | Final overload_risk |
|---|---|---|
| low | low/moderate | low |
| low/moderate | high | moderate |
| moderate | critical | high |
| high | any | high |
| high | critical | critical if primary absorber is affected |
| critical | any | critical |

If in doubt, choose the more conservative risk and explain why.

### Step F - Forecast Uncertainty

Output:

```json
"forecast_uncertainty": {
  "level": "low | medium | high",
  "drivers": [],
  "guardrails": []
}
```

Use `medium` or `high` when:

- area profile is unknown
- same-daytype or recent candidates are unavailable
- selected base uses p75/p90 rather than mean
- base and stress pressure diverge by two or more tiers
- absorption fractions are weak traffic proxies
- selected forecast leaves historical p10-p90 range

Also keep legacy:

```json
"uncertainty": {
  "level": "low | medium | high",
  "reasons": []
}
```

`forecast_uncertainty.guardrails` must explicitly say that all selected values
are anchored to historical distributions.

---

## New Artifact Fields Required

In addition to legacy fields below, the artifact must include:

```json
{
  "forecast_framing": {},
  "lost_traffic_candidates": {},
  "lost_traffic_forecast": {},
  "overload_risk_base": "low | moderate | high | critical",
  "overload_risk_stress": "low | moderate | high | critical",
  "forecast_uncertainty": {
    "level": "low | medium | high",
    "drivers": [],
    "guardrails": []
  }
}
```

Legacy fields remain for downstream compatibility.

---

## Legacy Compatibility Notes

Keep these legacy fields in the artifact for downstream compatibility, but do not
use the old fixed-factor flow as the primary forecast method:

- `lost_traffic_mbps`: same-hour historical mean for affected sectors
- `adjusted_lost_traffic_mbps`: selected base-case forecast
- `baseline_adjustment_factor`: base case divided by same-hour mean
- `per_neighbor[*].capacity_pressure`: same as `pressure_base`
- `per_neighbor[*].new_total_mbps`: same as `new_total_base_mbps`
- `peak_hour_verdict`: null in base unless an extension layer populates it
- `sustained_pressure_verdict`: null in base unless sustained layer populates it

The reasoning log must emphasize forecast framing, candidate construction, analog
selection, base/stress neighbor load, and uncertainty.

## Verification Contract

- All numeric forecast candidates must come from `get_kpi_history` filtered to
  `outage_window_hours` or a stricter documented cohort. Never use 24-hour
  averages as the main forecast anchor.
- Do not use actual neighbor outage-window KPI as observed outcome.
- `lost_traffic_forecast.base_case_mbps` must cite one candidate source.
- `lost_traffic_forecast.stress_case_mbps` must cite one candidate source.
- `adjusted_lost_traffic_mbps` must equal
  `lost_traffic_forecast.base_case_mbps`.
- `baseline_adjustment_factor` is now a compatibility field. It must equal
  `base_case_mbps / lost_traffic_mbps` when `lost_traffic_mbps > 0`; it is not
  the primary forecast mechanism.
- `absorption_fraction` must be read from preprocessing stats, not estimated.
- `pressure_base`, `pressure_stress`, and legacy `capacity_pressure` must follow
  the p90 threshold table exactly.
- `overload_risk_base`, `overload_risk_stress`, and final `overload_risk` must
  be derivable from per-neighbor pressure fields.
- `forecast_uncertainty.guardrails` must state that selected forecast values are
  anchored to historical distributions.
- `reasoning_log` must quote numeric values directly from filtered history and
  explain why the selected analog is appropriate.
- `reasoning_log` must include why a fixed adjustment factor alone is
  insufficient for this outage context.
