# KPI Agent Layer Collaboration

## Overview

The KPI agent is composed of three layered skills that always run in
sequence. Base always runs. Peak and Sustained are loaded by Harness
depending on outage duration and peak overlap.

---

## Trigger Logic

| duration_hours | peak_overlap | Skills loaded | peak_hour_verdict source |
|---|---|---|---|
| ≤ 6 | false | Base only | — (null) |
| ≤ 6 | true | Base + Peak | Peak Step 4 |
| > 6 | false | Base + Sustained | — (null) |
| > 6 | true | Base + Sustained | Sustained Step 5 (internal) |

When `duration > 6` and `peak_overlap = true`, Sustained derives
`peak_hour_verdict` internally. Peak skill is **not** loaded.

---

## What Each Layer Computes

### Base (`kpi_analysis_base.md`)

| Field | How computed |
|---|---|
| `outage_window_hours` | Parsed from `outage_start_utc` / `outage_end_utc` |
| `lost_traffic_mbps` | Mean throughput of failed sectors, filtered to outage window hours |
| `lost_volume_gb` | Mean volume of failed sectors, filtered to outage window hours |
| `loss_ratio` | `lost_traffic_mbps` / total station avg at those hours |
| `baseline_mbps` | Sum of all sector avgs at outage window hours |
| `per_neighbor.neighbor_baseline_mbps` | Mean throughput at outage window hours |
| `per_neighbor.neighbor_p90_mbps` | p90 throughput at outage window hours |
| `per_neighbor.neighbor_baseline_vol_gb` | Mean volume at outage window hours |
| `per_neighbor.extra_throughput_mbps` | `lost_traffic_mbps × absorption_fraction` |
| `per_neighbor.extra_volume_gb` | `lost_volume_gb × absorption_fraction` |
| `per_neighbor.new_total_mbps` | `neighbor_baseline_mbps + extra_throughput_mbps` |
| `per_neighbor.absorption_feasibility` | vs `neighbor_p90_mbps × 0.85` threshold |
| `overload_verdict` | Based on absorption_feasibility across all neighbors |

### Peak (`kpi_peak_hour_analysis.md`) — loads when duration ≤ 6h AND peak_overlap = true

| Field | How computed |
|---|---|
| `peak_window` | `peak_hours_within_window` from shared_context |
| `peak_lost_traffic_mbps` | Mean throughput of failed sectors at peak hours only |
| `peak_lost_volume_gb` | Mean volume of failed sectors at peak hours only |
| `peak_vs_average` | `peak_lost > base_lost × 1.2` → "significantly_worse" |
| Per-neighbor peak baseline / p90 | History filtered to peak hours |
| Per-neighbor `peak_absorption_feasibility` | vs `neighbor_peak_p90 × 0.85` |
| `peak_hour_verdict` | Based on peak absorption_feasibility across all neighbors |

### Sustained (`kpi_sustained_pressure.md`) — loads when duration > 6h

| Field | How computed |
|---|---|
| Per-hour `hour_baseline_mbps` | Mean throughput where hour-of-day == H |
| Per-hour `hour_p90_mbps` | p90 throughput where hour-of-day == H |
| Per-hour `hour_baseline_vol_gb` | Mean volume where hour-of-day == H |
| Per-hour `new_total_mbps` | `hour_baseline_mbps + (lost_traffic_mbps × absorption_fraction)` |
| Per-hour `new_total_vol_gb` | `hour_baseline_vol_gb + (lost_volume_gb × absorption_fraction)` |
| Per-hour `classification` | stable / stressed / overloaded vs `hour_p90 × 0.85` |
| `hourly_distribution` | Count of stable / stressed / overloaded hours |
| `trend` | Direction of overloaded proportion over time |
| `sustained_pressure_verdict` | Based on distribution + trend |
| `peak_hour_verdict` | Derived from peak-hour classifications (only if peak_overlap = true) |

---

## Data Flow Between Layers

```
get_kpi_history(affected_usid)   ─────────────────────────────┐
get_kpi_history(neighbor_usid)   ─── Base retrieves once       │
preprocessing_stats.per_backup   ─── absorption_fraction once  │
                                                               │
         Base artifact written                                 │
         ┌──────────────────────────────────────────────┐     │
         │ overload_verdict                             │     │
         │ lost_traffic_mbps  ◄──── reused by Peak      │     │
         │ lost_volume_gb     ◄──── reused by Peak      │◄────┘
         │ per_neighbor[].absorption_fraction ◄─ reused │
         │ per_neighbor[].neighbor_baseline_* ◄─ reused │
         └──────────────────────────────────────────────┘
                        │                   │
              duration ≤ 6h             duration > 6h
              peak_overlap=true         (any peak_overlap)
                        │                   │
                        ▼                   ▼
                  Peak layer          Sustained layer
                  adds:               adds:
                  peak_hour_verdict   sustained_pressure_verdict
                  peak_lost_*         hourly_distribution
                  peak_vs_average     trend
                                      peak_hour_verdict (if peak_overlap)
                                      sustained_reasoning_log[]
                                        .hour_baseline_vol_gb
                                        .new_total_vol_gb
```

---

## Throughput vs Volume Coverage

| Layer | Throughput (Mbps) | Volume (GB) | Classification basis |
|---|---|---|---|
| Base | ✓ lost + per-neighbor | ✓ lost + per-neighbor | — |
| Peak | ✓ peak lost + per-neighbor peak | ✓ peak lost | Throughput |
| Sustained | ✓ per-hour baseline + new total | ✓ per-hour baseline + new total | Throughput |

Volume is tracked at every layer but classification thresholds
(sufficient / marginal / insufficient, stable / stressed / overloaded)
are always based on throughput vs p90. Volume is recorded for
downstream capacity planning use by Assessment Agent.

---

## What Base Does NOT Do

- Does **not** call `get_kpi_timeseries` for neighbor USIDs
- Does **not** use 24-hour overall averages — always filters to outage window hours
- Does **not** compute `peak_hour_verdict` or `sustained_pressure_verdict`
  (these fields are written as `null` and filled by extension layers)

## What Extension Layers Do NOT Do

- Do **not** call any MCP tool — all history data is already in context from Base
- Do **not** overwrite `overload_verdict`, `lost_traffic_mbps`, or any other base field
- Do **not** re-read `absorption_fraction` — taken from base artifact `per_neighbor`
