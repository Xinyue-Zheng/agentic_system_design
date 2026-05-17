import json
import pandas as pd
from pathlib import Path
from tools.cache import get_cached

import numpy as np
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

def _usid_from_id(id_str: str) -> str:
    """'USID_09_S2' → 'USID_09'. Idempotent for parent-level IDs."""
    if (len(id_str) >= 3
            and id_str[-3] == "_"
            and id_str[-2] == "S"
            and id_str[-1].isdigit()):
        return id_str[:-3]
    return id_str


# ─────────────────────────────────────────────────────────────────────────────
# 1. COVERAGE SUMMARY (raw)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_coverage_summary_raw(pixels: list) -> dict:
    total = len(pixels)
    sector_ids = set()
    parent_ids = set()
    for p in pixels:
        info = p["info"]
        sector_ids.add(info["dominant"]["ID"])
        parent_ids.add(_usid_from_id(info["dominant"]["ID"]))
        if info.get("backup1"):
            sector_ids.add(info["backup1"]["ID"])
            parent_ids.add(_usid_from_id(info["backup1"]["ID"]))
        if info.get("backup2"):
            sector_ids.add(info["backup2"]["ID"])
            parent_ids.add(_usid_from_id(info["backup2"]["ID"]))

    s_dom_counts    = {n: 0  for n in sector_ids}
    s_backup_counts = {n: 0  for n in sector_ids}
    s_rsrp_samples  = {n: [] for n in sector_ids}
    s_tower_pos     = {}
    p_dom_counts    = {n: 0  for n in parent_ids}
    p_backup_counts = {n: 0  for n in parent_ids}
    p_rsrp_samples  = {n: [] for n in parent_ids}
    p_tower_pos     = {}

    for p in pixels:
        info   = p["info"]
        dom    = info["dominant"]
        sid    = dom["ID"]
        pid    = _usid_from_id(sid)
        s_dom_counts[sid] += 1
        p_dom_counts[pid] += 1
        s_rsrp_samples[sid].append(dom["rsrp"])
        p_rsrp_samples[pid].append(dom["rsrp"])
        if sid not in s_tower_pos:
            s_tower_pos[sid] = (dom["lat"], dom["lon"])
        if pid not in p_tower_pos:
            p_tower_pos[pid] = (dom["lat"], dom["lon"])
        for slot in ["backup1", "backup2"]:
            bu = info.get(slot)
            if bu:
                bs  = bu["ID"]
                bp  = _usid_from_id(bs)
                s_backup_counts[bs] += 1
                p_backup_counts[bp] += 1
                s_rsrp_samples[bs].append(bu["rsrp"])
                p_rsrp_samples[bp].append(bu["rsrp"])
                if bs not in s_tower_pos:
                    s_tower_pos[bs] = (bu["lat"], bu["lon"])
                if bp not in p_tower_pos:
                    p_tower_pos[bp] = (bu["lat"], bu["lon"])

    def _build_entry(dom_count, backup_count, rsrp_vals, tpos):
        dom_frac = dom_count / total
        if   dom_frac >= DOM_ANCHOR: role = "dominant-anchor"
        elif dom_frac >= DOM_STRONG: role = "strong-supporting"
        elif dom_frac >= DOM_LOCAL:  role = "localized-supporting"
        else:                        role = "edge-limited"
        vals = sorted(rsrp_vals)
        n    = len(vals)
        return {
            "tower_lat":                tpos[0],
            "tower_lon":                tpos[1],
            "dominant_pixel_count":     dom_count,
            "dominant_pixel_fraction":  round(dom_frac, 4),
            "backup_pixel_count":       backup_count,
            "backup_pixel_fraction":    round(backup_count / total, 4),
            "inferred_role":            role,
            "rsrp_sample_count":        n,
            "rsrp_mean_dbm":            round(sum(vals) / n, 2) if n else None,
            "rsrp_p10_dbm":             _percentile(vals, 0.10),
            "rsrp_p50_dbm":             _percentile(vals, 0.50),
            "rsrp_p90_dbm":             _percentile(vals, 0.90),
            "rsrp_pct_above_excellent": _pct_above(vals, RSRP_EXCELLENT),
            "rsrp_pct_above_good":      _pct_above(vals, RSRP_GOOD),
            "rsrp_pct_above_moderate":  _pct_above(vals, RSRP_MODERATE),
        }

    per_sector = {
        name: _build_entry(s_dom_counts[name], s_backup_counts[name],
                           s_rsrp_samples[name], s_tower_pos.get(name, (None, None)))
        for name in sorted(sector_ids)
    }
    per_usid = {
        name: _build_entry(p_dom_counts[name], p_backup_counts[name],
                           p_rsrp_samples[name], p_tower_pos.get(name, (None, None)))
        for name in sorted(parent_ids)
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
        "sinr_rsrq_consistent":   bool(abs(float(np.corrcoef(sinr_vals, rsrq_vals)[0,1])) > 0.7),
        "sinr_tp_consistent":     bool(abs(float(np.corrcoef(sinr_vals, tp_vals)[0,1]))   > 0.7),
    }

    return {"per_usid": per_usid, "per_sector": per_sector, "area_level": area_level}


# ─────────────────────────────────────────────────────────────────────────────
# 2. CAPACITY SUMMARY (raw)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_capacity_summary_raw(attr_df: pd.DataFrame) -> dict:
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

        if height < 25:    tower_type = "micro"
        elif height <= 45: tower_type = "macro"
        else:              tower_type = "tall_macro"

        has_low_band  = int(row.get("Band_700_cells", 0)) > 0
        has_high_band = int(row.get("Band_3500_cells", 0)) > 0
        if has_high_band and not has_low_band and c5g > c4g:
            op_role = "capacity-oriented"
        elif has_low_band and c5g == 0:
            op_role = "coverage-oriented"
        else:
            op_role = "mixed"

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
            "capacity_formula":      f"({c4g}×1.0 + {c5g}×2.0) × (1 + 0.15×{bands}) = {score:.2f}",
        }

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3. NEIGHBOR IDENTIFICATION (raw)
# ─────────────────────────────────────────────────────────────────────────────

def _identify_neighbors_raw(pixels: list, target_usid: str,
                            threshold: float = NEIGHBOR_OVERLAP_THRESHOLD) -> list:
    target_dom = [p for p in pixels
                  if _usid_from_id(p["info"]["dominant"]["ID"]) == target_usid]
    n_target   = len(target_dom)
    if n_target == 0:
        return []

    overlap_counts = {}
    for p in target_dom:
        for slot in ["backup1", "backup2"]:
            bu = p["info"].get(slot)
            if bu:
                n = _usid_from_id(bu["ID"])
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
# 4. LOAD REDISTRIBUTION (raw)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_load_redistribution_raw(pixels: list, target_usid: str,
                                     capacity_summary: dict,
                                     prb_df=None) -> dict:
    RSRP_GAP_HARD    = 15.0
    RSRP_GAP_PARTIAL =  8.0

    def classify_pixel_regime(sinr: float,
                               dom_rsrp: float,
                               gap: float) -> str:
        if gap > RSRP_GAP_HARD:
            replaceability = "hard"
        elif gap < RSRP_GAP_PARTIAL:
            replaceability = "easy"
        else:
            replaceability = "partial"

        if dom_rsrp > RSRP_GOOD:
            environment = "good"
        elif dom_rsrp > RSRP_MODERATE:
            environment = "marginal"
        else:
            environment = "poor"

        if sinr > SINR_HIGH_REGIME:
            sinr_ctx = "high"
        elif sinr < SINR_LOW_REGIME:
            sinr_ctx = "low"
        else:
            sinr_ctx = "mixed"

        if (replaceability == "hard"
                and environment == "good"
                and sinr_ctx == "high"):
            return "noise_limited"

        if (replaceability == "easy"
                and environment == "good"
                and sinr_ctx == "low"):
            return "interference_limited"

        if replaceability == "easy" and environment == "good":
            return "interference_limited"

        if environment in ("marginal", "poor"):
            return "environment_attenuated"

        if replaceability == "hard" and environment == "good":
            if sinr_ctx == "low":
                return "mixed"
            return "noise_limited"

        return "mixed"

    total      = len(pixels)
    target_dom = [p for p in pixels
                  if _usid_from_id(p["info"]["dominant"]["ID"]) == target_usid]
    n_target   = len(target_dom)

    if n_target == 0:
        return {"error": f"{target_usid} not found as dominant USID"}

    hole_pxs  = [p for p in target_dom if p["info"]["backup1"] is None]
    hole_frac = round(len(hole_pxs) / n_target, 4)

    sinr_dom       = [p["info"]["sinr_db"] for p in target_dom]
    high_sinr_frac = round(
        sum(1 for v in sinr_dom if v > SINR_HIGH_REGIME) / n_target, 4)
    low_sinr_frac  = round(
        sum(1 for v in sinr_dom if v < SINR_LOW_REGIME) / n_target, 4)

    regime_counts = {"noise_limited": 0, "interference_limited": 0,
                     "environment_attenuated": 0, "mixed": 0}
    for p in target_dom:
        info     = p["info"]
        sinr     = info["sinr_db"]
        dom_rsrp = info["dominant"]["rsrp"]
        regime = classify_pixel_regime(sinr, dom_rsrp, gap=0.0)
        regime_counts[regime] = regime_counts.get(regime, 0) + 1

    severe_frac = round(
        (regime_counts["noise_limited"] +
         regime_counts["environment_attenuated"]) / n_target, 4)
    mild_frac   = round(regime_counts["interference_limited"] / n_target, 4)

    if   severe_frac > 0.5: impact_regime = "mostly_severe"
    elif mild_frac   > 0.5: impact_regime = "mostly_mild"
    else:                    impact_regime = "mixed"

    bdata = {}
    for p in target_dom:
        info     = p["info"]
        dom_rsrp = info["dominant"]["rsrp"]
        sinr     = info["sinr_db"]
        for slot in ["backup1", "backup2"]:
            bu = info.get(slot)
            if bu:
                n   = _usid_from_id(bu["ID"])
                gap = dom_rsrp - bu["rsrp"]
                if n not in bdata:
                    bdata[n] = {
                        "pixels":    0,
                        "rsrp":      [],
                        "hard_gap":  0,
                        "easy_gap":  0,
                        "regime_noise_limited":          0,
                        "regime_interference_limited":   0,
                        "regime_environment_attenuated": 0,
                        "regime_mixed":                  0,
                    }
                bdata[n]["pixels"] += 1
                bdata[n]["rsrp"].append(bu["rsrp"])

                if gap > RSRP_GAP_HARD:
                    bdata[n]["hard_gap"] += 1
                elif gap < RSRP_GAP_PARTIAL:
                    bdata[n]["easy_gap"] += 1

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

        curr_frac   = sum(1 for p in pixels
                          if _usid_from_id(p["info"]["dominant"]["ID"]) == name) / total
        absorb_frac = absorb / total
        cap         = capacity_summary.get(name, {})
        cap_score   = cap.get("capacity_score", 1.0)

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
            norm_cap    = cap_score / 10.0 if cap_score > 0 else 0.1
            load_factor = round((curr_frac + absorb_frac) / norm_cap, 3)
            load_mode   = "spatial_proxy"
            if   load_factor > 0.8: risk = "high"
            elif load_factor > 0.5: risk = "medium"
            else:                   risk = "low"

        nl  = d.get("regime_noise_limited", 0)
        il  = d.get("regime_interference_limited", 0)
        ea  = d.get("regime_environment_attenuated", 0)
        mx  = d.get("regime_mixed", 0)
        severe_px = nl + ea
        mild_px   = il

        if   severe_px / absorb > 0.6: regime_note = "mostly_severe"
        elif mild_px   / absorb > 0.6: regime_note = "mostly_mild"
        else:                           regime_note = "mixed"

        hard_frac = round(d["hard_gap"] / max(absorb, 1), 4)
        easy_frac = round(d["easy_gap"] / max(absorb, 1), 4)

        per_backup[name] = {
            "absorption_pixel_count":                 absorb,
            "absorption_fraction_of_target":          round(absorb / n_target, 4),
            "absorption_fraction_of_total":           round(absorb_frac, 4),
            "rsrp_in_zone_mean_dbm":                  round(sum(vals) / n_vals, 2),
            "rsrp_in_zone_p50_dbm":                   _percentile(vals, 0.50),
            "rsrp_in_zone_p10_dbm":                   _percentile(vals, 0.10),
            "rsrp_pct_above_good_in_zone":            pct_good,
            "handover_quality":                       hq,
            "current_dominant_fraction":              round(curr_frac, 4),
            "capacity_score":                         cap_score,
            "post_outage_load_factor":                load_factor,
            "overload_risk":                          risk,
            "load_mode":                              load_mode,
            "sinr_regime_impact_note":                regime_note,
            "regime_noise_limited_fraction":          round(nl  / absorb, 4),
            "regime_interference_limited_fraction":   round(il  / absorb, 4),
            "regime_environment_attenuated_fraction": round(ea  / absorb, 4),
            "regime_mixed_fraction":                  round(mx  / absorb, 4),
            "hard_gap_fraction_absorbed":             hard_frac,
            "easy_gap_fraction_absorbed":             easy_frac,
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
# 5. IMAGE GENERATION (raw)
# ─────────────────────────────────────────────────────────────────────────────

def _gen_rsrp_raw(pixels, usid_name, target_usid,
                  grid_rows, grid_cols, lat_range, lon_range, output_dir):
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
            if _usid_from_id(info["dominant"]["ID"]) == usid_name:
                rsrp_grid[r, c] = info["dominant"]["rsrp"]
                dom_mask[r, c]  = True
            elif info.get("backup1") and _usid_from_id(info["backup1"]["ID"]) == usid_name:
                rsrp_grid[r, c] = info["backup1"]["rsrp"]
            elif info.get("backup2") and _usid_from_id(info["backup2"]["ID"]) == usid_name:
                rsrp_grid[r, c] = info["backup2"]["rsrp"]
            if _usid_from_id(info["dominant"]["ID"]) == target_usid:
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

    tower_pos = {}
    for p in pixels:
        dom = p["info"]["dominant"]
        parent = _usid_from_id(dom["ID"])
        if parent not in tower_pos:
            tower_pos[parent] = (dom["lat"], dom["lon"])
        for slot in ["backup1","backup2"]:
            bu = p["info"].get(slot)
            if bu:
                bp = _usid_from_id(bu["ID"])
                if bp not in tower_pos:
                    tower_pos[bp] = (bu["lat"], bu["lon"])

    return lons, lats, ext, color_map, dom_grid, rgb_grid, tower_pos


def _gen_dominance_raw(pixels, all_usid_names, target_usid,
                       grid_rows, grid_cols, lat_range, lon_range,
                       output_dir, n_tiles=1):
    lons, lats, ext, color_map, dom_grid, rgb_grid, tower_pos = \
        _build_dom_grids(pixels, all_usid_names, grid_rows, grid_cols,
                         lat_range, lon_range)

    tgt_mask = np.vectorize(_usid_from_id)(dom_grid) == target_usid
    tgt_mask = tgt_mask.astype(float)
    paths    = []

    fig, ax = plt.subplots(figsize=(9, 8))
    ax.imshow(rgb_grid, origin="lower", extent=ext, aspect="auto", alpha=0.85)

    if tgt_mask.any():
        ax.contour(lons, lats, tgt_mask,
                   levels=[0.5], colors=["black"], linewidths=[3.0])

    fontsize = max(4, min(7, 60 // len(all_usid_names)))
    plotted_overview = set()
    for name in all_usid_names:
        parent = _usid_from_id(name)
        if parent not in tower_pos or parent in plotted_overview:
            continue
        plotted_overview.add(parent)
        t_lat, t_lon = tower_pos[parent]
        is_target = (parent == target_usid)
        color  = "red"   if is_target else "black"
        size   = 80 if is_target else 35
        ax.scatter(t_lon, t_lat, marker="^", s=size,
                   c=color, zorder=5, linewidths=0.5,
                   edgecolors="white")
        short = parent.split("_")[-1] if "_" in parent else parent
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

    tgt_rows, tgt_cols = np.where(np.vectorize(_usid_from_id)(dom_grid) == target_usid)
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

    zoom_usids = sorted(set(z_dom.flatten()))

    def _hex_rgb(h):
        return [int(h[i:i+2], 16)/255 for i in (1, 3, 5)]

    grey  = [0.88, 0.88, 0.88]
    neighbor_set = set(zoom_usids)
    z_rgb = np.array([[_hex_rgb(color_map[z_dom[r,c]])
                       if z_dom[r,c] in neighbor_set else grey
                       for c in range(z_dom.shape[1])]
                      for r in range(z_dom.shape[0])])

    fig, ax = plt.subplots(figsize=(8, 7))
    ax.imshow(z_rgb, origin="lower", extent=z_ext, aspect="auto", alpha=0.85)

    if z_tgt.any():
        ax.contour(z_lons, z_lats, z_tgt,
                   levels=[0.5], colors=["black"], linewidths=[3.0])

    plotted_zoom = set()
    for name in zoom_usids:
        parent = _usid_from_id(name)
        if parent not in tower_pos or parent in plotted_zoom:
            continue
        t_lat, t_lon = tower_pos[parent]
        if not (z_lats[0] <= t_lat <= z_lats[-1] and
                z_lons[0] <= t_lon <= z_lons[-1]):
            continue
        plotted_zoom.add(parent)
        is_target = (parent == target_usid)
        color  = "red" if is_target else "black"
        size   = 100  if is_target else 50
        ax.scatter(t_lon, t_lat, marker="^", s=size, c=color,
                   zorder=5, linewidths=0.5, edgecolors="white")
        short = parent.split("_")[-1] if "_" in parent else parent
        ax.annotate(short,
                    xy=(t_lon, t_lat),
                    xytext=(3, 4), textcoords="offset points",
                    fontsize=8, color=color,
                    fontweight="bold" if is_target else "normal",
                    zorder=6)

    legend_handles = [
        mpatches.Patch(color=color_map[n],
                       label=n + (" ← TARGET" if _usid_from_id(n) == target_usid else ""))
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


def _gen_sinr_raw(pixels, target_usid, grid_rows, grid_cols,
                  lat_range, lon_range, output_dir):
    lat_min, lat_max = lat_range
    lon_min, lon_max = lon_range
    ext  = [lon_min, lon_max, lat_min, lat_max]
    lons = np.linspace(lon_min, lon_max, grid_cols)
    lats = np.linspace(lat_min, lat_max, grid_rows)

    sinr_grid = np.array([[pixels[r*grid_cols+c]["info"]["sinr_db"]
                           for c in range(grid_cols)] for r in range(grid_rows)],
                         dtype=np.float32)
    tgt_mask  = np.array([[_usid_from_id(pixels[r*grid_cols+c]["info"]["dominant"]["ID"]) == target_usid
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


def _gen_throughput_raw(pixels, target_usid, grid_rows, grid_cols,
                        lat_range, lon_range, output_dir):
    lat_min, lat_max = lat_range
    lon_min, lon_max = lon_range
    ext  = [lon_min, lon_max, lat_min, lat_max]
    lons = np.linspace(lon_min, lon_max, grid_cols)
    lats = np.linspace(lat_min, lat_max, grid_rows)

    tp_grid  = np.array([[pixels[r*grid_cols+c]["info"]["throughput_mbps"]
                          for c in range(grid_cols)] for r in range(grid_rows)],
                        dtype=np.float32)
    tgt_mask = np.array([[_usid_from_id(pixels[r*grid_cols+c]["info"]["dominant"]["ID"]) == target_usid
                          for c in range(grid_cols)] for r in range(grid_rows)],
                        dtype=float)

    cmap = LinearSegmentedColormap.from_list(
        "tp", ["#8B0000","#FF4500","#FFA500","#FFD700","#ADFF2F","#00FF00"])

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(tp_grid, origin="upper", cmap=cmap, vmin=0, vmax=100,
                   extent=ext, aspect="auto")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("Throughput (Mbps)", fontsize=9)
    for thresh, lbl in [(TP_HIGH, "High"), (TP_MEDIUM, "Med.")]:
        norm = thresh / 100
        cb.ax.axhline(norm, color="white", lw=1, ls="--")
        cb.ax.text(1.3, norm, lbl, va="center", fontsize=6,
                   transform=cb.ax.transAxes)

    if tgt_mask.any():
        ax.contour(lons, lats, tgt_mask, levels=[0.5],
                   colors=["red"], linewidths=[2])

    ax.set_title(
        f"Throughput Map  (red = {target_usid} dominant area)\n"
        f"Low throughput inside → direct user experience impact",
        fontsize=9, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")

    path = Path(output_dir) / "throughput_map.png"
    _save_fig(fig, path)
    return path


def _gen_rsrq_raw(pixels, target_usid, grid_rows, grid_cols,
                  lat_range, lon_range, output_dir):
    lat_min, lat_max = lat_range
    lon_min, lon_max = lon_range
    ext  = [lon_min, lon_max, lat_min, lat_max]
    lons = np.linspace(lon_min, lon_max, grid_cols)
    lats = np.linspace(lat_min, lat_max, grid_rows)

    rsrq_grid = np.array([[pixels[r*grid_cols+c]["info"]["rsrq_db"]
                           for c in range(grid_cols)] for r in range(grid_rows)],
                         dtype=np.float32)
    tgt_mask  = np.array([[_usid_from_id(pixels[r*grid_cols+c]["info"]["dominant"]["ID"]) == target_usid
                           for c in range(grid_cols)] for r in range(grid_rows)],
                         dtype=float)

    cmap = LinearSegmentedColormap.from_list(
        "rsrq", ["#4B0082","#0000FF","#00BFFF","#00FF00","#FFD700","#FF4500"])

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(rsrq_grid, origin="upper", cmap=cmap, vmin=-20, vmax=-5,
                   extent=ext, aspect="auto")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("RSRQ (dB)", fontsize=9)
    for thresh, lbl in [(RSRQ_EXCELLENT,"Exc."),(RSRQ_GOOD,"Good"),
                        (RSRQ_MODERATE,"Mod.")]:
        norm = (thresh - (-20)) / (-5 - (-20))
        cb.ax.axhline(norm, color="white", lw=1, ls="--")
        cb.ax.text(1.3, norm, lbl, va="center", fontsize=6,
                   transform=cb.ax.transAxes)

    if tgt_mask.any():
        ax.contour(lons, lats, tgt_mask, levels=[0.5],
                   colors=["red"], linewidths=[2])

    ax.set_title(
        f"RSRQ Map  (red = {target_usid} dominant area)\n"
        f"Poor RSRQ = interference present  |  "
        f"Compare with SINR to distinguish interference vs attenuation",
        fontsize=9, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")

    path = Path(output_dir) / "rsrq_map.png"
    _save_fig(fig, path)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# SHARED FILE-LOADING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _load_pixels(coverage_json_path: str) -> list:
    with open(coverage_json_path) as f:
        cov = json.load(f)
    return cov["pixels"] if isinstance(cov, dict) else cov

def _get_grid_params(pixels: list) -> tuple:
    all_lats = sorted(set(round(p["lat"], 6) for p in pixels))
    all_lons = sorted(set(round(p["lon"], 6) for p in pixels))
    return (
        len(all_lats), len(all_lons),
        (all_lats[0], all_lats[-1]),
        (all_lons[0], all_lons[-1]),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC WRAPPERS
# ─────────────────────────────────────────────────────────────────────────────

def compute_coverage_summary(coverage_json_path: str) -> dict:
    """Per-sector and per-USID RSRP statistics plus area-level SINR, throughput, and RSRQ distributions across all pixels. Cached after first call."""
    def _compute():
        return _compute_coverage_summary_raw(_load_pixels(coverage_json_path))
    return get_cached("coverage_summary", coverage_json_path, _compute)

def compute_capacity_summary(attr_csv_path: str) -> dict:
    """Capacity score for every USID from site attributes CSV. Formula: (4G_cells x 1.0 + 5G_cells x 2.0) x (1 + 0.15 x active_bands). Used as input to compute_load_redistribution. Cached after first call."""
    def _compute():
        return _compute_capacity_summary_raw(pd.read_csv(attr_csv_path))
    return get_cached("capacity_summary", "all", _compute)

def identify_neighbors(coverage_json_path: str,
                       target_usid: str,
                       threshold: float = 0.05) -> list:
    """Rank all USIDs by backup overlap fraction with the target USID. Returns list sorted by overlap fraction descending. Cached by target_usid after first call."""
    def _compute():
        return _identify_neighbors_raw(
            _load_pixels(coverage_json_path), target_usid, threshold)
    return get_cached("neighbors", target_usid, _compute)

def compute_load_redistribution(coverage_json_path: str,
                                target_usid: str,
                                attr_csv_path: str) -> dict:
    """When target_usid goes down, compute absorption capacity and overload risk for each backup USID. Internally calls compute_capacity_summary — no need to pass it separately. Cached by target_usid after first call."""
    def _compute():
        cap = compute_capacity_summary(attr_csv_path)
        return _compute_load_redistribution_raw(
            _load_pixels(coverage_json_path), target_usid, cap)
    return get_cached("load_redistribution", target_usid, _compute)

def generate_rsrp_image(coverage_json_path: str,
                        usid: str, output_dir: str) -> dict:
    """RSRP heatmap PNG for a given USID. Returns image_path and cached flag. Skips generation if file already exists."""
    path = Path(output_dir) / f"rsrp_{usid}.png"
    if path.exists():
        return {"image_path": str(path), "cached": True}
    def _compute():
        pixels = _load_pixels(coverage_json_path)
        gr, gc, lr, lonr = _get_grid_params(pixels)
        _gen_rsrp_raw(pixels, usid, usid, gr, gc, lr, lonr, output_dir)
        return {"image_path": str(path), "cached": False}
    return get_cached("rsrp_image", usid, _compute)

def generate_sinr_map(coverage_json_path: str,
                      target_usid: str, output_dir: str) -> dict:
    """SINR heatmap PNG with target USID dominant area boundary. Returns image_path and cached flag. Skips generation if file already exists."""
    path = Path(output_dir) / "sinr_map.png"
    if path.exists():
        return {"image_path": str(path), "cached": True}
    def _compute():
        pixels = _load_pixels(coverage_json_path)
        gr, gc, lr, lonr = _get_grid_params(pixels)
        _gen_sinr_raw(pixels, target_usid, gr, gc, lr, lonr, output_dir)
        return {"image_path": str(path), "cached": False}
    return get_cached("sinr_map", target_usid, _compute)

def generate_throughput_map(coverage_json_path: str,
                            target_usid: str, output_dir: str) -> dict:
    """Throughput heatmap PNG with target USID dominant area boundary. Returns image_path and cached flag. Skips generation if file already exists."""
    path = Path(output_dir) / "throughput_map.png"
    if path.exists():
        return {"image_path": str(path), "cached": True}
    def _compute():
        pixels = _load_pixels(coverage_json_path)
        gr, gc, lr, lonr = _get_grid_params(pixels)
        _gen_throughput_raw(pixels, target_usid, gr, gc, lr, lonr, output_dir)
        return {"image_path": str(path), "cached": False}
    return get_cached("throughput_map", target_usid, _compute)

def generate_rsrq_map(coverage_json_path: str,
                      target_usid: str, output_dir: str) -> dict:
    """RSRQ heatmap PNG with target USID dominant area boundary. Returns image_path and cached flag. Skips generation if file already exists."""
    path = Path(output_dir) / "rsrq_map.png"
    if path.exists():
        return {"image_path": str(path), "cached": True}
    def _compute():
        pixels = _load_pixels(coverage_json_path)
        gr, gc, lr, lonr = _get_grid_params(pixels)
        _gen_rsrq_raw(pixels, target_usid, gr, gc, lr, lonr, output_dir)
        return {"image_path": str(path), "cached": False}
    return get_cached("rsrq_map", target_usid, _compute)

def generate_dominance_map(coverage_json_path: str,
                           target_usid: str, output_dir: str) -> dict:
    """Dominance map PNGs: full network overview and neighborhood zoom. Returns overview_path, neighborhood_path, and cached flag. Skips generation if both files already exist."""
    p1 = Path(output_dir) / "dominance_map_overview.png"
    p2 = Path(output_dir) / "dominance_map_neighborhood.png"
    if p1.exists() and p2.exists():
        return {"overview_path": str(p1),
                "neighborhood_path": str(p2), "cached": True}
    def _compute():
        pixels = _load_pixels(coverage_json_path)
        gr, gc, lr, lonr = _get_grid_params(pixels)
        all_usid_names = list(set(
            p["info"]["dominant"]["ID"] for p in pixels))
        _gen_dominance_raw(pixels, all_usid_names, target_usid,
                           gr, gc, lr, lonr, output_dir)
        return {"overview_path": str(p1),
                "neighborhood_path": str(p2), "cached": False}
    return get_cached("dominance_map", target_usid, _compute)
