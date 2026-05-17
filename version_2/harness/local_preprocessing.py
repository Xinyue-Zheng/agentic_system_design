"""
local_preprocessing.py
=======================
Step 0 of the pipeline — runs entirely locally, no API calls.

Responsibilities
----------------
1. compute_coverage_summary()     per-USID RSRP stats + area-level SINR/TP/RSRQ
2. compute_capacity_summary()     capacity score for EVERY USID from attribute CSV
                                   (agents receive these as pre-computed facts)
3. identify_neighbors()           overlap-fraction-based neighbor ranking
4. compute_load_redistribution()  absorption, SINR regime, overload risk per backup
5. generate_rsrp_image()          one RSRP heatmap per target+neighbor USID
6. generate_dominance_map()       tiled dominant-USID color map
7. generate_sinr_map()            SINR heatmap with target area boundary
8. run_local_preprocessing()      master runner — calls all above, saves JSON

All numeric outputs are ground-truth anchors for agent prompts.
All images are used for geographic correlation with the real map.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap

# ── 3GPP quality thresholds (TS 38.133 / 36.133) ─────────────────────────────
RSRP_EXCELLENT, RSRP_GOOD, RSRP_MODERATE = -80, -90, -100   # dBm
SINR_EXCELLENT, SINR_GOOD, SINR_MODERATE =  20,  13,    0   # dB
RSRQ_EXCELLENT, RSRQ_GOOD, RSRQ_MODERATE = -10, -14,  -17   # dB
TP_HIGH, TP_MEDIUM                        =  50,  10         # Mbps

# ── Dominance role thresholds ─────────────────────────────────────────────────
DOM_ANCHOR = 0.30   # ≥30% → dominant-anchor
DOM_STRONG = 0.10   # 10–30% → strong-supporting
DOM_LOCAL  = 0.03   # 3–10%  → localized-supporting
                    # <3%    → edge-limited

# ── Neighbor definition ───────────────────────────────────────────────────────
NEIGHBOR_OVERLAP_THRESHOLD = 0.05   # backup fraction > 5% of target's pixels

# ── SINR regime thresholds ────────────────────────────────────────────────────
SINR_HIGH_REGIME = 10   # > 10 dB → noise-limited   → severe post-outage impact
SINR_LOW_REGIME  =  5   # < 5 dB  → interference-limited → mild post-outage impact

# ── Capacity formula weights ─────────────────────────────────────────────────
# capacity_score = (4G_cells × W4G + 5G_cells × W5G) × (1 + BAND_BONUS × active_bands)
W4G        = 1.0
W5G        = 2.0   # 5G NR ~2× capacity per cell vs LTE
BAND_BONUS = 0.15  # 15% capacity bonus per additional active frequency band

# ── Dominance map color palette (12 distinct colors per tile) ─────────────────
PALETTE = [
    "#E63946","#2196F3","#4CAF50","#FF9800","#9C27B0",
    "#00BCD4","#FF5722","#8BC34A","#E91E63","#3F51B5",
    "#FFEB3B","#009688",
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _pct_above(vals, thresh):
    return round(100 * sum(1 for v in vals if v > thresh) / max(len(vals), 1), 1)

def _percentile(vals_sorted, q):
    n = len(vals_sorted)
    return round(vals_sorted[int(q * n)], 2) if vals_sorted else None

def _save_fig(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [img] {Path(path).name}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. COVERAGE SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

def compute_coverage_summary(pixels: list) -> dict:
    """
    Per-USID RSRP statistics + area-level SINR/TP/RSRQ distributions.

    RSRP sampling strategy:
      dominant slot   → used for pixels where USID wins
      backup1/backup2 → used for pixels where USID appears as fallback
    This gives the broadest representative RSRP distribution for each USID
    across the entire target area, not only where it dominates.
    """
    total = len(pixels)
    usid_names = set()
    for p in pixels:
        info = p["info"]
        usid_names.add(info["dominant"]["ID"])
        if info.get("backup1"): usid_names.add(info["backup1"]["ID"])
        if info.get("backup2"): usid_names.add(info["backup2"]["ID"])

    dom_counts   = {n: 0  for n in usid_names}
    backup_counts= {n: 0  for n in usid_names}
    rsrp_samples = {n: [] for n in usid_names}
    tower_pos    = {}

    for p in pixels:
        info = p["info"]
        dom  = info["dominant"]
        dom_counts[dom["ID"]] += 1
        rsrp_samples[dom["ID"]].append(dom["rsrp"])
        if dom["ID"] not in tower_pos:
            tower_pos[dom["ID"]] = (dom["lat"], dom["lon"])
        for slot in ["backup1", "backup2"]:
            bu = info.get(slot)
            if bu:
                backup_counts[bu["ID"]] += 1
                rsrp_samples[bu["ID"]].append(bu["rsrp"])
                if bu["ID"] not in tower_pos:
                    tower_pos[bu["ID"]] = (bu["lat"], bu["lon"])

    per_usid = {}
    for name in sorted(usid_names):
        dom_frac = dom_counts[name] / total
        if   dom_frac >= DOM_ANCHOR: role = "dominant-anchor"
        elif dom_frac >= DOM_STRONG: role = "strong-supporting"
        elif dom_frac >= DOM_LOCAL:  role = "localized-supporting"
        else:                        role = "edge-limited"

        vals = sorted(rsrp_samples[name])
        n    = len(vals)
        tpos = tower_pos.get(name, (None, None))

        per_usid[name] = {
            "tower_lat":                 tpos[0],
            "tower_lon":                 tpos[1],
            "dominant_pixel_count":      dom_counts[name],
            "dominant_pixel_fraction":   round(dom_frac, 4),
            "backup_pixel_count":        backup_counts[name],
            "backup_pixel_fraction":     round(backup_counts[name] / total, 4),
            "inferred_role":             role,
            "rsrp_sample_count":         n,
            "rsrp_mean_dbm":             round(sum(vals) / n, 2) if n else None,
            "rsrp_p10_dbm":              _percentile(vals, 0.10),
            "rsrp_p50_dbm":              _percentile(vals, 0.50),
            "rsrp_p90_dbm":              _percentile(vals, 0.90),
            "rsrp_pct_above_excellent":  _pct_above(vals, RSRP_EXCELLENT),
            "rsrp_pct_above_good":       _pct_above(vals, RSRP_GOOD),
            "rsrp_pct_above_moderate":   _pct_above(vals, RSRP_MODERATE),
        }

    sinr_vals = [p["info"]["sinr_db"]         for p in pixels]
    tp_vals   = [p["info"]["throughput_mbps"] for p in pixels]
    rsrq_vals = [p["info"]["rsrq_db"]         for p in pixels]

    area_level = {
        "total_pixels":           total,
        "sinr_mean_db":           round(float(np.mean(sinr_vals)), 2),
        "sinr_pct_excellent":     _pct_above(sinr_vals, SINR_EXCELLENT),
        "sinr_pct_good":          _pct_above(sinr_vals, SINR_GOOD),
        "sinr_pct_moderate":      _pct_above(sinr_vals, SINR_MODERATE),
        "throughput_mean_mbps":   round(float(np.mean(tp_vals)), 2),
        "throughput_pct_high":    _pct_above(tp_vals, TP_HIGH),
        "throughput_pct_medium":  _pct_above(tp_vals, TP_MEDIUM),
        "rsrq_mean_db":           round(float(np.mean(rsrq_vals)), 2),
        "rsrq_pct_excellent":     _pct_above(rsrq_vals, RSRQ_EXCELLENT),
        "rsrq_pct_good":          _pct_above(rsrq_vals, RSRQ_GOOD),
        # Physics cross-validation: RSRQ and TP are monotone functions of SINR.
        # Inconsistency (corr < 0.7) may indicate measurement artifacts in real data.
        "sinr_rsrq_consistent":   bool(abs(float(np.corrcoef(sinr_vals, rsrq_vals)[0,1])) > 0.7),
        "sinr_tp_consistent":     bool(abs(float(np.corrcoef(sinr_vals, tp_vals)[0,1]))   > 0.7),
    }

    return {"per_usid": per_usid, "area_level": area_level}


# ─────────────────────────────────────────────────────────────────────────────
# 2. CAPACITY SUMMARY  (all USIDs — computed locally, never by agents)
# ─────────────────────────────────────────────────────────────────────────────

def compute_capacity_summary(attr_df: pd.DataFrame) -> dict:
    """
    Capacity score for every USID from the attribute CSV.

    Formula (deterministic — agents receive this as a fact, not a task):
      capacity_score = (4G_cells × 1.0 + 5G_cells × 2.0)
                       × (1 + 0.15 × active_band_count)

    Rationale:
      - 5G NR cells deliver ~2× capacity vs LTE for same spectrum width
        (higher spectral efficiency: 3GPP TR 38.306 / TS 38.214)
      - Each additional active frequency band provides orthogonal spectrum
        diversity → 15% incremental capacity bonus per band
      - A site with capacity_score = 10.0 is treated as the normalization
        reference (comfortably serves ~20% of a typical area's pixels)

    Tower type classification:
      < 25 m → micro   (street-level, limited coverage radius)
      25–45 m → macro  (standard urban macro)
      > 45 m  → tall_macro (dominant coverage, possible anchor)

    Operational role classification:
      high-band-only (no Band_700) + 5G-heavy → capacity-oriented
      low-band dominant (Band_700 > 0) + 4G-only → coverage-oriented
      otherwise → mixed
    """
    if attr_df.empty:
        return {}

    band_cols = ["Band_700_cells", "Band_1800_cells",
                 "Band_2600_cells", "Band_3500_cells"]

    result = {}
    for _, row in attr_df.iterrows():
        name   = str(row.get("USID", row.get("usid", "")))
        c4g    = int(row.get("4G_cells", 0))
        c5g    = int(row.get("5G_cells", 0))
        bands  = sum(1 for col in band_cols if int(row.get(col, 0)) > 0)
        height = float(row.get("Tower_height_m", 0))

        score = (c4g * W4G + c5g * W5G) * (1 + BAND_BONUS * bands)

        # Tower type
        if height < 25:    tower_type = "micro"
        elif height <= 45: tower_type = "macro"
        else:              tower_type = "tall_macro"

        # Operational role
        has_low_band  = int(row.get("Band_700_cells", 0)) > 0
        has_high_band = int(row.get("Band_3500_cells", 0)) > 0
        if has_high_band and not has_low_band and c5g > c4g:
            op_role = "capacity-oriented"
        elif has_low_band and c5g == 0:
            op_role = "coverage-oriented"
        else:
            op_role = "mixed"

        # Technology profile
        if c5g > 0 and c4g == 0:          tech = "5G-only"
        elif c5g > c4g:                    tech = "5G-dominant"
        elif c4g > 0 and c5g == 0:         tech = "4G-only"
        else:                              tech = "mixed-4G-5G"

        result[name] = {
            "capacity_score":        round(score, 2),
            "active_band_count":     bands,
            "tower_height_m":        height,
            "tower_type":            tower_type,
            "technology_profile":    tech,
            "operational_role":      op_role,
            "4G_cells":              c4g,
            "5G_cells":              c5g,
            # Formula breakdown for transparency / audit
            "capacity_formula":      f"({c4g}×1.0 + {c5g}×2.0) × (1 + 0.15×{bands}) = {score:.2f}",
        }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3. NEIGHBOR IDENTIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def identify_neighbors(pixels: list, target_usid: str,
                       threshold: float = NEIGHBOR_OVERLAP_THRESHOLD) -> list:
    """
    Rank all USIDs by their backup overlap fraction with the target.

    A USID is a 'neighbor' (gets an RSRP image) if it appears as backup1 or
    backup2 in > threshold fraction of the target's dominant pixels.

    Threshold = 0.05 (5%): mirrors the operational convention in 3GPP SON
    neighbor-list compilation — a cell must be 'frequently the best fallback'
    before it earns a place in the active neighbor list (TS 32.541).
    """
    target_dom = [p for p in pixels if p["info"]["dominant"]["ID"] == target_usid]
    n_target   = len(target_dom)
    if n_target == 0:
        return []

    overlap_counts = {}
    for p in target_dom:
        for slot in ["backup1", "backup2"]:
            bu = p["info"].get(slot)
            if bu:
                n = bu["ID"]
                overlap_counts[n] = overlap_counts.get(n, 0) + 1

    return [
        {"usid":             name,
         "overlap_count":    count,
         "overlap_fraction": round(count / n_target, 4),
         "is_neighbor":      (count / n_target) >= threshold}
        for name, count in sorted(overlap_counts.items(),
                                   key=lambda x: x[1], reverse=True)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 4. LOAD REDISTRIBUTION ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def compute_load_redistribution(pixels: list, target_usid: str,
                                capacity_summary: dict,
                                prb_df=None) -> dict:
    """
    When the target USID shuts down, pixels in its dominant area handover to
    backup USIDs. This function quantifies three key questions:

    Q1 — Can the backup SERVE the absorbed pixels?
         rsrp_in_zone_* : signal quality the backup provides in those pixels
         handover_quality: good / partial / poor

    Q2 — Can the backup HANDLE the extra traffic?
         post_outage_load_factor: (current + absorbed) / capacity
         overload_risk: low / medium / high
         prb_df: optional PRB utilization data — when provided replaces spatial proxy
         TODO: replace spatial proxy with PRB when operator data is available

    Q3 — How SEVERE will the impact be?
         Uses three signals together (SINR alone is insufficient):

         Signal 1 — RSRP gap (dom - backup):
           > 15 dB → hard to replace  (BACKUP_GAP_DB boundary)
           8-15 dB → partial
           < 8 dB  → easy to replace  (3GPP A3 event ~8 dB offset)

         Signal 2 — Dominant RSRP (environment quality):
           > -90 dBm  → environment good
           -100 to -90 → environment marginal
           < -100 dBm → environment poor

         Signal 3 — SINR (interference vs noise context):
           > 10 dB → noise-limited (USID_00 alone, no competitors)
           < 5 dB  → potentially interference-limited OR environment-attenuated
                     — Signal 2 distinguishes these two cases

         Why three signals?
           Low SINR + good environment → interference-limited → MILD
             (many strong competitors, backup already nearly dominant)
           Low SINR + poor environment → environment-attenuated → SEVERE
             (all signals weak due to terrain/forest/buildings,
              NOT because of competing cells — incorrectly classified
              as mild if SINR alone is used)
    """

    # ── Thresholds ────────────────────────────────────────────────────────────
    RSRP_GAP_HARD    = 15.0   # dB — hard to replace (matches backup eligibility)
    RSRP_GAP_PARTIAL =  8.0   # dB — partial (aligns with 3GPP A3 event offset)

    # ── Nested helper: three-signal pixel regime classifier ───────────────────
    def classify_pixel_regime(sinr: float,
                               dom_rsrp: float,
                               gap: float) -> str:
        """
        Classify the outage impact regime for a single pixel using three signals.

        Parameters
        ----------
        sinr     : SINR at this pixel before shutdown (dB)
        dom_rsrp : dominant USID RSRP at this pixel (dBm)
        gap      : dominant_rsrp - backup_rsrp (dB, positive = backup weaker)

        Returns
        -------
        "noise_limited"           severe — USID_00 strong, alone, backup much weaker
        "interference_limited"    mild   — dense urban, backup nearly dominant
        "environment_attenuated"  severe — all signals weak due to terrain/vegetation
        "mixed"                   intermediate

        Rules (applied in order, first match wins):

        RULE 1 → noise_limited (severe):
          gap > HARD AND dom_rsrp > -90 AND sinr > 10
          Physical: USID_00 strong, alone, no competitors — user depends entirely
          on it. Backup is much weaker. Shutdown causes large quality drop.

        RULE 2 → interference_limited (mild):
          gap < PARTIAL AND dom_rsrp > -90 AND sinr < 5
          Physical: dense urban, many strong competitors, backup nearly dominant.
          Backup takes over smoothly. SINR may even improve after shutdown.

        RULE 3 → mostly_mild (easy replacement, SINR context not decisive):
          gap < PARTIAL AND dom_rsrp > -90 AND sinr >= 5
          Physical: backup nearly as strong, environment good.
          Handover quality good regardless of interference context.

        RULE 4 → environment_attenuated (severe, NOT interference-limited):
          dom_rsrp <= -90 AND gap <= HARD
          Physical: environment (forest/building/terrain) attenuates ALL signals.
          Low SINR here is NOT from competing cells — both dominant and backup
          are weak. This is the key correction vs SINR-only classification.

        RULE 5 → noise_limited (severe, coverage-hole-like):
          dom_rsrp <= -90 AND gap > HARD
          Physical: edge of coverage, backup barely reachable.

        RULE 6 → mixed:
          gap > HARD AND dom_rsrp > -90 AND sinr < 5
          Physical: USID_00 dominates despite interference, but backup is weak.
          Moderate quality drop expected.

        RULE 7 → mixed (all other cases)
        """
        # Determine replaceability from RSRP gap
        if gap > RSRP_GAP_HARD:
            replaceability = "hard"
        elif gap < RSRP_GAP_PARTIAL:
            replaceability = "easy"
        else:
            replaceability = "partial"

        # Determine environment quality from dominant RSRP
        if dom_rsrp > RSRP_GOOD:       # > -90 dBm
            environment = "good"
        elif dom_rsrp > RSRP_MODERATE: # -100 to -90 dBm
            environment = "marginal"
        else:                           # < -100 dBm
            environment = "poor"

        # Determine SINR context
        if sinr > SINR_HIGH_REGIME:    # > 10 dB
            sinr_ctx = "high"
        elif sinr < SINR_LOW_REGIME:   # < 5 dB
            sinr_ctx = "low"
        else:
            sinr_ctx = "mixed"

        # Apply rules in order
        # RULE 1: noise-limited severe
        if (replaceability == "hard"
                and environment == "good"
                and sinr_ctx == "high"):
            return "noise_limited"

        # RULE 2: genuine interference-limited mild
        if (replaceability == "easy"
                and environment == "good"
                and sinr_ctx == "low"):
            return "interference_limited"

        # RULE 3: easy replacement, environment good
        if replaceability == "easy" and environment == "good":
            return "interference_limited"

        # RULE 4: environment attenuation — key correction vs SINR-only
        if environment in ("marginal", "poor"):
            return "environment_attenuated"

        # RULE 5: noise-limited at coverage edge
        if replaceability == "hard" and environment == "good":
            if sinr_ctx == "low":
                return "mixed"           # RULE 6
            return "noise_limited"       # catches high + partial SINR

        # RULE 7: all other cases
        return "mixed"

    # ── Main computation ──────────────────────────────────────────────────────
    total      = len(pixels)
    target_dom = [p for p in pixels
                  if p["info"]["dominant"]["ID"] == target_usid]
    n_target   = len(target_dom)

    if n_target == 0:
        return {"error": f"{target_usid} not found as dominant USID"}

    # Coverage holes (pixels with no backup at all)
    hole_pxs  = [p for p in target_dom if p["info"]["backup1"] is None]
    hole_frac = round(len(hole_pxs) / n_target, 4)

    # Area-level SINR stats (kept for cross-validation and SINR map context)
    sinr_dom       = [p["info"]["sinr_db"] for p in target_dom]
    high_sinr_frac = round(
        sum(1 for v in sinr_dom if v > SINR_HIGH_REGIME) / n_target, 4)
    low_sinr_frac  = round(
        sum(1 for v in sinr_dom if v < SINR_LOW_REGIME) / n_target, 4)

    # Area-level impact regime using three-signal classifier
    # Classify every pixel in target's dominant area against the dominant RSRP
    # and SINR — gap is 0 here (we are characterising the area overall,
    # not a specific backup). Use gap=0 to force environment/SINR signals.
    regime_counts = {"noise_limited": 0, "interference_limited": 0,
                     "environment_attenuated": 0, "mixed": 0}
    for p in target_dom:
        info     = p["info"]
        sinr     = info["sinr_db"]
        dom_rsrp = info["dominant"]["rsrp"]
        # For area-level: use gap=0 (no specific backup) so classification
        # is driven by environment quality and SINR context only
        regime = classify_pixel_regime(sinr, dom_rsrp, gap=0.0)
        regime_counts[regime] = regime_counts.get(regime, 0) + 1

    # Severe = noise_limited + environment_attenuated
    # Mild   = interference_limited
    severe_frac = round(
        (regime_counts["noise_limited"] +
         regime_counts["environment_attenuated"]) / n_target, 4)
    mild_frac   = round(regime_counts["interference_limited"] / n_target, 4)

    if   severe_frac > 0.5: impact_regime = "mostly_severe"
    elif mild_frac   > 0.5: impact_regime = "mostly_mild"
    else:                    impact_regime = "mixed"

    # Per-backup pixel data collection
    bdata = {}
    for p in target_dom:
        info     = p["info"]
        dom_rsrp = info["dominant"]["rsrp"]
        sinr     = info["sinr_db"]
        for slot in ["backup1", "backup2"]:
            bu = info.get(slot)
            if bu:
                n   = bu["ID"]
                gap = dom_rsrp - bu["rsrp"]   # positive: dominant stronger
                if n not in bdata:
                    bdata[n] = {
                        "pixels":    0,
                        "rsrp":      [],
                        "hard_gap":  0,
                        "easy_gap":  0,
                        # three-signal regime counts
                        "regime_noise_limited":          0,
                        "regime_interference_limited":   0,
                        "regime_environment_attenuated": 0,
                        "regime_mixed":                  0,
                    }
                bdata[n]["pixels"] += 1
                bdata[n]["rsrp"].append(bu["rsrp"])

                # RSRP gap counts (for legacy hard/easy fraction fields)
                if gap > RSRP_GAP_HARD:
                    bdata[n]["hard_gap"] += 1
                elif gap < RSRP_GAP_PARTIAL:
                    bdata[n]["easy_gap"] += 1

                # Three-signal regime per pixel
                regime = classify_pixel_regime(sinr, dom_rsrp, gap)
                key    = f"regime_{regime}"
                bdata[n][key] = bdata[n].get(key, 0) + 1

    per_backup = {}
    for name, d in bdata.items():
        absorb   = d["pixels"]
        vals     = sorted(d["rsrp"])
        n_vals   = len(vals)
        pct_good = _pct_above(vals, RSRP_GOOD)

        if pct_good >= 70:   hq = "good"
        elif pct_good >= 40: hq = "partial"
        else:                hq = "poor"

        # Current dominant load proxy
        curr_frac   = sum(1 for p in pixels
                          if p["info"]["dominant"]["ID"] == name) / total
        absorb_frac = absorb / total
        cap         = capacity_summary.get(name, {})
        cap_score   = cap.get("capacity_score", 1.0)

        # Load factor: PRB mode (real data) vs spatial proxy (placeholder)
        if prb_df is not None and len(prb_df) > 0:
            t_rows = prb_df[prb_df["USID"] == target_usid]
            b_rows = prb_df[prb_df["USID"] == name]
            if not t_rows.empty and not b_rows.empty:
                target_prb    = float(t_rows["prb_utilization"].mean())
                backup_prb    = float(b_rows["prb_utilization"].mean())
                absorbed_load = (absorb / n_target) * target_prb
                load_factor   = round(backup_prb + absorbed_load, 3)
                load_mode     = "prb_measured"
                if   load_factor > 0.85: risk = "high"
                elif load_factor > 0.70: risk = "medium"
                else:                    risk = "low"
            else:
                norm_cap    = cap_score / 10.0 if cap_score > 0 else 0.1
                load_factor = round((curr_frac + absorb_frac) / norm_cap, 3)
                load_mode   = "spatial_proxy_fallback"
                if   load_factor > 0.8: risk = "high"
                elif load_factor > 0.5: risk = "medium"
                else:                   risk = "low"
        else:
            # TODO: replace with real PRB utilization (3GPP TS 32.541)
            norm_cap    = cap_score / 10.0 if cap_score > 0 else 0.1
            load_factor = round((curr_frac + absorb_frac) / norm_cap, 3)
            load_mode   = "spatial_proxy"
            if   load_factor > 0.8: risk = "high"
            elif load_factor > 0.5: risk = "medium"
            else:                   risk = "low"

        # Q3 — three-signal regime note for this backup
        # Severe = noise_limited + environment_attenuated
        # Mild   = interference_limited
        nl  = d.get("regime_noise_limited", 0)
        il  = d.get("regime_interference_limited", 0)
        ea  = d.get("regime_environment_attenuated", 0)
        mx  = d.get("regime_mixed", 0)
        severe_px = nl + ea
        mild_px   = il

        if   severe_px / absorb > 0.6: regime_note = "mostly_severe"
        elif mild_px   / absorb > 0.6: regime_note = "mostly_mild"
        else:                           regime_note = "mixed"

        # Legacy gap fractions kept for backward compatibility
        hard_frac = round(d["hard_gap"] / max(absorb, 1), 4)
        easy_frac = round(d["easy_gap"] / max(absorb, 1), 4)

        per_backup[name] = {
            # Q1 — can it serve?
            "absorption_pixel_count":              absorb,
            "absorption_fraction_of_target":       round(absorb / n_target, 4),
            "absorption_fraction_of_total":        round(absorb_frac, 4),
            "rsrp_in_zone_mean_dbm":               round(sum(vals) / n_vals, 2),
            "rsrp_in_zone_p50_dbm":                _percentile(vals, 0.50),
            "rsrp_in_zone_p10_dbm":                _percentile(vals, 0.10),
            "rsrp_pct_above_good_in_zone":         pct_good,
            "handover_quality":                    hq,
            # Q2 — can it handle the load?
            "current_dominant_fraction":           round(curr_frac, 4),
            "capacity_score":                      cap_score,
            "post_outage_load_factor":             load_factor,
            "overload_risk":                       risk,
            "load_mode":                           load_mode,
            # Q3 — three-signal regime classification
            "sinr_regime_impact_note":             regime_note,
            "regime_noise_limited_fraction":       round(nl  / absorb, 4),
            "regime_interference_limited_fraction":round(il  / absorb, 4),
            "regime_environment_attenuated_fraction": round(ea / absorb, 4),
            "regime_mixed_fraction":               round(mx  / absorb, 4),
            # Legacy RSRP gap fractions (kept for schema compatibility)
            "hard_gap_fraction_absorbed":          hard_frac,
            "easy_gap_fraction_absorbed":          easy_frac,
        }

    primary = max(per_backup,
                  key=lambda n: per_backup[n]["absorption_fraction_of_target"],
                  default=None)

    return {
        "target_usid":                      target_usid,
        "target_dominant_pixels":           n_target,
        "target_dominant_fraction":         round(n_target / total, 4),
        "coverage_hole_pixels":             len(hole_pxs),
        "coverage_hole_fraction":           hole_frac,
        "target_dom_sinr_mean":             round(float(np.mean(sinr_dom)), 2),
        "target_dom_high_sinr_fraction":    high_sinr_frac,
        "target_dom_low_sinr_fraction":     low_sinr_frac,
        "dominant_area_severe_fraction":    severe_frac,
        "dominant_area_mild_fraction":      mild_frac,
        "dominant_area_impact_regime":      impact_regime,
        "primary_backup_usid":              primary,
        "per_backup":                       per_backup,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. IMAGE GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_rsrp_image(pixels, usid_name, target_usid,
                        grid_rows, grid_cols, lat_range, lon_range, output_dir):
    """
    RSRP heatmap for one USID.

    What the image communicates that statistics cannot:
      - Spatial contiguity of weak zones (a connected hole vs scattered pixels)
      - Directionality of RSRP decay relative to the target's dominant boundary
      - Where the backup's signal gradient crosses from good to poor relative
        to the target's dominant area — used for geographic correlation in Stage 3

    Overlays:
      yellow solid contour  = this USID's own dominance boundary
      red dashed contour    = target USID's dominant area boundary (reference)
      grey pixels           = USID not visible here (not dominant, not backup)
    """
    lat_min, lat_max = lat_range
    lon_min, lon_max = lon_range
    ext  = [lon_min, lon_max, lat_min, lat_max]
    lons = np.linspace(lon_min, lon_max, grid_cols)
    lats = np.linspace(lat_min, lat_max, grid_rows)

    rsrp_grid  = np.full((grid_rows, grid_cols), np.nan, dtype=np.float32)
    dom_mask   = np.zeros((grid_rows, grid_cols), dtype=bool)
    tgt_mask   = np.zeros((grid_rows, grid_cols), dtype=bool)

    for r in range(grid_rows):
        for c in range(grid_cols):
            info = pixels[r * grid_cols + c]["info"]
            if info["dominant"]["ID"] == usid_name:
                rsrp_grid[r, c] = info["dominant"]["rsrp"]
                dom_mask[r, c]  = True
            elif info.get("backup1") and info["backup1"]["ID"] == usid_name:
                rsrp_grid[r, c] = info["backup1"]["rsrp"]
            elif info.get("backup2") and info["backup2"]["ID"] == usid_name:
                rsrp_grid[r, c] = info["backup2"]["rsrp"]
            if info["dominant"]["ID"] == target_usid:
                tgt_mask[r, c] = True

    cmap = LinearSegmentedColormap.from_list(
        "rsrp", ["#8B0000","#FF0000","#FFA500","#FFFF00","#00FF00","#0000FF"])
    cmap.set_bad("lightgrey")

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(rsrp_grid, origin="upper", cmap=cmap, vmin=-115, vmax=-55,
                   extent=ext, aspect="auto")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("RSRP (dBm)", fontsize=9)
    for thresh, lbl in [(-80,"Exc."),(-90,"Good"),(-100,"Mod.")]:
        norm = (thresh - (-115)) / (-55 - (-115))
        cb.ax.axhline(norm, color="white", lw=1, ls="--")
        cb.ax.text(1.3, norm, lbl, va="center", fontsize=6, transform=cb.ax.transAxes)

    if dom_mask.any():
        ax.contour(lons, lats, dom_mask.astype(float),
                   levels=[0.5], colors=["yellow"], linewidths=[2])
    if usid_name != target_usid and tgt_mask.any():
        ax.contour(lons, lats, tgt_mask.astype(float),
                   levels=[0.5], colors=["red"], linewidths=[1.5], linestyles=["dashed"])

    ax.set_title(
        f"RSRP — {usid_name}"
        + (f"\nyellow=own dominance  |  red-dashed={target_usid} area"
           if usid_name != target_usid else "\nyellow=dominance boundary"),
        fontsize=9, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")

    path = Path(output_dir) / f"rsrp_{usid_name}.png"
    _save_fig(fig, path)
    return path


def _build_dom_grids(pixels, all_usid_names, grid_rows, grid_cols, lat_range, lon_range):
    """Build shared data structures used by both dominance map functions."""
    lat_min, lat_max = lat_range
    lon_min, lon_max = lon_range
    lons = np.linspace(lon_min, lon_max, grid_cols)
    lats = np.linspace(lat_min, lat_max, grid_rows)
    ext  = [lon_min, lon_max, lat_min, lat_max]

    color_map = {name: PALETTE[i % len(PALETTE)]
                 for i, name in enumerate(sorted(all_usid_names))}

    dom_grid = np.array(
        [[pixels[r*grid_cols+c]["info"]["dominant"]["ID"]
          for c in range(grid_cols)] for r in range(grid_rows)])

    def _hex_rgb(h):
        return [int(h[i:i+2], 16)/255 for i in (1, 3, 5)]

    rgb_grid = np.array([[_hex_rgb(color_map[dom_grid[r,c]])
                          for c in range(grid_cols)] for r in range(grid_rows)])

    # Tower positions: lat/lon from dominant slot of each USID
    tower_pos = {}
    for p in pixels:
        dom = p["info"]["dominant"]
        if dom["ID"] not in tower_pos:
            tower_pos[dom["ID"]] = (dom["lat"], dom["lon"])
        for slot in ["backup1","backup2"]:
            bu = p["info"].get(slot)
            if bu and bu["ID"] not in tower_pos:
                tower_pos[bu["ID"]] = (bu["lat"], bu["lon"])

    return lons, lats, ext, color_map, dom_grid, rgb_grid, tower_pos


def generate_dominance_map(pixels, all_usid_names, target_usid,
                           grid_rows, grid_cols, lat_range, lon_range,
                           output_dir, n_tiles=1):
    """
    Two-image dominance map — replaces tiling approach.

    Image 1 — Full network overview (dominance_map_overview.png):
      Full area, all USIDs colored (colors may repeat for large networks — acceptable).
      Each USID labeled with a small triangle marker at its tower position.
      Target USID: bold black contour + red triangle.
      Purpose: global spatial context for Stage 3 agent.

    Image 2 — Target neighborhood zoom (dominance_map_neighborhood.png):
      Zoomed to target dominant area ± 30% margin.
      Only target + direct neighbors colored; rest shown as light grey.
      Full legend with no color conflicts (≤8 USIDs).
      Purpose: precise neighbor layout for Stage 1 agent.
    """
    lons, lats, ext, color_map, dom_grid, rgb_grid, tower_pos =         _build_dom_grids(pixels, all_usid_names, grid_rows, grid_cols,
                         lat_range, lon_range)

    tgt_mask = (dom_grid == target_usid).astype(float)
    paths    = []

    # ── Image 1: Full network overview with USID labels ───────────────────────
    fig, ax = plt.subplots(figsize=(9, 8))
    ax.imshow(rgb_grid, origin="lower", extent=ext, aspect="auto", alpha=0.85)

    # Target USID bold black boundary
    if tgt_mask.any():
        ax.contour(lons, lats, tgt_mask,
                   levels=[0.5], colors=["black"], linewidths=[3.0])

    # Label every USID at its tower position
    fontsize = max(4, min(7, 60 // len(all_usid_names)))
    for name in all_usid_names:
        if name not in tower_pos:
            continue
        t_lat, t_lon = tower_pos[name]
        is_target = (name == target_usid)
        color  = "red"   if is_target else "black"
        marker = "^"
        size   = 80 if is_target else 35
        ax.scatter(t_lon, t_lat, marker=marker, s=size,
                   c=color, zorder=5, linewidths=0.5,
                   edgecolors="white")
        # Short label: just the numeric ID part e.g. "00" from "USID_00"
        short = name.split("_")[-1] if "_" in name else name
        ax.annotate(short,
                    xy=(t_lon, t_lat),
                    xytext=(2, 3), textcoords="offset points",
                    fontsize=fontsize, color=color,
                    fontweight="bold" if is_target else "normal",
                    zorder=6)

    ax.set_title(
        f"Dominant USID Map — Full Network Overview\n"
        f"Black contour = {target_usid} boundary  |  "
        f"Red = {target_usid} tower  |  Labels = USID ID",
        fontsize=9, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")

    p1 = Path(output_dir) / "dominance_map_overview.png"
    _save_fig(fig, p1)
    paths.append(p1)

    # ── Image 2: Target neighborhood zoom ────────────────────────────────────
    # Find bounding box of target dominant area + 30% margin
    tgt_rows, tgt_cols = np.where(dom_grid == target_usid)
    if len(tgt_rows) > 0:
        margin_r = max(3, int((tgt_rows.max() - tgt_rows.min()) * 0.30))
        margin_c = max(3, int((tgt_cols.max() - tgt_cols.min()) * 0.30))
        r0 = max(0, tgt_rows.min() - margin_r)
        r1 = min(grid_rows, tgt_rows.max() + margin_r + 1)
        c0 = max(0, tgt_cols.min() - margin_c)
        c1 = min(grid_cols, tgt_cols.max() + margin_c + 1)
    else:
        r0, r1, c0, c1 = 0, grid_rows, 0, grid_cols

    z_lons = lons[c0:c1]; z_lats = lats[r0:r1]
    z_ext  = [z_lons[0], z_lons[-1], z_lats[0], z_lats[-1]]
    z_dom  = dom_grid[r0:r1, c0:c1]
    z_tgt  = tgt_mask[r0:r1, c0:c1]

    # Which USIDs appear in this zoom window
    zoom_usids = sorted(set(z_dom.flatten()))

    # Build zoomed RGB: neighbors in full color, others in light grey
    neighbor_set = set(zoom_usids)   # all visible USIDs get color in zoom

    def _hex_rgb(h):
        return [int(h[i:i+2], 16)/255 for i in (1, 3, 5)]

    grey = [0.88, 0.88, 0.88]
    z_rgb = np.array([[_hex_rgb(color_map[z_dom[r,c]])
                       if z_dom[r,c] in neighbor_set else grey
                       for c in range(z_dom.shape[1])]
                      for r in range(z_dom.shape[0])])

    fig, ax = plt.subplots(figsize=(8, 7))
    ax.imshow(z_rgb, origin="lower", extent=z_ext, aspect="auto", alpha=0.85)

    if z_tgt.any():
        ax.contour(z_lons, z_lats, z_tgt,
                   levels=[0.5], colors=["black"], linewidths=[3.0])

    # Label USIDs visible in zoom window
    for name in zoom_usids:
        if name not in tower_pos:
            continue
        t_lat, t_lon = tower_pos[name]
        if not (z_lats[0] <= t_lat <= z_lats[-1] and
                z_lons[0] <= t_lon <= z_lons[-1]):
            continue
        is_target = (name == target_usid)
        color  = "red" if is_target else "black"
        size   = 100  if is_target else 50
        ax.scatter(t_lon, t_lat, marker="^", s=size, c=color,
                   zorder=5, linewidths=0.5, edgecolors="white")
        short = name.split("_")[-1] if "_" in name else name
        ax.annotate(short,
                    xy=(t_lon, t_lat),
                    xytext=(3, 4), textcoords="offset points",
                    fontsize=8, color=color,
                    fontweight="bold" if is_target else "normal",
                    zorder=6)

    # Legend for visible USIDs
    legend_handles = [
        mpatches.Patch(color=color_map[n],
                       label=n + (" ← TARGET" if n == target_usid else ""))
        for n in zoom_usids
    ]
    ax.legend(handles=legend_handles, loc="lower right",
              fontsize=7, title="Dominant USID")

    ax.set_title(
        f"Dominant USID Map — Neighborhood Zoom\n"
        f"Target: {target_usid}  |  Black contour = {target_usid} boundary",
        fontsize=9, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")

    p2 = Path(output_dir) / "dominance_map_neighborhood.png"
    _save_fig(fig, p2)
    paths.append(p2)

    return paths


def generate_sinr_map(pixels, target_usid, grid_rows, grid_cols,
                      lat_range, lon_range, output_dir):
    """
    SINR heatmap with the target USID's dominant area boundary.

    Primary analytical use in Stage 3:
      Identify which geographic sub-zones inside the target's coverage area
      are noise-limited (high SINR → severe impact) vs interference-limited
      (low SINR → mild impact), then correlate with real-map land use.
    """
    lat_min, lat_max = lat_range
    lon_min, lon_max = lon_range
    ext  = [lon_min, lon_max, lat_min, lat_max]
    lons = np.linspace(lon_min, lon_max, grid_cols)
    lats = np.linspace(lat_min, lat_max, grid_rows)

    sinr_grid = np.array([[pixels[r*grid_cols+c]["info"]["sinr_db"]
                           for c in range(grid_cols)] for r in range(grid_rows)],
                         dtype=np.float32)
    tgt_mask  = np.array([[pixels[r*grid_cols+c]["info"]["dominant"]["ID"] == target_usid
                           for c in range(grid_cols)] for r in range(grid_rows)],
                         dtype=float)

    cmap = LinearSegmentedColormap.from_list(
        "sinr", ["#4B0082","#0000FF","#00BFFF","#00FF00","#FFD700","#FF4500"])

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(sinr_grid, origin="upper", cmap=cmap, vmin=-10, vmax=30,
                   extent=ext, aspect="auto")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("SINR (dB)", fontsize=9)
    for thresh, lbl in [(20,"Exc."),(13,"Good"),(0,"Mod.")]:
        norm = (thresh-(-10))/(30-(-10))
        cb.ax.axhline(norm, color="white", lw=1, ls="--")
        cb.ax.text(1.3, norm, lbl, va="center", fontsize=6, transform=cb.ax.transAxes)

    if tgt_mask.any():
        ax.contour(lons, lats, tgt_mask, levels=[0.5],
                   colors=["red"], linewidths=[2])

    ax.set_title(f"SINR Map  (red = {target_usid} dominant area)\n"
                 f"High SINR inside → noise-limited → severe post-outage impact",
                 fontsize=9, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")

    path = Path(output_dir) / "sinr_map.png"
    _save_fig(fig, path)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 6. MASTER RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_local_preprocessing(coverage_json_path, attr_csv_path,
                             target_usid, output_dir, map_image_path=None):
    """
    Run the complete local preprocessing pipeline and save results.

    Returns preprocess dict containing:
      coverage_summary    — per-USID RSRP stats + area-level quality
      capacity_summary    — capacity score for every USID (pre-computed facts)
      overlap_info        — neighbor ranking by backup overlap fraction
      load_redistribution — absorption + overload risk per backup USID
      image_paths         — dict of generated image file paths
      neighbor_usids      — list of neighbor USID names (get RSRP images)
      all_usid_names      — all USID names in the area
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(coverage_json_path) as f:
        cov = json.load(f)

    # Support both {"pixels": [...]} wrapper and flat list
    pixels = cov["pixels"] if isinstance(cov, dict) else cov

    # Derive grid dimensions and lat/lon ranges directly from pixel data.
    # This makes preprocessing compatible with real operator data which
    # will not have a grid_config header block.
    all_lats  = sorted(set(round(p["lat"], 6) for p in pixels))
    all_lons  = sorted(set(round(p["lon"], 6) for p in pixels))
    grid_rows = len(all_lats)
    grid_cols = len(all_lons)
    lat_range = (all_lats[0], all_lats[-1])
    lon_range = (all_lons[0], all_lons[-1])
    print(f"[PreProcess] Grid: {grid_rows}×{grid_cols}  "
          f"lat [{lat_range[0]:.4f}, {lat_range[1]:.4f}]  "
          f"lon [{lon_range[0]:.4f}, {lon_range[1]:.4f}]")

    attr_df = pd.read_csv(attr_csv_path) if attr_csv_path else pd.DataFrame()

    print("[PreProcess] Coverage summary…")
    coverage_summary = compute_coverage_summary(pixels)

    print("[PreProcess] Capacity summary (all USIDs)…")
    capacity_summary = compute_capacity_summary(attr_df)

    print("[PreProcess] Neighbor identification…")
    overlap_info   = identify_neighbors(pixels, target_usid)
    neighbor_usids = [o["usid"] for o in overlap_info if o["is_neighbor"]]

    print("[PreProcess] Load redistribution analysis…")
    load_redist = compute_load_redistribution(pixels, target_usid, capacity_summary)

    all_usid_names = list(coverage_summary["per_usid"].keys())

    print("[PreProcess] Generating images…")
    image_paths = {}

    # RSRP images: target + neighbors only
    for usid in list(dict.fromkeys([target_usid] + neighbor_usids)):
        p = generate_rsrp_image(pixels, usid, target_usid,
                                grid_rows, grid_cols, lat_range, lon_range, out)
        image_paths[f"rsrp_{usid}"] = str(p)

    # Dominance maps: overview (full network) + neighborhood (target zoom)
    dom_paths = generate_dominance_map(
        pixels, all_usid_names, target_usid,
        grid_rows, grid_cols, lat_range, lon_range, out)
    image_paths["dominance_map_overview"]      = str(dom_paths[0])
    image_paths["dominance_map_neighborhood"]  = str(dom_paths[1])

    # SINR map
    sinr_path = generate_sinr_map(
        pixels, target_usid, grid_rows, grid_cols, lat_range, lon_range, out)
    image_paths["sinr_map"] = str(sinr_path)

    if map_image_path:
        image_paths["real_map"] = str(map_image_path)

    preprocess_out = {
        "target_usid":         target_usid,
        "coverage_summary":    coverage_summary,
        "capacity_summary":    capacity_summary,
        "overlap_info":        overlap_info,
        "load_redistribution": load_redist,
        "image_paths":         image_paths,
        "neighbor_usids":      neighbor_usids,
        "all_usid_names":      all_usid_names,
    }

    stats_path = out / "preprocessing_stats.json"
    with open(stats_path, "w") as f:
        json.dump(preprocess_out, f, indent=2)
    print(f"[PreProcess] Done → {stats_path}")

    return preprocess_out


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Run local preprocessing for USID outage pipeline.")
    p.add_argument("--coverage-json", required=True,
                   help="Path to usid_coverage_pixels.json")
    p.add_argument("--attr-csv",      required=True,
                   help="Path to usid_attributes.csv")
    p.add_argument("--target-usid",   required=True,
                   help="Target USID to assess (e.g. USID_00)")
    p.add_argument("--output-dir",    required=True,
                   help="Directory to save all outputs")
    p.add_argument("--real-map",      default=None,
                   help="Optional path to real map image (PNG/JPG)")
    args = p.parse_args()

    run_local_preprocessing(
        coverage_json_path=args.coverage_json,
        attr_csv_path=args.attr_csv,
        target_usid=args.target_usid,
        output_dir=args.output_dir,
        map_image_path=args.real_map,
    )