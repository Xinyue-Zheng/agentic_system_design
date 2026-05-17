"""
synthetic_data_generator_v2.py  —  STANDALONE TEST SCAFFOLD ONLY
=================================================================
Generates realistic synthetic USID coverage data for the Plano, TX area.
Includes geographic features (forest, creek) and ensures coverage hole
fraction stays below 5% — consistent with a well-planned urban network.

Also generates:
  - Sector-level KPI timeseries (kpi_sector_timeseries.csv)
  - Outage ticket data (outage_tickets.json)

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
  python synthetic_data_generator_v2.py --n-usids 50
  python synthetic_data_generator_v2.py --n-usids 50 --seed 7
  python synthetic_data_generator_v2.py --n-usids 50 --no-kpi
  python synthetic_data_generator_v2.py --n-usids 50 --start-date 2025-02-01 --end-date 2025-04-24 --n-tickets 8
"""

import argparse
import csv
import datetime
import gzip
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

# ── KPI diurnal breakpoints (hour → load_factor) ─────────────────────────────
_DIURNAL_HOURS  = np.array([0, 3, 7, 9, 12, 14, 18, 20, 22, 24], dtype=float)
_DIURNAL_LOADS  = np.array([0.05, 0.03, 0.35, 0.65, 0.75, 0.70,
                             0.90, 1.00, 0.60, 0.05], dtype=float)

# ── Day-of-week load scaling ──────────────────────────────────────────────────
_DOW_SCALE = {0: 1.00, 1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00,  # Mon–Fri
              5: 0.85, 6: 0.70}                                 # Sat, Sun

# ── Plano TX location references for ticket narratives ───────────────────────
_PLANO_LOCATIONS = [
    "Near the intersection of Spring Creek Pkwy and Jupiter Rd",
    "Along Legacy Drive corridor, north of US-75",
    "Preston Rd and Park Blvd area, Collin Creek vicinity",
    "East side of Bob Woodruff Park, off Renner Rd",
    "SH-190 and Coit Rd interchange area",
    "Downtown Plano, near 15th St and K Ave",
    "West Plano near Dallas North Tollway and Headquarters Dr",
    "Plano Medical Center area, near Medical Center Dr",
]

# ── Root-cause narratives ─────────────────────────────────────────────────────
_ROOT_CAUSES  = ["Power failure", "Fiber cut", "Hardware fault",
                 "Software fault", "Unknown"]
_RC_WEIGHTS   = [0.30, 0.25, 0.20, 0.15, 0.10]

_OUTAGE_TYPES   = ["Full Outage", "Partial Outage", "Degraded Service"]
_OT_WEIGHTS     = [0.35, 0.40, 0.25]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _haversine_km(lat_g, lon_g, t_lat, t_lon):
    """Vectorised Haversine distance in km."""
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


def _bearing_deg(lat1, lon1, lat2, lon2):
    """Forward azimuth from point 1 to point 2, degrees [0, 360)."""
    dlon = math.radians(lon2 - lon1)
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    x = math.cos(rlat2) * math.sin(dlon)
    y = (math.cos(rlat1) * math.sin(rlat2)
         - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360

_SECTOR_AZIMUTHS = [0, 120, 240]   # S0=N, S1=SE, S2=SW

def _sector_id(usid_name, tower_lat, tower_lon, pix_lat, pix_lon):
    """Return sector-level ID (e.g. 'USID_09_S2') for a pixel based on bearing from tower."""
    b = _bearing_deg(tower_lat, tower_lon, pix_lat, pix_lon)
    idx = min(range(3), key=lambda i: min(abs(b - _SECTOR_AZIMUTHS[i]),
                                          360 - abs(b - _SECTOR_AZIMUTHS[i])))
    return f"{usid_name}_S{idx}"


def _zip_from_lon(lon):
    """Assign Plano TX zip code by approximate longitude band."""
    if lon < -96.71:
        return "75024"
    elif lon < -96.70:
        return "75023"
    elif lon < -96.69:
        return "75025"
    elif lon < -96.68:
        return "75074"
    else:
        return "75075"


def _weighted_choice(rng, options, weights):
    """Single weighted random choice using rng."""
    cumw = np.cumsum(weights)
    r = rng.random()
    for opt, cw in zip(options, cumw):
        if r <= cw:
            return opt
    return options[-1]


def _is_in_zone(t_lat, t_lon, mask, grid_rows, grid_cols, area_km):
    """Return True if the USID at (t_lat, t_lon) falls inside the boolean mask."""
    x_km = (t_lon - BASE_LON) * 111.32 * math.cos(math.radians(BASE_LAT))
    y_km = (t_lat - BASE_LAT) * 111.32
    nx = x_km / area_km
    ny = y_km / area_km
    c = max(0, min(grid_cols - 1, int(nx * grid_cols)))
    r = max(0, min(grid_rows - 1, int(ny * grid_rows)))
    return bool(mask[r, c])


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
# KPI TIMESERIES GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_kpi(usid_configs, forest_mask, creek_mask, grid_rows, grid_cols,
                 area_km, outage_events, rng, output_dir,
                 start_date=None, end_date=None):
    """
    Generate sector-level KPI timeseries at 15-minute resolution.

    Each USID has 3 sectors (S0=0°, S1=120°, S2=240°). Throughput follows a
    diurnal curve, day-of-week scaling, geographic penalties, per-sector
    asymmetry, and lognormal noise. Outage windows zero or reduce traffic.

    Parameters
    ----------
    usid_configs    List of (name, lat, lon, profile) tuples
    forest_mask     Boolean ndarray from _build_geo_masks
    creek_mask      Boolean ndarray from _build_geo_masks
    grid_rows       Grid height (pixels)
    grid_cols       Grid width (pixels)
    area_km         Side length of the square area in km
    outage_events   List of outage dicts from generate_tickets
    rng             numpy Generator (shared, seed-stable)
    output_dir      pathlib.Path for output files
    start_date      datetime.date — KPI window start (default: today − 60 days)
    end_date        datetime.date — KPI window end (default: today)
    """
    today = datetime.date.today()
    if start_date is None:
        start_date = today - datetime.timedelta(days=60)
    if end_date is None:
        end_date = today

    n_days = (end_date - start_date).days
    if n_days <= 0:
        raise ValueError(f"start_date {start_date} must be before end_date {end_date}")

    n_usids   = len(usid_configs)
    n_sectors = 3
    intervals_per_day = 96   # 15-min slots
    azimuth_by_sector = [0, 120, 240]
    sector_suffixes   = ["S0", "S1", "S2"]

    # ── Pre-compute per-sector stable parameters (seed-stable) ────────────────
    # dl_peak_mbps, ul_peak_mbps, user_peak, prb_peak, sector_mult, rsrp_mean
    sector_params = []
    for usid_idx, (name, t_lat, t_lon, _) in enumerate(usid_configs):
        in_forest = _is_in_zone(t_lat, t_lon, forest_mask,
                                grid_rows, grid_cols, area_km)
        in_creek  = _is_in_zone(t_lat, t_lon, creek_mask,
                                grid_rows, grid_cols, area_km)

        geo_dl   = 0.80 if in_forest else (0.92 if in_creek else 1.0)
        geo_usr  = 0.75 if in_forest else 1.0
        geo_prb  = 1.15 if in_forest else 1.0
        rsrp_mean = -95.0 if in_forest else (-88.0 if in_creek else -85.0)

        for s_idx, (suffix, az) in enumerate(zip(sector_suffixes, azimuth_by_sector)):
            az_bias   = 1.08 if az == 0 else 1.0
            sect_mult = float(rng.uniform(0.85, 1.15))

            dl_peak  = float(rng.uniform(80, 120)) * geo_dl * az_bias * sect_mult
            ul_peak  = dl_peak * 0.25
            usr_peak = float(rng.integers(50, 151)) * geo_usr
            prb_peak = float(rng.uniform(60, 90)) * geo_prb

            sector_params.append({
                "sector_id":   f"{name}_{suffix}",
                "usid":        name,
                "azimuth_deg": az,
                "dl_peak":     dl_peak,
                "ul_peak":     ul_peak,
                "usr_peak":    usr_peak,
                "prb_peak":    min(prb_peak, 100.0),
                "rsrp_mean":   rsrp_mean,
                "in_forest":   in_forest,
                "in_creek":    in_creek,
            })

    # ── Build outage lookup: usid → list of (start_dt, end_dt, type) ─────────
    outage_lookup = {}
    for ev in outage_events:
        uid = ev["affected_usid"]
        s_dt = datetime.datetime.strptime(ev["outage_start_utc"], "%Y-%m-%dT%H:%M:%SZ")
        e_dt = (datetime.datetime.strptime(ev["outage_end_utc"], "%Y-%m-%dT%H:%M:%SZ")
                if ev["outage_end_utc"] else None)
        outage_lookup.setdefault(uid, []).append((s_dt, e_dt, ev["outage_type"]))

    # ── Generate timestamps for one day (reused each day) ────────────────────
    slot_minutes = [h * 15 for h in range(intervals_per_day)]   # 0..1425

    # ── Stream-write CSV ──────────────────────────────────────────────────────
    out = Path(output_dir)
    csv_path = out / "kpi_sector_timeseries.csv"

    fieldnames = [
        "sector_id", "usid", "azimuth_deg", "timestamp_utc",
        "throughput_dl_mbps", "throughput_ul_mbps",
        "volume_dl_gb", "volume_ul_gb",
        "connected_users", "prb_utilization_pct",
        "avg_rsrp_dbm", "avg_sinr_db",
    ]

    total_rows      = 0
    outage_affected = 0
    dl_sum          = 0.0
    dl_count        = 0
    forest_dl_sum   = 0.0
    forest_dl_count = 0

    print(f"  [kpi] Writing {csv_path.name}  "
          f"({n_usids} USIDs × 3 sectors × {n_days} days × 96 intervals)…",
          flush=True)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for day_offset in range(n_days):
            cur_date = start_date + datetime.timedelta(days=day_offset)
            dow      = cur_date.weekday()   # 0=Mon … 6=Sun
            dow_scale = _DOW_SCALE[dow]

            for slot in range(intervals_per_day):
                hour_frac = slot_minutes[slot] / 60.0
                load_factor = float(np.interp(hour_frac,
                                              _DIURNAL_HOURS, _DIURNAL_LOADS))
                load = load_factor * dow_scale

                slot_dt = datetime.datetime(
                    cur_date.year, cur_date.month, cur_date.day,
                    slot_minutes[slot] // 60, slot_minutes[slot] % 60, 0)
                ts_str = slot_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

                for sp in sector_params:
                    # Lognormal noise
                    noise = float(np.exp(rng.normal(0, 0.08)))

                    dl_raw  = sp["dl_peak"]  * load * noise
                    ul_raw  = sp["ul_peak"]  * load * noise
                    usr_raw = sp["usr_peak"] * load * noise
                    prb_raw = min(sp["prb_peak"] * load, 100.0)

                    # RSRP / SINR
                    rsrp = float(np.clip(rng.normal(sp["rsrp_mean"], 8), -120, -60))
                    sinr = float(np.clip(rng.normal(12, 5), -5, 30))

                    # Check outage
                    outage_hit = False
                    for (o_start, o_end, o_type) in outage_lookup.get(sp["usid"], []):
                        if slot_dt >= o_start and (o_end is None or slot_dt < o_end):
                            outage_hit = True
                            if o_type == "Full Outage":
                                dl_raw = ul_raw = usr_raw = prb_raw = 0.0
                            elif o_type == "Partial Outage":
                                dl_raw  *= 0.20
                                ul_raw  *= 0.20
                                usr_raw *= 0.20
                            outage_affected += 1
                            break

                    vol_dl = dl_raw  * (15 / 60) / 1024
                    vol_ul = ul_raw  * (15 / 60) / 1024

                    writer.writerow({
                        "sector_id":           sp["sector_id"],
                        "usid":                sp["usid"],
                        "azimuth_deg":         sp["azimuth_deg"],
                        "timestamp_utc":       ts_str,
                        "throughput_dl_mbps":  f"{dl_raw:.2f}",
                        "throughput_ul_mbps":  f"{ul_raw:.2f}",
                        "volume_dl_gb":        f"{vol_dl:.4f}",
                        "volume_ul_gb":        f"{vol_ul:.4f}",
                        "connected_users":     int(max(usr_raw, 0)),
                        "prb_utilization_pct": f"{prb_raw:.2f}",
                        "avg_rsrp_dbm":        f"{rsrp:.2f}",
                        "avg_sinr_db":         f"{sinr:.2f}",
                    })
                    total_rows += 1

                    if not outage_hit:
                        dl_sum   += dl_raw
                        dl_count += 1
                        if sp["in_forest"]:
                            forest_dl_sum   += dl_raw
                            forest_dl_count += 1

    # ── USID completeness check ───────────────────────────────────────────────
    written_usids = set()
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            written_usids.add(row["usid"])

    if written_usids != set(c[0] for c in usid_configs):
        missing = set(c[0] for c in usid_configs) - written_usids
        raise ValueError(f"[kpi] Missing USIDs in output: {missing}")
    print(f"  [kpi] Verified: all {n_usids} USIDs present in KPI output ✓")

    mean_dl       = dl_sum / dl_count if dl_count else 0.0
    forest_mean   = forest_dl_sum / forest_dl_count if forest_dl_count else 0.0

    print(f"  [kpi] Total rows written:      {total_rows:,}")
    print(f"  [kpi] Mean DL throughput:      {mean_dl:.1f} Mbps  (all sectors, non-outage)")
    print(f"  [kpi] Forest-zone mean DL:     {forest_mean:.1f} Mbps")
    print(f"  [kpi] Outage-affected intervals: {outage_affected:,}")

    return csv_path


# Module-level alias so generate() can call the function without the parameter
# name `generate_kpi` (bool) shadowing the function in its local scope.
generate_kpi_fn = generate_kpi


# ─────────────────────────────────────────────────────────────────────────────
# OUTAGE TICKET GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_tickets(usid_configs, forest_mask, creek_mask,
                     grid_rows, grid_cols, area_km,
                     n_tickets, rng, output_dir,
                     kpi_start_date=None, kpi_end_date=None):
    """
    Generate synthetic outage tickets for a set of USIDs.

    Guarantees at least one Full Outage, one Partial Outage, and one OPEN
    ticket (ongoing, no end time). Returns a list of outage event dicts
    that generate_kpi uses to impose outage windows on the KPI timeseries.

    Parameters
    ----------
    usid_configs     List of (name, lat, lon, profile) tuples
    forest_mask      Boolean ndarray
    creek_mask       Boolean ndarray
    grid_rows        Grid height
    grid_cols        Grid width
    area_km          Area side length in km
    n_tickets        Number of tickets to generate
    rng              numpy Generator
    output_dir       pathlib.Path
    kpi_start_date   datetime.date — ticket window start
    kpi_end_date     datetime.date — ticket window end
    """
    today = datetime.date.today()
    if kpi_start_date is None:
        kpi_start_date = today - datetime.timedelta(days=60)
    if kpi_end_date is None:
        kpi_end_date = today

    window_seconds = int((kpi_end_date - kpi_start_date).total_seconds()
                         if hasattr(kpi_end_date, 'total_seconds')
                         else (datetime.datetime.combine(kpi_end_date, datetime.time())
                               - datetime.datetime.combine(kpi_start_date, datetime.time())
                               ).total_seconds())

    win_start_dt = datetime.datetime.combine(kpi_start_date, datetime.time(0, 0, 0))
    win_end_dt   = datetime.datetime.combine(kpi_end_date,   datetime.time(0, 0, 0))

    # ── Duration ranges per outage type (hours) ───────────────────────────────
    _duration_ranges = {
        "Full Outage":      (1,  8),
        "Partial Outage":   (2,  24),
        "Degraded Service": (4,  72),
    }

    n_usids = len(usid_configs)
    usid_pool = list(range(n_usids))
    rng.shuffle(usid_pool)

    # ── Force guaranteed tickets first ────────────────────────────────────────
    forced_types   = ["Full Outage", "Partial Outage"]
    forced_open    = True    # at least one OPEN

    tickets     = []
    used_usids  = set()

    def _make_ticket(ticket_idx, otype, force_open=False):
        """Build one ticket dict."""
        # Pick USID — no repeat if pool allows
        avail = [i for i in usid_pool if usid_configs[i][0] not in used_usids]
        if not avail:
            avail = list(range(n_usids))
        cfg_idx = avail[int(rng.integers(0, len(avail)))]
        name, t_lat, t_lon, _ = usid_configs[cfg_idx]
        used_usids.add(name)

        # Duration
        dur_lo, dur_hi = _duration_ranges[otype]
        dur_hours = float(rng.uniform(dur_lo, dur_hi))
        dur_sec   = int(dur_hours * 3600)

        # Start time: random within window minus duration
        max_start_offset = max(int(window_seconds) - dur_sec, 3600)
        start_offset_sec = int(rng.integers(0, max_start_offset))
        o_start = win_start_dt + datetime.timedelta(seconds=start_offset_sec)
        o_end   = o_start + datetime.timedelta(seconds=dur_sec)
        if o_end > win_end_dt:
            o_end = win_end_dt

        # OPEN ticket → null end
        if force_open:
            o_end_str = None
            status_choices = ["OPEN", "IN_PROGRESS"]
            status_weights = [0.60, 0.40]
        else:
            o_end_str = o_end.strftime("%Y-%m-%dT%H:%M:%SZ")
            status_choices = ["RESOLVED", "IN_PROGRESS"]
            status_weights = [0.80, 0.20]

        status = _weighted_choice(rng, status_choices, status_weights)

        # Priority
        if otype == "Full Outage":
            priority = _weighted_choice(rng, ["P1", "P2"], [0.80, 0.20])
        elif otype == "Partial Outage":
            priority = _weighted_choice(rng, ["P2", "P1"], [0.70, 0.30])
        else:
            priority = _weighted_choice(rng, ["P3", "P2"], [0.70, 0.30])

        # Sector spread
        sector_choices = ["All", "S0,S1", "S1,S2", "S0,S2", "S0", "S1", "S2"]
        affected_sectors = str(rng.choice(sector_choices))

        # Root cause
        root_cause = _weighted_choice(rng, _ROOT_CAUSES, _RC_WEIGHTS)

        # Location text
        loc_base = _PLANO_LOCATIONS[int(rng.integers(0, len(_PLANO_LOCATIONS)))]
        location_natural = f"{loc_base}, serving sector near lat {t_lat:.4f}"

        # Zip code
        zip_code = _zip_from_lon(t_lon)

        # reporter
        if rng.random() < 0.4:
            reporter = "NOC_AUTO"
        else:
            tech_id = int(rng.integers(10, 100))
            reporter = f"Field_Tech_{tech_id:02d}"

        # Ticket ID
        date_tag = o_start.strftime("%Y-%m-%d")
        tkt_id   = f"TKT-{date_tag}-{ticket_idx:04d}"

        # Notes narrative
        rc_lower = root_cause.lower()
        notes = (f"{otype} reported at {name} due to {rc_lower}. "
                 f"Affecting {affected_sectors} sectors in the {zip_code} area. "
                 f"Estimated impact: {dur_hours:.1f} hours of service disruption.")

        resolution_notes = None
        if status == "RESOLVED":
            resolution_notes = (f"Issue resolved after {dur_hours:.1f} hours. "
                                f"Root cause confirmed as {rc_lower}. "
                                f"Service restored to normal levels.")

        return {
            "ticket_id":         tkt_id,
            "status":            status,
            "priority":          priority,
            "outage_type":       otype,
            "affected_usid":     name,
            "affected_sectors":  affected_sectors,
            "location_natural":  location_natural,
            "zip_code":          zip_code,
            "city_state":        "Plano, TX",
            "lat":               round(t_lat, 6),
            "lon":               round(t_lon, 6),
            "outage_start_utc":  o_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outage_end_utc":    o_end_str,
            "reported_by":       reporter,
            "root_cause":        root_cause,
            "notes":             notes,
            "resolution_notes":  resolution_notes,
        }

    # ── Build ticket list with guarantees ─────────────────────────────────────
    ticket_list = []
    open_ticket_placed = False

    # Ticket 0: forced Full Outage, OPEN
    ticket_list.append(_make_ticket(0, "Full Outage", force_open=True))
    ticket_list[-1]["outage_end_utc"] = None
    ticket_list[-1]["status"] = "OPEN"
    open_ticket_placed = True

    # Ticket 1: forced Partial Outage
    if n_tickets >= 2:
        ticket_list.append(_make_ticket(1, "Partial Outage", force_open=False))

    # Remaining tickets: random types
    for idx in range(2, n_tickets):
        otype = _weighted_choice(rng, _OUTAGE_TYPES, _OT_WEIGHTS)
        ticket_list.append(_make_ticket(idx, otype, force_open=False))

    # ── Write JSON ────────────────────────────────────────────────────────────
    out = Path(output_dir)
    json_path = out / "outage_tickets.json"

    generated_at = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "generated_at": generated_at,
        "n_tickets":    len(ticket_list),
        "tickets":      ticket_list,
    }

    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)

    # ── Quality summary ───────────────────────────────────────────────────────
    from collections import Counter
    ot_counts     = Counter(t["outage_type"] for t in ticket_list)
    st_counts     = Counter(t["status"]      for t in ticket_list)
    rc_counts     = Counter(t["root_cause"]  for t in ticket_list)
    all_starts    = [t["outage_start_utc"] for t in ticket_list]
    all_ends      = [t["outage_end_utc"]   for t in ticket_list if t["outage_end_utc"]]

    print(f"  [json] {json_path.name}  ({len(ticket_list)} tickets)")
    print(f"  [json] outage_type: {dict(ot_counts)}")
    print(f"  [json] status:      {dict(st_counts)}")
    print(f"  [json] root_cause:  {dict(rc_counts)}")
    print(f"  [json] Earliest start: {min(all_starts)}")
    if all_ends:
        print(f"  [json] Latest end:     {max(all_ends)}")

    # Return outage event dicts for KPI consumption
    outage_events = [
        {
            "affected_usid":    t["affected_usid"],
            "outage_type":      t["outage_type"],
            "outage_start_utc": t["outage_start_utc"],
            "outage_end_utc":   t["outage_end_utc"],
        }
        for t in ticket_list
    ]
    return outage_events


# Module-level alias so generate() can call the function without the parameter
# name `generate_tickets` (bool) shadowing the function in its local scope.
generate_tickets_fn = generate_tickets


# ─────────────────────────────────────────────────────────────────────────────
# MAIN GENERATION FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def generate(output_dir="synthetic_output", seed=42, n_usids=50,
             area_id=None, target_usid=None,
             generate_kpi=True, generate_tickets=True,
             n_tickets=5, kpi_start_date=None, kpi_end_date=None):
    """
    Generate pixel JSON + attribute CSV + optional KPI timeseries + tickets
    for Plano TX area with geographic features.

    Parameters
    ----------
    n_usids          Number of base stations (recommend 20-100)
    area_id          Written into JSON header (auto-generated if None)
    target_usid      Target USID name (defaults to USID_00 = center tower)
    generate_kpi     If True, write kpi_sector_timeseries.csv
    generate_tickets If True, write outage_tickets.json
    n_tickets        Number of outage tickets to generate
    kpi_start_date   datetime.date — KPI window start (default: today − 60 days)
    kpi_end_date     datetime.date — KPI window end (default: today)
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
            pix_lat  = float(lat_grid[r, c])
            pix_lon  = float(lon_grid[r, c])

            backups = []
            for rank in range(1, len(usid_names)):
                cand_i    = int(sorted_idx[rank, r, c])
                cand_name = usid_names[cand_i]
                cand_rsrp = float(rsrp_stack[cand_i, r, c])
                if cand_rsrp >= dom_val - BACKUP_GAP_DB:
                    ct_lat, ct_lon = tower_loc[cand_name]
                    backups.append({"ID":   _sector_id(cand_name, ct_lat, ct_lon, pix_lat, pix_lon),
                                    "lat":  round(ct_lat, 6),
                                    "lon":  round(ct_lon, 6),
                                    "rsrp": round(cand_rsrp, 2)})
                if len(backups) >= 2:
                    break

            if not backups:
                hole_count += 1

            pixels.append({
                "lat": round(pix_lat, 6),
                "lon": round(pix_lon, 6),
                "info": {
                    "dominant": {"ID":   _sector_id(dom_name, dom_tlat, dom_tlon, pix_lat, pix_lon),
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

    # ── Step 5: Generate ticket outage events ─────────────────────────────────
    outage_events = []
    if generate_tickets:
        outage_events = generate_tickets_fn(
            usid_configs, forest_mask, creek_mask,
            grid_rows, grid_cols, area_km,
            n_tickets, rng, out,
            kpi_start_date=kpi_start_date,
            kpi_end_date=kpi_end_date)

    # ── Step 6: Generate KPI timeseries ───────────────────────────────────────
    if generate_kpi:
        generate_kpi_fn(
            usid_configs, forest_mask, creek_mask,
            grid_rows, grid_cols, area_km,
            outage_events, rng, out,
            start_date=kpi_start_date,
            end_date=kpi_end_date)

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
    """Parse CLI arguments including new KPI and ticket controls."""
    p = argparse.ArgumentParser(
        description="Generate synthetic USID data for Plano TX with geographic features.")
    p.add_argument("--output-dir",  default="data")
    p.add_argument("--n-usids",     type=int, default=50,
                   help="Number of USIDs (default: 50)")
    p.add_argument("--seed",        type=int, default=42)
    p.add_argument("--area-id",     default=None)
    p.add_argument("--no-kpi",      action="store_true",
                   help="Skip KPI timeseries generation")
    p.add_argument("--no-tickets",  action="store_true",
                   help="Skip outage ticket generation")
    p.add_argument("--n-tickets",   type=int, default=5,
                   help="Number of outage tickets to generate (default: 5)")
    p.add_argument("--start-date",  default=None,
                   help="KPI window start date YYYY-MM-DD (default: 60 days ago)")
    p.add_argument("--end-date",    default=None,
                   help="KPI window end date YYYY-MM-DD (default: today)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse()

    start_date = (datetime.date.fromisoformat(args.start_date)
                  if args.start_date else None)
    end_date   = (datetime.date.fromisoformat(args.end_date)
                  if args.end_date else None)

    print(f"Generating synthetic data for Plano TX "
          f"(N={args.n_usids} USIDs, seed={args.seed})…")
    jp, cp, tgt = generate(
        output_dir=args.output_dir,
        seed=args.seed,
        n_usids=args.n_usids,
        area_id=args.area_id,
        generate_kpi=not args.no_kpi,
        generate_tickets=not args.no_tickets,
        n_tickets=args.n_tickets,
        kpi_start_date=start_date,
        kpi_end_date=end_date,
    )
    print(f"\nDone. Workflow inputs:")
    print(f"  --coverage-json  {jp}")
    print(f"  --attr-csv       {cp}")
    print(f"  --target-usid    {tgt}")
