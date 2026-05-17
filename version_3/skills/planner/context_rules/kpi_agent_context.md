# Context Rule: kpi_agent

## Input from shared_context
Reads: `time_context.peak_overlap`, `time_context.peak_hours_within_window`,
`outage_scope.sector_states`, `outage_scope.type`

---

## Priority Focus Derivation

Compose `priority_focus` by combining a **traffic scope** clause with a **time scope** clause.

### Step 1 — Determine traffic scope

| `outage_scope.type` | Traffic scope clause |
|---|---|
| `"Full Outage"` | "Complete traffic loss from [affected_usid]. All sectors are offline." |
| `"Partial Outage"` | "Partial traffic loss. Failed sectors: [list failed sector_ids]. Active sectors still serving: [list active sector_ids]." |
| `"Degraded Service"` | "Reduced throughput across degraded sectors: [list degraded sector_ids]. No sectors have fully failed." |

### Step 2 — Determine time scope

| `peak_overlap` | Time scope clause |
|---|---|
| `true` | "Focus overflow risk analysis specifically during peak hours: [peak_hours_within_window]. Assess whether neighbor cells can absorb displaced traffic at those hours." |
| `false` | "Outage falls outside peak hours. Focus on off-peak load assessment and baseline neighbor capacity." |

### Step 2b — Determine duration scope

Compute `duration_hours` = `outage_end_utc` − `outage_start_utc`.
If `outage_end_utc` is null, skip this step.

| `duration_hours` | Duration scope clause |
|---|---|
| > 6 | Append: "Outage is long-duration ([N] hours). Assess whether neighbor capacity holds over time, not just at peak." |
| ≤ 6 | No additional clause. |

### Step 3 — Compose

Concatenate traffic scope clause + time scope clause +
duration scope clause (if any) as `priority_focus`.

---

## Flag Derivation

Harness reads these flags to decide which additional skill files to load
alongside kpi_analysis_base.md.

| Flag | Condition | Additional skill loaded by Harness |
|---|---|---|
| `PEAK_HOUR_OVERFLOW` | `peak_overlap == true` AND `duration_hours ≤ 6` | `kpi_peak_hour_analysis.md` |
| `SUSTAINED_OUTAGE` | `duration_hours > 6` | `kpi_sustained_pressure.md` |
| `null` | neither condition met | base skill only |

When both peak_overlap = true AND duration > 6 hours:
  Only SUSTAINED_OUTAGE is set. PEAK_HOUR_OVERFLOW is not set.
  kpi_sustained_pressure.md will derive peak_hour_verdict
  internally from its hourly_distribution (Step 5).
  kpi_peak_hour_analysis.md is not loaded.

`duration_hours` is computed from `outage_end_utc` − `outage_start_utc`.
If `outage_end_utc` is null, `SUSTAINED_OUTAGE` is never set.

---

## Constraint Derivation

`constraint = null`

kpi_agent determines its own data constraints from the timeseries it retrieves directly.
