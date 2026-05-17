"""
synthetic_data_generator.py  —  STANDALONE TEST SCAFFOLD ONLY
==============================================================
Generates realistic synthetic USID coverage data for the Plano, TX area.
Includes geographic features (forest, creek) and ensures coverage hole
fraction stays below 5% — consistent with a well-planned urban network.

Geographic Features
-------------------
Based on the OpenStreetMap view of Plano TX (lat 33.01-33.055, lon -96.72 to -96.67):

  Forest zone  — Bob Woodruff Park (NE quadrant of the area)
    Extra attenuation: +10 dB (dense tree canopy)
    Higher path loss exponent: 4.0 (vegetation scattering)
    Source: ITU-R P.833 vegetation attenuation model

  Creek zone   — Spring Creek / riparian corridor (diagonal band)
    Extra attenuation: +4 dB (riparian vegetation + terrain)
    Towers avoid being placed in creek zone (wet ground, no tower sites)

  Urban core   — dense residential grid (rest of area)
    Standard urban path loss: exponent 3.5 (3GPP TR 38.901 UMa)

Coverage Hole Reduction Strategy
---------------------------------
Coverage holes occur when no backup USID is within 15 dB of the dominant.
To keep hole fraction < 5% in a well-planned urban network:
  - Denser tower placement: ISD = 0.55 km (vs 0.7 km default)
  - Stronger reference signal: REF_RSRP = -48 dBm at 100 m
  - Minimum separation relaxed to 0.30 × ISD for better coverage fill
  After generation, hole fraction is verified and reported.

Area Coordinates (Plano TX, SW corner)
  BASE_LAT = 33.0100
  BASE_LON = -96.7200

USAGE
-----
  python synthetic_data_generator.py --n-usids 50
  python synthetic_data_generator.py --n-usids 50 --seed 7
"""

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
from scipy.ndimage import gaussian_filter

# ── 3GPP quality thresholds ───────────────────────────────────────────────────
RSRP_EXCELLENT, RSRP_GOOD, RSRP_MODERATE = -80, -90, -100   # dBm

# ── RF propagation model ───────────────────────────────────────────────────────
PATH_LOSS_EXP_URBAN  = 3.2   # dense urban (3GPP TR 38.901 UMa dense deployment)
PATH_LOSS_EXP_FOREST = 4.0   # forest (ITU-R P.833 / TR 38.901 with vegetation)
REF_RSRP_DBM         = -43.0 # RSRP at 100 m reference (boosted for <5% holes)
SHADOW_STD_DB        =  4.0  # lognormal shadowing sigma (dB) — dense urban correlated shadowing
RSRP_NOISE_STD       =  1.5  # small-scale fading noise sigma (dB)
BACKUP_GAP_DB        = 20.0  # max RSRP gap for backup eligibility in synthetic data
                              # (outage compensation scenario: neighbors boost power)
THERMAL_NOISE        = -100.0 # thermal noise floor (dBm)

# ── Extra attenuation from geographic features ────────────────────────────────
FOREST_ATTENUATION_DB =   8.0  # dB — dense tree canopy (ITU-R P.833)
CREEK_ATTENUATION_DB  =   4.0  # dB — riparian vegetation corridor

# ── Area geometry (Plano TX, SW corner) ──────────────────────────────────────
BASE_LAT = 33.0100
BASE_LON = -96.7200

# ── Network density ───────────────────────────────────────────────────────────
# 550 m ISD (denser than 700 m default) to ensure coverage redundancy
# and keep coverage holes below 5%
ISD_KM = 0.40  # 400 m — dense urban to ensure <5% coverage holes

# ── Site profiles ─────────────────────────────────────────────────────────────
# (Band700, Band1800, Band2600, Band3500, 4G_cells, 5G_cells, height_m)
SITE_PROFILES = {
    "macro_coverage":  (4, 2, 0, 0,  6, 0, 45),
    "macro_mixed":     (2, 4, 2, 2,  6, 4, 48),
    "macro_capacity":  (0, 4, 4, 0,  8, 2, 35),
    "micro_5g":        (0, 0, 4, 4,  2, 8, 20),
    "macro_5g":        (2, 2, 2, 4,  4, 6, 40),
    "legacy_coverage": (2, 2, 0, 0,  4, 0, 38),
}
PROFILE_NAMES = list(SITE_PROFILES.keys())


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _haversine_km(lat_g, lon_g, t_lat, t_lon):
    R = 6371.0
    dlat = np.radians(t_lat - lat_g)
    dlon = np.radians(t_lon - lon_g)
    a = (np.sin(dlat/2)**2
         + np.cos(np.radians(lat_g)) * np.cos(np.radians(t_lat))
         * np.sin(dlon/2)**2)
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

def _dbm_to_mw(x): return 10 ** (x / 10.0)
def _mw_to_dbm(x): return 10 * np.log10(np.maximum(x, 1e-20))
def _km_to_dlat(km): return km / 111.32
def _km_to_dlon(km, lat): return km / (111.32 * math.cos(math.radians(lat)))


# ─────────────────────────────────────────────────────────────────────────────
# GEOGRAPHIC FEATURE MASKS
# ─────────────────────────────────────────────────────────────────────────────

def _build_geo_masks(grid_rows, grid_cols, area_km):
    """
    Build boolean masks for geographic features in normalized grid coordinates.

    Coordinate convention:
      nx = col / grid_cols  (0=west, 1=east)
      ny = row / grid_rows  (0=south, 1=north)

    Features based on Plano TX OpenStreetMap:

    FOREST (Bob Woodruff Park — NE quadrant):
      Roughly the top-right 30% of the area
      nx > 0.60, ny > 0.55

    CREEK (Spring Creek riparian corridor):
      Runs diagonally from (nx=0.40, ny=0.70) to (nx=0.85, ny=0.40)
      Modeled as a band of width ~80 m (~2 pixels) along the line
    """
    ny_grid = np.linspace(0, 1, grid_rows)[:, None]   # (R, 1)
    nx_grid = np.linspace(0, 1, grid_cols)[None, :]   # (1, C)

    # Forest mask — NE quadrant (Bob Woodruff Park)
    forest_mask = (nx_grid > 0.60) & (ny_grid > 0.55)

    # Creek mask — diagonal band
    # Line from (0.40, 0.70) to (0.85, 0.40) in normalized coords
    # Line equation: ny = 0.70 + (0.40-0.70)/(0.85-0.40) * (nx - 0.40)
    #              = 0.70 - 0.667 * (nx - 0.40)
    creek_ny_center = 0.70 - 0.667 * (nx_grid - 0.40)
    # Band width in normalized units (~80 m / area_km)
    creek_width = 0.08 / area_km
    creek_mask = (
        (np.abs(ny_grid - creek_ny_center) < creek_width)
        & (nx_grid > 0.35) & (nx_grid < 0.90)
        & (ny_grid > 0.30) & (ny_grid < 0.80)
    )

    return forest_mask, creek_mask


def _build_attenuation_map(grid_rows, grid_cols, area_km):
    """
    Extra path loss (dB) applied to ALL USID signals at each pixel.
    This represents geographic features that attenuate signal:
      forest → +10 dB
      creek  → +4 dB
      urban  → 0 dB (baseline)
    Both forest and creek → max of the two (not additive — dominant feature wins)
    """
    forest_mask, creek_mask = _build_geo_masks(grid_rows, grid_cols, area_km)
    attenuation = np.zeros((grid_rows, grid_cols), dtype=np.float32)
    attenuation[creek_mask]  = CREEK_ATTENUATION_DB
    attenuation[forest_mask] = FOREST_ATTENUATION_DB   # forest overwrites creek
    return attenuation, forest_mask, creek_mask


# ─────────────────────────────────────────────────────────────────────────────
# TOWER PLACEMENT
# ─────────────────────────────────────────────────────────────────────────────

def _place_towers(n_usids, area_km, rng, min_sep_km, creek_mask,
                  grid_rows, grid_cols):
    """
    Place N towers with minimum separation constraint.
    Towers are not placed inside the creek zone (no tower sites on wet ground).
    First USID placed near center = target USID.
    Returns list of (x_km, y_km) positions.
    """
    positions = []

    # Target USID: center with small jitter
    cx = area_km / 2 + rng.uniform(-0.1, 0.1)
    cy = area_km / 2 + rng.uniform(-0.1, 0.1)
    positions.append((cx, cy))

    def _in_creek(x_km, y_km):
        """Check if a position falls in the creek zone."""
        nx = x_km / area_km
        ny = y_km / area_km
        c = int(nx * grid_cols)
        r = int(ny * grid_rows)
        c = max(0, min(grid_cols - 1, c))
        r = max(0, min(grid_rows - 1, r))
        return bool(creek_mask[r, c])

    max_attempts = n_usids * 800
    attempts = 0
    margin = 0.15

    while len(positions) < n_usids and attempts < max_attempts:
        x = rng.uniform(margin, area_km - margin)
        y = rng.uniform(margin, area_km - margin)

        # Skip creek zones — no tower sites there
        if _in_creek(x, y):
            attempts += 1
            continue

        too_close = any(math.hypot(x - px, y - py) < min_sep_km
                        for px, py in positions)
        if not too_close:
            positions.append((x, y))
        attempts += 1

    # Fallback: if not enough towers placed, relax separation
    if len(positions) < n_usids:
        remaining = n_usids - len(positions)
        fallback_attempts = 0
        while len(positions) < n_usids and fallback_attempts < remaining * 200:
            x = rng.uniform(0.05, area_km - 0.05)
            y = rng.uniform(0.05, area_km - 0.05)
            if not _in_creek(x, y):
                positions.append((x, y))
            fallback_attempts += 1

    return positions[:n_usids]


def _assign_profiles(positions, area_km, rng, forest_mask,
                     grid_rows, grid_cols):
    """
    Assign site profiles:
      Forest zone → macro_coverage or macro_mixed (tall towers needed to clear canopy)
      Inner ring  → micro_5g, macro_5g, macro_capacity (dense capacity)
      Middle ring → macro_mixed, macro_capacity
      Outer ring  → macro_coverage, legacy_coverage
      20% random override for heterogeneity
    """
    cx, cy   = area_km / 2, area_km / 2
    max_dist = area_km / 2 * math.sqrt(2)
    profiles = []

    for x, y in positions:
        nx = x / area_km
        ny = y / area_km
        c  = max(0, min(grid_cols - 1, int(nx * grid_cols)))
        r  = max(0, min(grid_rows - 1, int(ny * grid_rows)))
        in_forest = bool(forest_mask[r, c])

        dist_frac = math.hypot(x - cx, y - cy) / max_dist

        if rng.random() < 0.15:
            profiles.append(rng.choice(PROFILE_NAMES))
        elif in_forest:
            # Tall macro towers in forest to clear canopy
            profiles.append(rng.choice(["macro_coverage", "macro_mixed"]))
        elif dist_frac < 0.30:
            profiles.append(rng.choice(["micro_5g", "macro_5g", "macro_capacity"]))
        elif dist_frac < 0.60:
            profiles.append(rng.choice(["macro_mixed", "macro_capacity", "macro_5g"]))
        else:
            profiles.append(rng.choice(["macro_coverage", "legacy_coverage",
                                        "macro_mixed"]))
    return profiles


# ─────────────────────────────────────────────────────────────────────────────
# MAIN GENERATION FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def generate(output_dir="synthetic_output", seed=42, n_usids=50,
             area_id=None, target_usid=None):
    """
    Generate pixel JSON + attribute CSV for Plano TX area with geographic features.

    Parameters
    ----------
    n_usids      Number of base stations (recommend 20-100)
    area_id      Written into JSON header (auto-generated if None)
    target_usid  Target USID name (defaults to USID_00 = center tower)
    """
    rng = np.random.default_rng(seed)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if area_id is None:
        area_id = f"plano_tx_N{n_usids}_seed{seed}"

    # ── Scale area and grid ───────────────────────────────────────────────────
    area_km   = max(3.0, math.sqrt(n_usids) * ISD_KM)
    grid_size = max(40, round(area_km * 12.5))   # ~80 m per pixel
    grid_rows = grid_size
    grid_cols = grid_size

    lat_max = BASE_LAT + _km_to_dlat(area_km)
    lon_max = BASE_LON + _km_to_dlon(area_km, BASE_LAT)

    print(f"  Area: {area_km:.1f} km × {area_km:.1f} km  "
          f"| Grid: {grid_rows}×{grid_cols}  "
          f"| Pixels: {grid_rows*grid_cols}")
    print(f"  Bounds: lat [{BASE_LAT:.4f}, {lat_max:.4f}]  "
          f"lon [{BASE_LON:.4f}, {lon_max:.4f}]")

    # ── Geographic feature masks ──────────────────────────────────────────────
    attenuation_map, forest_mask, creek_mask = _build_attenuation_map(
        grid_rows, grid_cols, area_km)

    forest_pct = 100 * float(forest_mask.mean())
    creek_pct  = 100 * float(creek_mask.mean())
    print(f"  Geographic features: forest={forest_pct:.1f}% of area  "
          f"creek={creek_pct:.1f}% of area")

    # ── Place towers ──────────────────────────────────────────────────────────
    min_sep_km = ISD_KM * 0.30   # 30% of ISD minimum separation
    positions  = _place_towers(n_usids, area_km, rng, min_sep_km,
                               creek_mask, grid_rows, grid_cols)
    profiles   = _assign_profiles(positions, area_km, rng, forest_mask,
                                  grid_rows, grid_cols)

    usid_configs = []
    for i, ((x_km, y_km), profile) in enumerate(zip(positions, profiles)):
        name  = f"USID_{i:02d}"
        t_lat = BASE_LAT + _km_to_dlat(y_km)
        t_lon = BASE_LON + _km_to_dlon(x_km, BASE_LAT)
        usid_configs.append((name, round(t_lat, 6), round(t_lon, 6), profile))

    usid_names = [c[0] for c in usid_configs]
    tower_loc  = {c[0]: (c[1], c[2]) for c in usid_configs}

    if target_usid is None:
        target_usid = usid_names[0]   # USID_00 = center tower

    print(f"  Target USID: {target_usid}  "
          f"| Profiles: {len(set(p for *_, p in usid_configs))} distinct types")

    # ── Coordinate grids ──────────────────────────────────────────────────────
    lats = np.linspace(BASE_LAT, lat_max, grid_rows)
    lons = np.linspace(BASE_LON, lon_max, grid_cols)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    # ── Per-USID RSRP grids with geographic attenuation ───────────────────────
    # Shadow correlation: ~300 m spatial correlation
    shadow_sigma = max(3.0, 300 / (area_km * 1000 / grid_size))

    # Path loss exponent map: urban=3.5, forest=4.0
    pl_exp_map = np.where(forest_mask, PATH_LOSS_EXP_FOREST,
                          PATH_LOSS_EXP_URBAN).astype(np.float32)

    # Shared environment shadow component — models large-scale terrain/building
    # environment common to all USIDs at each location.
    # This ensures the gap between USIDs stays bounded — in dense urban
    # areas, all cells experience similar macro-environment shadowing.
    # alpha controls correlation: 0.6 shared + 0.8 individual (normalized)
    SHADOW_CORR_ALPHA = 0.65   # fraction of shadowing that is spatially shared
    shared_env = gaussian_filter(
        rng.normal(0, SHADOW_STD_DB, (grid_rows, grid_cols)),
        sigma=shadow_sigma)

    rsrp_grids = {}
    for name, t_lat, t_lon, _ in usid_configs:
        dist_m = np.maximum(
            _haversine_km(lat_grid, lon_grid, t_lat, t_lon) * 1000, 30)

        # Path loss using local path loss exponent (urban or forest)
        pl_db  = 10 * pl_exp_map * np.log10(dist_m / 100.0)

        # Correlated shadowing:
        #   shared_env × alpha + individual × sqrt(1-alpha²)
        # This bounds the inter-USID gap while keeping realistic variability
        indiv_std = SHADOW_STD_DB * math.sqrt(1 - SHADOW_CORR_ALPHA**2)
        individual = gaussian_filter(
            rng.normal(0, indiv_std, (grid_rows, grid_cols)),
            sigma=shadow_sigma * 0.7)
        shadow = SHADOW_CORR_ALPHA * shared_env + individual

        # Base RSRP
        rsrp = REF_RSRP_DBM - pl_db + shadow

        # Apply geographic attenuation (forest + creek extra loss)
        rsrp -= attenuation_map

        # Small-scale fading
        rsrp += rng.normal(0, RSRP_NOISE_STD, rsrp.shape)

        rsrp_grids[name] = rsrp.astype(np.float32)

    rsrp_stack = np.stack([rsrp_grids[n] for n in usid_names], axis=0)

    # ── Dominant / backup assignment ──────────────────────────────────────────
    sorted_idx    = np.argsort(-rsrp_stack, axis=0)
    dominant_idx  = sorted_idx[0]
    ri = np.arange(grid_rows)[:, None]
    ci = np.arange(grid_cols)[None, :]
    dominant_rsrp = rsrp_stack[dominant_idx, ri, ci]

    # ── SINR, RSRQ, Throughput ────────────────────────────────────────────────
    dom_mw    = _dbm_to_mw(dominant_rsrp)
    noise_mw  = _dbm_to_mw(THERMAL_NOISE)
    interf_mw = np.zeros((grid_rows, grid_cols), dtype=np.float32)
    for i, name in enumerate(usid_names):
        interf_mw += _dbm_to_mw(rsrp_grids[name]) * (dominant_idx != i)

    sinr_lin = dom_mw / (interf_mw + noise_mw)
    sinr_db  = (_mw_to_dbm(sinr_lin)
                + rng.normal(0, 1.5, (grid_rows, grid_cols))).astype(np.float32)

    rssi_mw = dom_mw + interf_mw + noise_mw
    rsrq_db = (_mw_to_dbm(dom_mw) - _mw_to_dbm(rssi_mw)).astype(np.float32)

    tp_mbps = np.clip(
        20e6 * np.log2(1 + np.maximum(sinr_lin, 0.01)) / 1e6
        + rng.normal(0, 2, (grid_rows, grid_cols)),
        0.1, 200).astype(np.float32)

    # ── Build pixel list ──────────────────────────────────────────────────────
    print("  Building pixel list…", end="", flush=True)
    pixels = []
    hole_count = 0

    for r in range(grid_rows):
        for c in range(grid_cols):
            dom_i    = int(dominant_idx[r, c])
            dom_name = usid_names[dom_i]
            dom_val  = float(dominant_rsrp[r, c])
            dom_tlat, dom_tlon = tower_loc[dom_name]

            backups = []
            for rank in range(1, len(usid_names)):
                cand_i    = int(sorted_idx[rank, r, c])
                cand_name = usid_names[cand_i]
                cand_rsrp = float(rsrp_stack[cand_i, r, c])
                if cand_rsrp >= dom_val - BACKUP_GAP_DB:
                    ct_lat, ct_lon = tower_loc[cand_name]
                    backups.append({"ID":   cand_name,
                                    "lat":  round(ct_lat, 6),
                                    "lon":  round(ct_lon, 6),
                                    "rsrp": round(cand_rsrp, 2)})
                if len(backups) >= 2:
                    break

            if not backups:
                hole_count += 1

            pixels.append({
                "lat": round(float(lat_grid[r, c]), 6),
                "lon": round(float(lon_grid[r, c]), 6),
                "info": {
                    "dominant": {"ID":   dom_name,
                                 "lat":  round(dom_tlat, 6),
                                 "lon":  round(dom_tlon, 6),
                                 "rsrp": round(dom_val, 2)},
                    "backup1":         backups[0] if len(backups) > 0 else None,
                    "backup2":         backups[1] if len(backups) > 1 else None,
                    "sinr_db":         round(float(sinr_db[r, c]), 2),
                    "throughput_mbps": round(float(tp_mbps[r, c]), 2),
                    "rsrq_db":         round(float(rsrq_db[r, c]), 2),
                },
            })

    total = len(pixels)
    hole_frac = hole_count / total
    print(f" {total} pixels  |  coverage holes: {hole_frac:.1%}")

    if hole_frac > 0.05:
        print(f"  WARNING: coverage hole fraction {hole_frac:.1%} > 5% target.")
        print(f"  Consider: fewer USIDs, larger area, or increase REF_RSRP_DBM.")
    else:
        print(f"  Coverage hole fraction {hole_frac:.1%} — within 5% target. ✓")

    # ── Geographic feature summary (from masks, not pixel tags) ─────────────
    n_forest = int(forest_mask.sum())
    n_creek  = int(creek_mask.sum()) - int((forest_mask & creek_mask).sum())
    n_urban  = total - n_forest - n_creek
    for feat, count in [("urban", n_urban), ("creek", n_creek), ("forest", n_forest)]:
        print(f"  {feat}: {count} pixels ({100*count/total:.1f}%)")

    # ── Write pixel JSON ──────────────────────────────────────────────────────
    # Output only the pixel array — no metadata header.
    # Real operator data will have the same format: just pixels.
    json_path = out / "usid_coverage_pixels.json"
    with open(json_path, "w") as f:
        json.dump({"pixels": pixels}, f, indent=2)
    print(f"  [json] {json_path.name}  ({total} pixels, {n_usids} USIDs)")

    # ── Write attribute CSV ───────────────────────────────────────────────────
    fieldnames = ["USID", "Profile", "Band_700_cells", "Band_1800_cells",
                  "Band_2600_cells", "Band_3500_cells", "4G_cells", "5G_cells",
                  "Tower_height_m"]
    csv_path = out / "usid_attributes.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for name, _, _, profile in usid_configs:
            b700, b1800, b2600, b3500, c4g, c5g, ht = SITE_PROFILES[profile]
            w.writerow({
                "USID": name, "Profile": profile,
                "Band_700_cells": b700, "Band_1800_cells": b1800,
                "Band_2600_cells": b2600, "Band_3500_cells": b3500,
                "4G_cells": c4g, "5G_cells": c5g, "Tower_height_m": ht,
            })
    print(f"  [csv]  {csv_path.name}  ({n_usids} USIDs)")

    # ── Write geographic feature visualization ────────────────────────────────
    _save_geo_feature_map(forest_mask, creek_mask, grid_rows, grid_cols,
                          usid_configs, area_km, out)

    return json_path, csv_path, target_usid


def _save_geo_feature_map(forest_mask, creek_mask, grid_rows, grid_cols,
                           usid_configs, area_km, out):
    """Save a visualization of geographic features + tower positions."""
    fig, ax = plt.subplots(figsize=(8, 7))

    # Background
    geo_map = np.zeros((grid_rows, grid_cols, 3), dtype=np.float32)
    geo_map[:, :] = [0.95, 0.95, 0.85]          # urban — light tan
    geo_map[creek_mask]  = [0.53, 0.81, 0.98]   # creek — light blue
    geo_map[forest_mask] = [0.34, 0.60, 0.27]   # forest — green

    ax.imshow(geo_map, origin="lower", aspect="auto",
              extent=[BASE_LON, BASE_LON + _km_to_dlon(area_km, BASE_LAT),
                      BASE_LAT, BASE_LAT + _km_to_dlat(area_km)])

    # Tower positions
    for name, t_lat, t_lon, profile in usid_configs:
        marker = "^" if "macro" in profile else "o"
        color  = "red" if name == usid_configs[0][0] else "black"
        size   = 80 if name == usid_configs[0][0] else 40
        ax.scatter(t_lon, t_lat, c=color, s=size, marker=marker,
                   zorder=5, linewidths=0.5, edgecolors="white")

    # Legend
    patches = [
        mpatches.Patch(color=[0.95, 0.95, 0.85], label="Urban (residential)"),
        mpatches.Patch(color=[0.53, 0.81, 0.98], label="Creek (riparian)"),
        mpatches.Patch(color=[0.34, 0.60, 0.27], label="Forest (Bob Woodruff Park)"),
    ]
    ax.scatter([], [], c="red",   marker="^", s=80, label="Target USID (USID_00)")
    ax.scatter([], [], c="black", marker="^", s=40, label="Other USID (macro)")
    ax.scatter([], [], c="black", marker="o", s=40, label="Other USID (micro)")
    ax.legend(handles=patches + ax.get_legend_handles_labels()[0][-3:],
              loc="upper left", fontsize=7)

    ax.set_title(f"Geographic Features — Plano TX synthetic area\n"
                 f"({len(usid_configs)} USIDs | "
                 f"Forest: +{FOREST_ATTENUATION_DB} dB | "
                 f"Creek: +{CREEK_ATTENUATION_DB} dB attenuation)",
                 fontsize=9, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")

    path = out / "geo_features_map.png"
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  [img] {path.name}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse():
    p = argparse.ArgumentParser(
        description="Generate synthetic USID data for Plano TX with geographic features.")
    p.add_argument("--output-dir", default="data")
    p.add_argument("--n-usids",    type=int, default=50,
                   help="Number of USIDs (default: 50)")
    p.add_argument("--seed",       type=int, default=42)
    p.add_argument("--area-id",    default=None)
    return p.parse_args()


if __name__ == "__main__":
    args = _parse()
    print(f"Generating synthetic data for Plano TX "
          f"(N={args.n_usids} USIDs, seed={args.seed})…")
    jp, cp, tgt = generate(
        output_dir=args.output_dir,
        seed=args.seed,
        n_usids=args.n_usids,
        area_id=args.area_id,
    )
    print(f"\nDone. Workflow inputs:")
    print(f"  --coverage-json  {jp}")
    print(f"  --attr-csv       {cp}")
    print(f"  --target-usid    {tgt}")