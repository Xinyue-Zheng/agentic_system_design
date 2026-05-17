# Planner: Output Schema

## Required Output Format

The Planner must emit exactly one JSON block. No text outside the block.

---

## JSON Schema

```
{
  "shared_context": {                          // required
    "outage_scope": {                          // required
      "type": string,                          // required — copied from ticket outage_type
      "sector_states": {                       // required — null for Full Outage
        "<sector_id>": "failed"
                      | "degraded"
                      | "active"
                      | "unknown"
      } | null
    },
    "time_context": {                          // required
      "peak_overlap": boolean,                 // required
      "peak_hours_within_window": [string]     // required — null if peak_overlap is false
                                 | null        // format: "HH:MM" (UTC, 24-hour)
    },
    "time_background": {                       // required
      "day_type": string,                      // required — "holiday" | "weekend" | "weekday"
      "holiday_name": string | null,           // required — holiday name or null
      "time_of_day": string,                   // required — "overnight" | "morning_peak" | "midday" | "evening_peak" | "late_evening"
      "calibration_note": string | null        // required — note when day_type is not weekday, else null
    },
    "area_profile": {                          // required — null if no coordinates in ticket
      "dominant_landuse": string,              // e.g. "residential" | "commercial" | "industrial" | "unknown"
      "landuse_summary": object,               // count per landuse type
      "has_hospital": boolean | null,          // null if osmnx query failed
      "has_school": boolean | null,
      "has_railway": boolean | null,
      "source": "openstreetmap"
    } | null
  },

  "per_agent_context": {                       // required
    "coverage_agent": {                        // required
      "priority_focus": string,                // required
      "flag": string | null,                   // required
      "constraint": string | null              // required
    },
    "kpi_agent": {                             // required
      "priority_focus": string,                // required
      "flag": string | null,                   // required
      "constraint": string | null              // required
    },
    "config_agent": {                          // required
      "priority_focus": string,                // required
      "flag": string | null,                   // required
      "constraint": string | null              // required
    },
    "geo_agent": {                             // required
      "priority_focus": string,                // required
      "flag": string | null,                   // required
      "constraint": string | null              // required
    }
  },

  "planner_reasoning_log": {                   // required
    "tools_called": [                          // required — at least one entry
      {
        "tool": string,                        // required — exact MCP tool name
        "params": object,                      // required — exact params passed
        "reason": string                       // required — WHY this tool was called
      }
    ],
    "key_judgments": [                         // required
      {
        "judgment": string,                    // required — claim made in shared_context
        "based_on": string                     // required — data value that supports it
      }
    ]
  }
}
```

---

## Validation Rules (enforced by Harness)

1. All four analysis agents (`coverage_agent`, `kpi_agent`, `config_agent`, `geo_agent`)
   must have a `per_agent_context` entry. Any additional registered agent must also have
   an entry — the harness validates against its registered agent list, not a hardcoded count.

2. `peak_hours_within_window` must be `null` if `peak_overlap` is `false`.

3. `planner_reasoning_log.tools_called` must contain at least one entry.

4. Every field present in `shared_context` must have a corresponding entry in
   `planner_reasoning_log.key_judgments`.

5. `flag` values are **NOT** validated by this schema. They are validated by each agent's
   reasoning skill file at runtime. This allows new flags to be added by updating an
   agent's skill file without modifying this schema.

---

## Example A — Full Outage (USID_19)

Ticket: `outage_type: "Full Outage"`, `affected_usid: "USID_19"`,
`outage_start_utc: "2026-04-19T00:29:01Z"`, `outage_end_utc: "2026-04-20T00:29:01Z"`

> `sector_states` is `null` — ticket already implies all sectors are down.
> Only `get_kpi_history` is called (for peak hours). The 24-hour window covers
> the station's peak hours at 17:00–19:00 UTC, so `peak_overlap` is `true`.

```json
{
  "shared_context": {
    "outage_scope": {
      "type": "Full Outage",
      "sector_states": null
    },
    "time_context": {
      "peak_overlap": true,
      "peak_hours_within_window": ["17:00", "18:00", "19:00"]
    },
    "time_background": {
      "day_type": "weekday",
      "holiday_name": null,
      "time_of_day": "overnight",
      "calibration_note": null
    },
    "area_profile": {
      "dominant_landuse": "residential",
      "landuse_summary": {"residential": 14, "commercial": 3},
      "has_hospital": false,
      "has_school": true,
      "has_railway": false,
      "source": "openstreetmap"
    }
  },
  "per_agent_context": {
    "coverage_agent": {
      "priority_focus": "Assess full coverage loss for USID_19. All sectors are assumed failed. Identify neighbor cells that can provide backup coverage across the entire site footprint. Do not restrict analysis to individual azimuths.",
      "flag": "FULL_SITE_FAILURE",
      "constraint": null
    },
    "kpi_agent": {
      "priority_focus": "Complete traffic loss from USID_19. All sectors are offline. Focus overflow risk analysis specifically during peak hours: [17:00, 18:00, 19:00]. Assess whether neighbor cells can absorb displaced traffic at those hours.",
      "flag": "PEAK_HOUR_OVERFLOW",
      "constraint": null
    },
    "config_agent": {
      "priority_focus": "All sectors of USID_19 are offline. Assess neighbor site capacity to absorb the full displaced traffic load. Neighbor sites must sustain absorbed traffic during peak hours: [17:00, 18:00, 19:00]. Prioritize capacity headroom at those hours. Outage is long-duration (24.0 hours). Emphasize sustained capacity, not burst tolerance.",
      "flag": null,
      "constraint": null
    },
    "geo_agent": {
      "priority_focus": "Assess the full geographic footprint of coverage loss for USID_19 centered at (33.031544, -96.705749). All sectors are offline — map the complete extent of lost coverage across all azimuths. Identify which populated areas fall within the affected zone.",
      "flag": "FULL_SITE_COVERAGE_LOSS",
      "constraint": null
    }
  },
  "planner_reasoning_log": {
    "tools_called": [
      {
        "tool": "get_kpi_history",
        "params": { "usid": "USID_19" },
        "reason": "Need to identify USID_19's recurring peak hours to determine whether the outage window overlaps with high-demand periods. Peak hours cannot be inferred from the ticket timestamp alone."
      },
      {
        "tool": "get_area_profile",
        "params": { "lat": 33.031544, "lon": -96.705749, "radius_m": 1000 },
        "reason": "Q4b: ticket contains coordinates — querying OSM land use profile to populate area_profile for KPI baseline adjustment."
      }
    ],
    "key_judgments": [
      {
        "judgment": "sector_states is null — all sectors assumed failed",
        "based_on": "Ticket outage_type is 'Full Outage', which unambiguously implies all sectors are down. No timeseries retrieval required."
      },
      {
        "judgment": "peak_overlap is true; peak hours 17:00, 18:00, 19:00 fall within the outage window",
        "based_on": "get_kpi_history aggregated by hour-of-day: hours 17, 18, 19 UTC showed highest mean throughput_dl_mbps across 60 days. Outage window 00:29 Apr-19 to 00:29 Apr-20 UTC covers all 24 hours, including all three peak hours."
      },
      {
        "judgment": "day_type=weekday, time_of_day=overnight — no baseline adjustment expected",
        "based_on": "outage_start_utc 2026-04-19T00:29:01Z is a Sunday (weekend), hour 00 → overnight. Correction: day_type=weekend, calibration_note set."
      },
      {
        "judgment": "area_profile dominant_landuse=residential from OSM within 1km radius",
        "based_on": "get_area_profile returned 14 residential polygons, 3 commercial, dominant=residential."
      }
    ]
  }
}
```

---

## Example B — Partial Outage (USID_20)

Ticket: `outage_type: "Partial Outage"`, `affected_usid: "USID_20"`,
`outage_start_utc: "2026-03-08T06:00:00Z"`, `outage_end_utc: "2026-03-09T00:48:00Z"`

> `sector_states` must be derived from data — ticket does not specify which sectors failed.
> Both `get_kpi_history` and `get_kpi_timeseries` are called.
> Timeseries shows S0 and S2 failed; S1 remained active.
> Peak hours 17:00–19:00 fall within the 06:00–00:48 window → `peak_overlap` is `true`.

```json
{
  "shared_context": {
    "outage_scope": {
      "type": "Partial Outage",
      "sector_states": {
        "USID_20_S0": "failed",
        "USID_20_S1": "active",
        "USID_20_S2": "failed"
      }
    },
    "time_context": {
      "peak_overlap": true,
      "peak_hours_within_window": ["17:00", "18:00", "19:00"]
    }
  },
  "per_agent_context": {
    "coverage_agent": {
      "priority_focus": "Assess coverage gaps specifically for failed sectors: USID_20_S0, USID_20_S2. Active sector USID_20_S1 remains operational — do not model full site failure. Focus gap analysis on the azimuths of failed sectors only.",
      "flag": "PARTIAL_SECTOR_FAILURE",
      "constraint": "Do not model full site failure. Active sector USID_20_S1 remains operational and must be excluded from gap analysis."
    },
    "kpi_agent": {
      "priority_focus": "Partial traffic loss. Failed sectors: USID_20_S0, USID_20_S2. Active sector still serving: USID_20_S1. Focus overflow risk analysis specifically during peak hours: [17:00, 18:00, 19:00]. Assess whether neighbor cells can absorb the displaced load from the two failed sectors at those hours.",
      "flag": "PEAK_HOUR_OVERFLOW",
      "constraint": null
    },
    "config_agent": {
      "priority_focus": "Failed sectors requiring redistribution: USID_20_S0, USID_20_S2. Active sector USID_20_S1 continues serving its load — do not double-count. Neighbor sites must sustain absorbed traffic during peak hours: [17:00, 18:00, 19:00]. Prioritize capacity headroom at those hours. Outage is long-duration (18.8 hours). Emphasize sustained capacity, not burst tolerance.",
      "flag": null,
      "constraint": null
    },
    "geo_agent": {
      "priority_focus": "Assess geographic coverage gaps for failed sectors: USID_20_S0, USID_20_S2 of USID_20 at (33.018924, -96.698139). Active sector USID_20_S1 continues to serve its footprint — restrict gap mapping to the azimuths of failed sectors only.",
      "flag": "PARTIAL_COVERAGE_LOSS",
      "constraint": null
    }
  },
  "planner_reasoning_log": {
    "tools_called": [
      {
        "tool": "get_kpi_history",
        "params": { "usid": "USID_20" },
        "reason": "Need USID_20's 60-day historical averages per sector to: (1) establish classification baselines for Q1 sector-state thresholds, and (2) identify recurring peak hours for Q2 peak overlap determination."
      },
      {
        "tool": "get_kpi_timeseries",
        "params": {
          "usid": "USID_20",
          "start_utc": "2026-03-08T06:00:00Z",
          "end_utc": "2026-03-09T00:48:00Z"
        },
        "reason": "Ticket is a Partial Outage — which specific sectors are affected is not stated. Need sector-level measurements during the outage window to classify each sector as failed, degraded, or active against historical baselines."
      }
    ],
    "key_judgments": [
      {
        "judgment": "USID_20_S0 is 'failed'",
        "based_on": "Mean throughput_dl_mbps during outage window: 0.3 Mbps. 60-day historical average: 48.2 Mbps. Ratio: 0.6% < 5% threshold."
      },
      {
        "judgment": "USID_20_S1 is 'active'",
        "based_on": "Mean throughput_dl_mbps during outage window: 41.7 Mbps. 60-day historical average: 47.9 Mbps. Ratio: 87.1% > 60% threshold."
      },
      {
        "judgment": "USID_20_S2 is 'failed'",
        "based_on": "Mean throughput_dl_mbps during outage window: 0.1 Mbps. 60-day historical average: 50.1 Mbps. Ratio: 0.2% < 5% threshold."
      },
      {
        "judgment": "peak_overlap is true; peak hours 17:00, 18:00, 19:00 fall within the outage window",
        "based_on": "get_kpi_history aggregated by hour-of-day: hours 17, 18, 19 UTC showed highest mean throughput_dl_mbps across 60 days. Outage window 06:00 Mar-08 to 00:48 Mar-09 UTC spans 18.8 hours and includes all three peak hours."
      }
    ]
  }
}
```
