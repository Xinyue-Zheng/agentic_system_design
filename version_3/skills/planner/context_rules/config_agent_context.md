# Context Rule: config_agent

## Input from shared_context
Reads: `outage_scope.sector_states`, `outage_scope.type`,
`time_context.peak_overlap`, `time_context.peak_hours_within_window`

Also reads from ticket (passed as run parameter): `outage_start_utc`, `outage_end_utc`

---

## Priority Focus Derivation

Compose `priority_focus` by combining a **redistribution scope**, a **capacity pressure**
clause, and optionally a **duration qualifier**.

### Step 1 — Determine redistribution scope

| `outage_scope.type` | Redistribution scope clause |
|---|---|
| `"Full Outage"` | "All sectors of [affected_usid] are offline. Assess neighbor site capacity to absorb the full displaced traffic load." |
| `"Partial Outage"` | "Failed sectors requiring redistribution: [list failed sector_ids]. Active sectors [list active sector_ids] continue serving their load — do not double-count." |
| `"Degraded Service"` | "Degraded sectors: [list degraded sector_ids]. Assess partial load spillover to neighbors." |

> Note: Neighbor directionality is derived from site coordinates in
> `get_site_attributes`, not from Planner direction strings. Config Agent
> reads actual azimuth from site attributes when available.

### Step 2 — Determine capacity pressure clause

| `peak_overlap` | Capacity pressure clause |
|---|---|
| `true` | "Neighbor sites must sustain absorbed traffic during peak hours: [peak_hours_within_window]. Prioritize capacity headroom at those hours." |
| `false` | "Outage is off-peak. Assess steady-state neighbor capacity without peak multipliers." |

### Step 3 — Apply duration qualifier

Compute duration: `outage_end_utc - outage_start_utc` (skip if `outage_end_utc` is null).

| Duration | Qualifier |
|---|---|
| > 6 hours | Append: "Outage is long-duration ([N] hours). Emphasize sustained capacity, not burst tolerance." |
| ≤ 6 hours | No qualifier |
| `outage_end_utc` is null | No qualifier |

### Step 4 — Compose

Concatenate redistribution scope + capacity pressure clause + duration qualifier (if any)
as `priority_focus`.

---

## Flag Derivation

Config agent analysis is driven by static site attributes and does not
require flag-based skill switching at this stage.

| Flag | Condition | Status |
|---|---|---|
| `null` | all cases | current implementation uses base skill only |

Reserved for future extension. Candidate flags:
- `SOLE_5G_PROVIDER`: affected USID is the only 5G station in the area;
  NSA downgrade risk becomes the primary analysis focus.
- `ALL_NEIGHBORS_LOW_CAPACITY`: all neighbor capacity_scores are below
  threshold; analysis shifts from finding the best neighbor to assessing
  minimum coverage preservation.

---

## Constraint Derivation

`constraint = null`

config_agent reads site attributes itself via `get_site_attributes`.
