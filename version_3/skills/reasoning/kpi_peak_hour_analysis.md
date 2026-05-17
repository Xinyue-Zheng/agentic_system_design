---
name: kpi_peak_hour_analysis
description: >
  Loaded only when PEAK_HOUR_OVERFLOW flag is set: peak_overlap == true
  AND duration_hours <= 6. Extends kpi_analysis_base by producing an anchored
  peak-hour forecast. Does not replace base fields; it adds peak-specific
  forecast candidates, base/stress peak load, and peak verdict reasoning.
---

# KPI Analysis: Peak-Hour Anchored Forecast

## When This Skill Runs

Triggered when:

- `peak_overlap = true`
- outage duration is `<= 6h`

When duration is `> 6h` and `peak_overlap=true`, do not run this skill
independently. `kpi_sustained_pressure.md` derives `peak_hour_verdict` from its
hourly forecast distribution.

---

## Role

You are the KPI Peak-Hour layer. Base provides a full-window forecast, which may
smooth over short peak pressure. This layer asks:

> During the highest recurring demand hours inside this outage, what
> counterfactual traffic would failed sectors likely have carried, and can
> neighbors absorb it?

All peak forecast numbers must be anchored in `get_kpi_history` records already
retrieved by the base layer or available in context. Do not invent peak
throughput values.

---

## Preconditions

`kpi_analysis_base` has already run and produced:

- `forecast_framing`
- `lost_traffic_candidates`
- `lost_traffic_forecast`
- `per_neighbor`
- `affected_sectors`
- `outage_window_hours`

Reuse affected sectors, absorption fractions, neighbor list, and base forecast
guardrails. Do not overwrite base fields except `peak_hour_verdict`.

---

## Step 1 - Identify Peak Forecast Context

Read `shared_context.time_context.peak_hours_within_window`.

Create:

```json
"peak_forecast_context": {
  "peak_hours": ["17:00", "18:00"],
  "outage_fraction_of_peak_window": 0.75,
  "forecast_issue": "short outage overlaps highest recurring demand hours; full-window base forecast may understate peak stress"
}
```

Record why a separate peak forecast is needed.

---

## Step 2 - Build Peak Lost Traffic Candidates

Using affected USID history and affected sectors, filter to peak hours only.

Build:

```json
"peak_lost_traffic_candidates": {
  "peak_mean_mbps": 0.0,
  "peak_p75_mbps": 0.0,
  "peak_p90_mbps": 0.0,
  "same_daytype_peak_mean_mbps": 0.0,
  "recent_14d_peak_mean_mbps": 0.0,
  "candidate_notes": []
}
```

If a candidate cannot be supported by enough samples, set it to `null` and
explain in `candidate_notes`.

---

## Step 3 - Select Peak Base and Stress Forecast

Select:

- `peak_base_case_mbps`
- `peak_stress_case_mbps`

Guidance:

| Context | Peak base | Peak stress |
|---|---|---|
| Normal weekday peak | peak_mean or same-daytype peak mean | peak_p90 |
| Recent trend above peak mean | recent_14d_peak_mean | max(recent_14d_peak_mean, peak_p90) |
| Area profile unknown | peak_mean | peak_p90 |
| Sensitive or high-demand landuse | peak_p75 | peak_p90 |

Output:

```json
"selected_peak_forecast": {
  "base_case_source": "same_daytype_peak_mean_mbps",
  "base_case_mbps": 0.0,
  "stress_case_source": "peak_p90_mbps",
  "stress_case_mbps": 0.0,
  "directional_adjustment": "upward | neutral | downward",
  "reason": "string",
  "uncertainty": "low | medium | high"
}
```

The selected values must cite candidate sources. Do not choose a value without
an anchor.

---

## Step 4 - Forecast Neighbor Peak Load

For each neighbor in base artifact `per_neighbor`:

1. Use peak-hour neighbor history.
2. Compute `neighbor_peak_baseline_mbps`, `neighbor_peak_p75_mbps`, and
   `neighbor_peak_p90_mbps`.
3. Reuse `absorption_fraction`.
4. Compute base and stress peak totals:

```text
new_total_peak_base_mbps =
  neighbor_peak_baseline_mbps
  + selected_peak_forecast.base_case_mbps * absorption_fraction

new_total_peak_stress_mbps =
  neighbor_peak_baseline_mbps
  + selected_peak_forecast.stress_case_mbps * absorption_fraction
```

Classify using the same p90 pressure thresholds as base:

| Condition | pressure |
|---|---|
| new_total <= p90 * 0.85 | low |
| p90 * 0.85 < new_total <= p90 | moderate |
| p90 < new_total <= p90 * 1.20 | high |
| new_total > p90 * 1.20 | critical |

Output:

```json
"peak_neighbor_forecast": {
  "USID_25": {
    "absorption_fraction": 0.50,
    "neighbor_peak_baseline_mbps": 0.0,
    "neighbor_peak_p75_mbps": 0.0,
    "neighbor_peak_p90_mbps": 0.0,
    "new_total_peak_base_mbps": 0.0,
    "new_total_peak_stress_mbps": 0.0,
    "peak_pressure_base": "low | moderate | high | critical",
    "peak_pressure_stress": "low | moderate | high | critical",
    "forecast_note": "string"
  }
}
```

---

## Step 5 - Determine Peak Verdict

Use both base and stress pressure:

| Pattern | peak_hour_verdict |
|---|---|
| All primary absorbers low/moderate in base and stress | manageable |
| Base mostly low/moderate, but stress has high pressure | elevated_risk |
| Any primary absorber high in base case | critical |
| Any primary absorber critical in stress case | critical |

Primary absorbers are neighbors with material absorption fraction. Treat
`absorption_fraction >= 0.10` as material unless the base artifact says
otherwise.

Output:

```json
"peak_hour_verdict": "manageable | elevated_risk | critical",
"peak_verdict_reason": "string"
```

---

## Step 6 - Update Artifact

Add these fields to `kpi_agent_artifact.json` without removing base fields:

```json
{
  "peak_hour_verdict": "manageable | elevated_risk | critical",
  "peak_forecast_context": {},
  "peak_lost_traffic_candidates": {},
  "selected_peak_forecast": {},
  "peak_neighbor_forecast": {},
  "peak_verdict_reason": "string",
  "peak_reasoning_log": []
}
```

`peak_reasoning_log` must explain the peak context, candidate selection, and at
least one neighbor peak load calculation.

---

## Verification Contract

- Peak candidates must be filtered to `peak_hours_within_window` only.
- Selected peak base and stress values must cite candidate sources.
- No peak forecast value may be invented outside the candidate distribution
  without explicit high-uncertainty justification.
- `absorption_fraction` must be taken from base artifact.
- `peak_pressure_base` and `peak_pressure_stress` must follow the p90 threshold
  table exactly.
- `peak_hour_verdict` must follow Step 5.
- Do not overwrite base `lost_traffic_forecast`, `per_neighbor`, or
  `overload_risk` fields.
