---
name: coverage_directional_focus
description: >
  Loaded when FULL_SITE_FAILURE or PARTIAL_SECTOR_FAILURE flag is set.
  Handles Full Outage (all sectors failed), Partial Outage, and Degraded
  Service. Generates per_zone entries for every failed or degraded sector
  regardless of outage type. Extends coverage_analysis_base by analyzing
  signal conditions per sector direction. Requires base artifact to already
  exist. Does not replace base results — only adds per_zone.
---

# Coverage Analysis: Directional Focus

## Precondition
coverage_analysis_base has already run. Base artifact exists.
Do not recalculate load_redistribution_verdict.
Do not re-read preprocessing stats — use what is already in context.
Does not replace base results — only adds per_zone.

For Full Outage: all three sectors (S0, S1, S2) are treated
as failed. Generate one per_zone entry per sector.
Do not skip any sector.

---

## Inputs

Read from per_agent_context:
- outage_scope.type and outage_scope.sector_states

  If outage_scope.type == 'Full Outage':
    treat all three sectors (S0, S1, S2) as failed.
    sector_states is null for Full Outage — derive sector IDs
    from affected_usid: {affected_usid}_S0, {affected_usid}_S1,
    {affected_usid}_S2.

  Otherwise: read sector states normally from sector_states dict.

Read from base artifact already in context:
- key_findings_for_geo (weak_zones, strong_zones, coverage_holes)
- per_backup data

Read from coverage pixel data:
- dominant.ID / backup1.ID / backup2.ID per pixel
  (sector-level IDs, e.g. "USID_20_S2")

---

## Step 1 — Identify sectors to analyze

If outage_scope.type == 'Full Outage':
  sectors_to_analyze = [
    {affected_usid}_S0 → status: failed,
    {affected_usid}_S1 → status: failed,
    {affected_usid}_S2 → status: failed
  ]

Otherwise:
  sectors_to_analyze = all entries in sector_states where
  status is "failed" or "degraded".
  Skip sectors where status is "active".

For each sector in sectors_to_analyze:
  Call get_coverage_pixels_by_sector(sector_id)
  From the returned pixel list:
  - pixel_count = number of pixels returned
  - affected_bbox = min/max lat and lon across all pixels
  - centroid = mean lat and mean lon across all pixels

  If no pixels are returned for a sector: pixel_count = 0,
  affected_bbox = null, centroid = null.

---

## Step 2 — Analyze each affected sector direction

For each failed or degraded sector, create a per_zone entry.
pixel_count, affected_bbox, and centroid are derived in Step 1.

For FAILED sectors:
  - pixel_count, affected_bbox, centroid: from Step 1 pixel query
  - primary_backup_usid: identify from base artifact key_findings_for_geo
    which backup USID covers this sector's zone
  - signal_condition: derive from rsrp_p50 of that backup in this zone
    strong:    rsrp_p50 > -80 dBm
    moderate:  rsrp_p50 -90 to -80 dBm
    weak:      rsrp_p50 -100 to -90 dBm
    very_weak: rsrp_p50 < -100 dBm OR no backup
  - sinr_regime: read from base artifact per_backup.sinr_regime_impact_note
  - has_coverage_hole: true if this sector's zone appears in
    key_findings_for_geo.coverage_holes
  - hole_fraction_in_direction: if hole is in this sector's zone use
    coverage_hole_fraction, otherwise 0.0
  - throughput_drop_ratio: null
  - degradation_note: null

For DEGRADED sectors:
  - pixel_count, affected_bbox, centroid: from Step 1 pixel query
  - primary_backup_usid: null (sector is still partially serving,
    not fully handing over)
  - signal_condition: derive from dominant RSRP in this sector's zone
  - has_coverage_hole: always false (degraded ≠ hole)
  - hole_fraction_in_direction: always 0.0
  - throughput_drop_ratio: derive from sector_states context if available;
    otherwise note as "estimated_from_degraded_classification"
  - degradation_note: brief description of signal quality reduction
    e.g. "S2 throughput 5-60% of historical average — moderate degradation"

For ACTIVE sectors:
  - Do not create a per_zone entry. Active sectors are not analyzed here.

---

## Step 3 — Update artifact

Document each sector's pixel query result and signal assessment
in directional_reasoning_log before writing artifact.

Add per_zone to the existing base artifact.
Do not overwrite any base fields.

{
  "per_zone": {
    "USID_09_S0": {
      "sector_id": "USID_09_S0",
      "status": "failed",
      "pixel_count": 10,
      "affected_bbox": {
        "lat_min": 33.025, "lat_max": 33.028,
        "lon_min": -96.701, "lon_max": -96.695
      },
      "centroid": {"lat": 33.026, "lon": -96.697},
      "primary_backup_usid": "USID_25",
      "signal_condition": "strong",
      "rsrp_p50_in_zone": -64.82,
      "sinr_regime": "mostly_mild",
      "has_coverage_hole": false,
      "hole_fraction_in_direction": 0.0,
      "throughput_drop_ratio": null,
      "degradation_note": null
    },
    "USID_09_S1": {
      "sector_id": "USID_09_S1",
      "status": "failed",
      "pixel_count": 15,
      "affected_bbox": {
        "lat_min": 33.021, "lat_max": 33.025,
        "lon_min": -96.698, "lon_max": -96.691
      },
      "centroid": {"lat": 33.023, "lon": -96.694},
      "primary_backup_usid": "USID_43",
      "signal_condition": "strong",
      "rsrp_p50_in_zone": -67.75,
      "sinr_regime": "mostly_mild",
      "has_coverage_hole": false,
      "hole_fraction_in_direction": 0.0,
      "throughput_drop_ratio": null,
      "degradation_note": null
    },
    "USID_09_S2": {
      "sector_id": "USID_09_S2",
      "status": "failed",
      "pixel_count": 14,
      "affected_bbox": {
        "lat_min": 33.024, "lat_max": 33.028,
        "lon_min": -96.694, "lon_max": -96.689
      },
      "centroid": {"lat": 33.026, "lon": -96.692},
      "primary_backup_usid": "USID_01",
      "signal_condition": "strong",
      "rsrp_p50_in_zone": -66.49,
      "sinr_regime": "mostly_mild",
      "has_coverage_hole": false,
      "hole_fraction_in_direction": 0.0,
      "throughput_drop_ratio": null,
      "degradation_note": null
    }
  }
}

Zone keys use the full sector_id (e.g. USID_09_S0, USID_09_S1, USID_09_S2).

For Full Outage, per_zone always has three entries (S0, S1, S2).
For Partial Outage, per_zone has one entry per failed/degraded sector.

"directional_reasoning_log": [
  {
    "step": "Step 1 — Sector pixel query",
    "data_used": "get_coverage_pixels_by_sector(USID_09_S0): 10 pixels returned, bbox lat 33.025-33.028",
    "assumption": null,
    "result": "centroid=(33.026, -96.697), pixel_count=10"
  },
  {
    "step": "Step 2 — Failed sector USID_09_S0",
    "data_used": "primary_backup=USID_25, rsrp_p50_in_zone=-64.82, sinr=mostly_mild, has_coverage_hole=true",
    "assumption": null,
    "result": "signal_condition=strong, hole_fraction=0.024"
  }
]
