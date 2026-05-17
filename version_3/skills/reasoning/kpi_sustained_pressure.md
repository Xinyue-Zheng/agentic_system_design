---
name: kpi_sustained_pressure
description: >
  Loaded when duration_hours > 6. Extends kpi_analysis_base with an anchored
  hourly forecast for sustained neighbor pressure. When peak_overlap is true,
  derives peak_hour_verdict from the hourly base/stress classifications.
---

# KPI Analysis: Sustained Hourly Forecast

## When This Skill Runs

Triggered when outage duration is `> 6h`.

When `peak_overlap=true`, this skill also derives `peak_hour_verdict` from the
hourly forecast. `kpi_peak_hour_analysis.md` is not loaded separately in that
case.

---

## Role

You are the KPI Sustained Pressure layer. The base layer forecasts total
counterfactual load across the outage window. This layer asks:

> Does neighbor absorption capacity hold hour by hour, or does pressure persist,
> worsen, or concentrate in peak hours?

Use anchored hourly forecasts. Do not reuse one static lost-traffic value for
all hours when hourly historical distributions are available.

---

## Preconditions

`kpi_analysis_base` has already run and produced:

- `forecast_framing`
- `lost_traffic_forecast`
- `per_neighbor`
- `affected_sectors`
- `outage_window_hours`
- `forecast_uncertainty`

Reuse absorption fractions from base `per_neighbor`, affected sectors, and
history already retrieved by base where available.

Do not overwrite `lost_traffic_forecast`, base `per_neighbor`, or
`overload_risk`.

---

## Step 1 - Build Hourly Lost Traffic Forecast Candidates

For each hour `H` in `outage_window_hours`, filter affected USID history to:

- affected sectors only
- hour-of-day == `H`

Compute:

```json
"hourly_lost_traffic_candidates": {
  "17:00": {
    "same_hour_mean_mbps": 0.0,
    "same_hour_p75_mbps": 0.0,
    "same_hour_p90_mbps": 0.0,
    "same_daytype_hour_mean_mbps": 0.0,
    "recent_14d_hour_mean_mbps": 0.0,
    "candidate_notes": []
  }
}
```

If a candidate cannot be supported, set it to `null` and explain.

---

## Step 2 - Select Hourly Base and Stress Forecasts

For each hour, select:

- `selected_base_mbps`
- `selected_stress_mbps`

Guidance:

| Hour context | Base | Stress |
|---|---|---|
| Off-peak weekday | same_hour_mean | same_hour_p75 |
| Peak hour inside outage | same_hour_p75 or same-daytype hour mean | same_hour_p90 |
| Weekend/holiday with matching cohort | same-daytype hour mean | same_hour_p90 |
| Unknown or weak context | same_hour_mean | same_hour_p90 |

Output:

```json
"hourly_lost_traffic_forecast": {
  "17:00": {
    "base_case_source": "same_hour_p75_mbps",
    "base_case_mbps": 0.0,
    "stress_case_source": "same_hour_p90_mbps",
    "stress_case_mbps": 0.0,
    "selection_reason": "Peak hour; p75 is used as base and p90 as stress.",
    "uncertainty": "low | medium | high"
  }
}
```

The selection reason is required. This is the key sustained-forecast reasoning
step.

---

## Step 3 - Build Hourly Neighbor Forecast

For each hour `H` and each neighbor:

1. Filter neighbor history to hour `H`.
2. Compute `neighbor_hour_baseline_mbps`, `neighbor_hour_p75_mbps`,
   `neighbor_hour_p90_mbps`, and `neighbor_hour_baseline_vol_gb`.
3. Reuse `absorption_fraction` from base.
4. Compute:

```text
new_total_base_H =
  neighbor_hour_baseline_mbps
  + hourly_lost_traffic_forecast[H].base_case_mbps * absorption_fraction

new_total_stress_H =
  neighbor_hour_baseline_mbps
  + hourly_lost_traffic_forecast[H].stress_case_mbps * absorption_fraction
```

Classify base and stress:

| Condition | classification |
|---|---|
| new_total <= p90 * 0.85 | stable |
| p90 * 0.85 < new_total <= p90 | stressed |
| new_total > p90 | overloaded |

Use the worst classification across neighbors for each hour. Record the worst
neighbor for base and stress if they differ.

---

## Step 4 - Build Hourly Distribution

Output both base and stress distributions:

```json
"hourly_distribution": {
  "base": {
    "stable_hours": 0,
    "stressed_hours": 0,
    "overloaded_hours": 0
  },
  "stress": {
    "stable_hours": 0,
    "stressed_hours": 0,
    "overloaded_hours": 0
  }
}
```

For backward compatibility, also provide:

```json
"hourly_distribution_legacy": {
  "stable_hours": 0,
  "stressed_hours": 0,
  "overloaded_hours": 0
}
```

The legacy distribution should mirror the base distribution unless the stress
case is much worse and you explicitly decide the stress case is the operational
view.

---

## Step 5 - Determine Trend

Trend should reason over the sequence, not just count totals.

Consider:

- Does pressure increase entering peak hours?
- Does it persist after peak?
- Does the same neighbor drive worst pressure repeatedly?
- Does stress case materially worsen the base case?

Output:

```json
"trend": "stable",
"trend_detail": {
  "label": "improving | stable | worsening | worsening_then_persistent",
  "reason": "Pressure increases entering 17:00-20:00 and remains overloaded through outage end."
}
```

---

## Step 6 - Determine Sustained Pressure Verdict

Use base and stress distributions:

| Pattern | sustained_pressure_verdict |
|---|---|
| Base mostly stable and stress mostly stable/stressed | sustainable |
| Base has many stressed hours or trend worsens into peak | degrading |
| Base majority overloaded | unsustainable |
| Stress majority overloaded and base is degrading | unsustainable |

Output:

```json
"sustained_pressure_verdict": "sustainable | degrading | unsustainable",
"sustained_pressure_reason": "Base case overloads 9/11 hours; stress case overloads 11/11 hours."
```

---

## Step 7 - Derive Peak-Hour Verdict If Applicable

If `peak_overlap=true`:

1. Read `peak_hours_within_window`.
2. Extract base and stress classifications for those hours.
3. Determine:

| Peak pattern | peak_hour_verdict |
|---|---|
| Base and stress mostly stable | manageable |
| Base stable/stressed but stress overloaded in any peak hour | elevated_risk |
| Base overloaded in any material peak hour | critical |
| Stress overloaded in all or most peak hours | critical |

Output:

```json
"peak_derivation": {
  "peak_hours": ["17:00", "18:00", "19:00", "20:00"],
  "base_case_peak_classifications": {
    "17:00": "overloaded"
  },
  "stress_case_peak_classifications": {
    "17:00": "overloaded"
  },
  "derived_peak_hour_verdict": "critical"
}
```

If `peak_overlap=false`, set `peak_hour_verdict=null` and
`peak_derivation=null`.

---

## Step 8 - Update Artifact

Add to existing base artifact:

```json
{
  "sustained_pressure_verdict": "sustainable | degrading | unsustainable",
  "sustained_pressure_reason": "string",
  "duration_hours": 10.5,
  "hourly_lost_traffic_candidates": {},
  "hourly_lost_traffic_forecast": {},
  "hourly_neighbor_forecast": {},
  "hourly_distribution": {
    "base": {"stable_hours": 0, "stressed_hours": 0, "overloaded_hours": 0},
    "stress": {"stable_hours": 0, "stressed_hours": 0, "overloaded_hours": 0}
  },
  "hourly_distribution_legacy": {
    "stable_hours": 0,
    "stressed_hours": 0,
    "overloaded_hours": 0
  },
  "trend": "stable",
  "trend_detail": {"label": "stable", "reason": "string"},
  "peak_hour_verdict": "manageable | elevated_risk | critical | null",
  "peak_derivation": {},
  "sustained_reasoning_log": []
}
```

`sustained_reasoning_log` must include at least one entry per outage hour with
the selected hourly forecast basis, worst neighbor, base/stress totals, and
base/stress classification.

---

## Verification Contract

- Hourly candidates must be filtered to each exact hour-of-day.
- Each hourly base and stress forecast must cite a candidate source.
- Do not reuse one static lost-traffic value for all hours unless hourly history
  is unavailable; if unavailable, explain and mark uncertainty high.
- `absorption_fraction` must come from base artifact.
- Hourly classifications must follow Step 3 threshold rules.
- `hourly_distribution.base` must match the base hourly classifications.
- `hourly_distribution.stress` must match the stress hourly classifications.
- `sustained_pressure_verdict` must follow Step 6.
- `peak_hour_verdict` must follow Step 7 when `peak_overlap=true`.
- Do not overwrite base `overload_risk`, `lost_traffic_forecast`, or
  `per_neighbor` fields.
