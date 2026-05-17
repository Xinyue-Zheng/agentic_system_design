# Context Rule: coverage_agent

## Input from shared_context
Reads: `outage_scope.type`, `outage_scope.sector_states`, `time_context.peak_overlap`

---

## Priority Focus Derivation

Evaluate the following conditions in order; use the first match.

**Condition 1 — Full Outage (`outage_scope.type == "Full Outage"`):**
```
priority_focus = "Assess full coverage loss for [affected_usid]. All sectors are assumed
failed. Identify neighbor cells that can provide backup coverage across the entire site
footprint. Do not restrict analysis to individual azimuths."
```

**Condition 2 — Partial Outage with failed sectors
(`sector_states` contains ≥1 `"failed"` entry):**
```
priority_focus = "Assess coverage gaps specifically for failed sectors: [list failed
sector_ids]. Active sectors [list active sector_ids] remain operational — do not model
full site failure. Focus gap analysis on the azimuths of failed sectors only."
```

**Condition 3 — All sectors degraded, none failed
(all `sector_states` values are `"degraded"`):**
```
priority_focus = "Assess signal quality degradation across all sectors of [affected_usid].
No sectors have fully failed — focus on RSRP and SINR reduction, not coverage gaps."
```

---

> Note: Directional analysis is driven by coverage pixel data (sector-level
> IDs in dominant/backup fields) and preprocessing stats, not by
> Planner-injected direction strings. Coverage Agent reads sector spatial
> distribution directly from coverage pixel data (sector-level IDs) and
> preprocessing stats.

---

## Flag Derivation

Harness reads these flags to decide which additional skill files to load
alongside coverage_analysis_base.md.

| Flag | Condition | Skills loaded by Harness |
|---|---|---|
| `FULL_SITE_FAILURE` | `outage_type == "Full Outage"` | base + `coverage_directional_focus.md` |
| `PARTIAL_SECTOR_FAILURE` | `outage_type` is `"Partial Outage"` OR `"Degraded Service"` | base + `coverage_directional_focus.md` |

Directional Focus is now loaded for ALL outage types that have
failed sectors — including Full Outage. Full Outage has all three
sectors down, meaning three separate geographic directions are
affected. Per_zone entries for all three sectors provide Geo Agent
with precise centroid coordinates per direction, rather than a
single coarse tower-centered 10km map. This ensures spatial
analysis precision does not decrease as outage severity increases.

For `PARTIAL_SECTOR_FAILURE`, directional_focus handles both failed and
degraded sectors in `per_zone`:
- failed sector → analyze coverage hole + backup signal quality
- degraded sector → analyze RSRP/SINR reduction, do not model coverage hole

`SIGNAL_DEGRADATION_ONLY` is removed — merged into `PARTIAL_SECTOR_FAILURE`.

---

## Constraint Derivation

**If `sector_states` contains ≥1 `"active"` entry:**
```
constraint = "Do not model full site failure. Active sectors [list active sector_ids]
remain operational and must be excluded from gap analysis."
```

**Otherwise:** `constraint = null`
