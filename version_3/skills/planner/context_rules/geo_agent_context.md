# Context Rule: geo_agent

## Input from shared_context
Reads: `outage_scope.type`, `outage_scope.sector_states`

Also reads from ticket (passed as run parameter): `lat`, `lon`, `affected_usid`

---

## Priority Focus Derivation

Determine geographic impact scope based on outage coverage, then compose `priority_focus`.

**Condition 1 — Full Outage (`outage_scope.type == "Full Outage"`):**
```
priority_focus = "Assess the full geographic footprint of coverage loss for [affected_usid]
centered at ([lat], [lon]). All sectors are offline — map the complete extent of lost
coverage across all azimuths. Identify which populated areas fall within the affected zone."
```

**Condition 2 — Partial Outage with failed sectors
(`sector_states` contains ≥1 `"failed"` entry):**
```
priority_focus = "Coverage gaps exist in [affected_usid] at ([lat], [lon]).
Focus geographic analysis on zones flagged by Coverage Agent as
coverage_holes or weak_zones. Identify land_use and user_relevance
in those specific zones. Do not analyze strong_zones in detail."
```

**Condition 3 — All sectors degraded, none failed
(all `sector_states` values are `"degraded"`):**
```
priority_focus = "No full coverage gaps expected in [affected_usid]
at ([lat], [lon]). Focus on whether signal degradation zones identified
by Coverage Agent intersect populated or critical infrastructure areas."
```

**Terrain analysis:** geo_agent is always responsible for determining terrain relevance.
It will call `get_geo_features` itself if needed. Do not pre-judge or instruct on terrain.

> Note: Geographic focus areas are derived from Coverage Agent's
> `key_findings_for_geo` (coverage_holes, weak_zones coordinates),
> not from Planner direction strings. Planner only provides
> `geo_scope_flag` to indicate the overall scope of analysis.

---

## Flag Derivation

Geo Agent uses a single base skill regardless of flag.
Harness passes the flag to geo_agent via per_agent_context only —
it does not change which skill files are loaded.

| Flag | Condition | Effect |
|---|---|---|
| `FULL_SITE_COVERAGE_LOSS` | `outage_type == "Full Outage"` | Geo Agent analyzes all directions equally |
| `PARTIAL_COVERAGE_LOSS` | `sector_states` has ≥1 `"failed"` entry | Geo Agent prioritizes failed sector directions from Coverage findings |
| `null` | all sectors degraded, none failed OR all sectors active | Geo Agent focuses on signal degradation zones from Coverage findings |

In all cases, the primary guidance for what to analyze comes from
Coverage Agent's `key_findings_for_geo`. Coverage findings take
precedence because they are grounded in measured signal data.

---

## Constraint Derivation

`constraint = null`

geo_agent handles all geographic and terrain judgments autonomously.
