from __future__ import annotations

"""
Coverage impact analysis for base station outage simulation.

Simulation approach
-------------------
Affected pixels are those whose dominant cell belongs to the downed site:
  - Full outage  (affected_sectors=None):  any sector of target_usid
  - Partial outage (affected_sectors=[…]): only the listed sector IDs

Post-outage signal assignment per affected pixel:
  1. Use backup1 if it exists and is not itself affected.
  2. Otherwise use backup2 if it exists and is not affected.
  3. If no valid backup: RSRP=-120 dBm, SINR=-20 dB, RSRQ=-20 dB, tput=0.

SINR / RSRQ after outage are estimated by shifting the pre-outage value by the
backup-vs-dominant RSRP delta (dB): Δ = backup_rsrp − dominant_rsrp.
This is the standard dB-domain additive approximation.

Throughput after outage scales by the linear power ratio corresponding to Δ
(i.e. 10^(Δ/10)), clipped to zero.

No LLM calls are made.  get_area_profile and get_geo_features are imported
directly from /workspace/version_3/mcp_server/server.py — no MCP protocol.
"""

import base64
import io
import json
import os
import sys
from collections import Counter
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DATA_FILE  = "/workspace/version_3/data/usid_coverage_pixels.json"
_SERVER_DIR = "/workspace/version_3/mcp_server"

_FLOOR_RSRP = -120.0
_FLOOR_SINR =  -20.0
_FLOOR_RSRQ =  -20.0
_HOLE_RSRP_THRESHOLD = -110.0  # dBm

# Set DATA_DIR before server.py is ever imported so its module-level
# _load_data() call finds the right files.
os.environ.setdefault("DATA_DIR", "/workspace/version_3/data")

# ---------------------------------------------------------------------------
# Pixel cache
# ---------------------------------------------------------------------------
_pixels_cache: Optional[list] = None


def _load_pixels() -> list:
    global _pixels_cache
    if _pixels_cache is None:
        with open(_DATA_FILE) as fh:
            _pixels_cache = json.load(fh)["pixels"]
    return _pixels_cache


# ---------------------------------------------------------------------------
# Server function imports (direct call, no MCP protocol)
# ---------------------------------------------------------------------------
def _get_server_fns():
    """Return (get_area_profile, get_geo_features) from the MCP server module."""
    if _SERVER_DIR not in sys.path:
        sys.path.insert(0, _SERVER_DIR)
    try:
        import server as _srv  # noqa: PLC0415
        return _srv.get_area_profile, _srv.get_geo_features
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _parent_usid(sector_id: str) -> str:
    """'USID_20_S1' → 'USID_20';  already-parent IDs pass through unchanged."""
    parts = sector_id.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) >= 2 and parts[1][0] == "S" and parts[1][1:].isdigit():
        return parts[0]
    return sector_id


def _is_affected(cell_id: Optional[str], target_usid: str,
                 affected_sectors: Optional[list]) -> bool:
    if cell_id is None:
        return False
    if affected_sectors is None:
        return cell_id == target_usid or cell_id.startswith(target_usid + "_S")
    return cell_id in affected_sectors


def _stats4(arr: np.ndarray) -> dict:
    return {
        "mean": float(np.mean(arr)),
        "p10":  float(np.percentile(arr, 10)),
        "p50":  float(np.percentile(arr, 50)),
        "p90":  float(np.percentile(arr, 90)),
    }


def _stats3(arr: np.ndarray) -> dict:
    return {
        "mean": float(np.mean(arr)),
        "p10":  float(np.percentile(arr, 10)),
        "p50":  float(np.percentile(arr, 50)),
    }


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------
def get_neighbor_usids(target_usid: str) -> list[str]:
    """Return parent USIDs that serve as backup for >5 % of target's dominant pixels.

    Call this before run_coverage_preprocessing to identify which neighbor sites
    need KPI history pulled.
    """
    pixels = _load_pixels()
    dominant_pixels = [
        p for p in pixels
        if _is_affected(p["info"]["dominant"]["ID"], target_usid, None)
    ]
    if not dominant_pixels:
        return []

    threshold = 0.05 * len(dominant_pixels)
    counts: Counter = Counter()
    for p in dominant_pixels:
        info = p["info"]
        for key in ("backup1", "backup2"):
            cell = info.get(key)
            if cell:
                counts[_parent_usid(cell["ID"])] += 1

    return [usid for usid, cnt in counts.items() if cnt > threshold]


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------
def run_coverage_preprocessing(
    target_usid: str,
    affected_sectors: list[str] | None,
    output_dir: str,
) -> dict:
    """Run deterministic coverage impact analysis for a base station outage.

    Parameters
    ----------
    target_usid:      Parent USID of the downed site (e.g. 'USID_20').
    affected_sectors: None for full outage; list of sector IDs for partial outage.
    output_dir:       Directory where PNG maps are saved (created if absent).

    Returns
    -------
    dict with keys: signal_statistics, coverage_hole, per_backup, geographic, map_paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    pixels = _load_pixels()

    # ------------------------------------------------------------------
    # 1. Classify pixels into affected / unaffected
    # ------------------------------------------------------------------
    affected_rows = []
    for p in pixels:
        dom_id = p["info"]["dominant"]["ID"]
        if _is_affected(dom_id, target_usid, affected_sectors):
            affected_rows.append(p)

    total_count    = len(pixels)
    affected_count = len(affected_rows)

    # ------------------------------------------------------------------
    # 2. Simulate post-outage signal for every affected pixel
    # ------------------------------------------------------------------
    records = []
    for p in affected_rows:
        info = p["info"]
        dom  = info["dominant"]
        b1   = info.get("backup1")
        b2   = info.get("backup2")

        rsrp_before = dom["rsrp"]
        sinr_before = info["sinr_db"]
        rsrq_before = info["rsrq_db"]
        tput_before = info["throughput_mbps"]

        # Select first valid (non-affected) backup
        backup = None
        if b1 and not _is_affected(b1["ID"], target_usid, affected_sectors):
            backup = b1
        elif b2 and not _is_affected(b2["ID"], target_usid, affected_sectors):
            backup = b2

        if backup is not None:
            rsrp_after    = backup["rsrp"]
            delta_db      = rsrp_after - rsrp_before          # negative = weaker
            sinr_after    = sinr_before + delta_db
            rsrq_after    = rsrq_before + delta_db
            linear_ratio  = 10.0 ** (delta_db / 10.0)
            tput_after    = max(0.0, tput_before * linear_ratio)
            backup_parent = _parent_usid(backup["ID"])
            dom_after     = backup_parent
        else:
            rsrp_after    = _FLOOR_RSRP
            sinr_after    = _FLOOR_SINR
            rsrq_after    = _FLOOR_RSRQ
            tput_after    = 0.0
            backup_parent = None
            dom_after     = "NO_SIGNAL"

        records.append({
            "lat":          p["lat"],
            "lon":          p["lon"],
            "rsrp_before":  rsrp_before,
            "rsrp_after":   rsrp_after,
            "sinr_before":  sinr_before,
            "sinr_after":   sinr_after,
            "rsrq_before":  rsrq_before,
            "rsrq_after":   rsrq_after,
            "tput_before":  tput_before,
            "tput_after":   tput_after,
            "backup_parent": backup_parent,
            "dom_before":   _parent_usid(dom["ID"]),
            "dom_after":    dom_after,
        })

    # Numpy arrays for vectorised statistics
    lats    = np.array([r["lat"]         for r in records])
    lons    = np.array([r["lon"]         for r in records])
    rsrp_b  = np.array([r["rsrp_before"] for r in records])
    rsrp_a  = np.array([r["rsrp_after"]  for r in records])
    rsrp_d  = rsrp_b - rsrp_a
    sinr_b  = np.array([r["sinr_before"] for r in records])
    sinr_a  = np.array([r["sinr_after"]  for r in records])
    sinr_d  = sinr_b - sinr_a
    rsrq_b  = np.array([r["rsrq_before"] for r in records])
    rsrq_a  = np.array([r["rsrq_after"]  for r in records])
    rsrq_d  = rsrq_b - rsrq_a
    tput_b  = np.array([r["tput_before"] for r in records])
    tput_a  = np.array([r["tput_after"]  for r in records])
    tput_d  = tput_b - tput_a

    # ------------------------------------------------------------------
    # 3. Signal statistics
    # ------------------------------------------------------------------
    signal_statistics = {
        "rsrp_before":       _stats4(rsrp_b),
        "rsrp_after":        _stats4(rsrp_a),
        "rsrp_drop":         _stats4(rsrp_d),
        "sinr_before":       _stats4(sinr_b),
        "sinr_after":        _stats4(sinr_a),
        "sinr_drop":         _stats4(sinr_d),
        "rsrq_before":       _stats4(rsrq_b),
        "rsrq_after":        _stats4(rsrq_a),
        "rsrq_drop":         _stats4(rsrq_d),
        "throughput_before": _stats4(tput_b),
        "throughput_after":  _stats4(tput_a),
        "throughput_drop":   _stats4(tput_d),
    }

    # ------------------------------------------------------------------
    # 4. Coverage hole
    # ------------------------------------------------------------------
    hole_mask    = rsrp_a < _HOLE_RSRP_THRESHOLD
    hole_count   = int(np.sum(hole_mask))
    hole_coords  = [
        {"lat": r["lat"], "lon": r["lon"]}
        for r, is_hole in zip(records, hole_mask)
        if is_hole
    ]

    coverage_hole = {
        "coverage_hole_count":    hole_count,
        "coverage_hole_fraction": hole_count / affected_count if affected_count > 0 else 0.0,
        "coverage_hole_coords":   hole_coords,
        "affected_coordinate_count": affected_count,
        "total_coordinate_count":    total_count,
    }

    # ------------------------------------------------------------------
    # 5. Per-backup statistics
    # ------------------------------------------------------------------
    # Existing dominance counts across ALL pixels (pre-outage)
    all_dom_parent_counts: dict = {}
    for p in pixels:
        parent = _parent_usid(p["info"]["dominant"]["ID"])
        all_dom_parent_counts[parent] = all_dom_parent_counts.get(parent, 0) + 1

    absorbed_counts: dict = {}
    absorbed_rsrp:   dict = {}
    for r in records:
        bp = r["backup_parent"]
        if bp is None:
            continue
        absorbed_counts[bp] = absorbed_counts.get(bp, 0) + 1
        absorbed_rsrp.setdefault(bp, []).append(r["rsrp_after"])

    per_backup: dict = {}
    for bp, cnt in absorbed_counts.items():
        rsrp_arr = np.array(absorbed_rsrp[bp])
        existing = all_dom_parent_counts.get(bp, 0)
        per_backup[bp] = {
            "newly_absorbed_count":       cnt,
            "newly_absorbed_fraction":    cnt / affected_count if affected_count > 0 else 0.0,
            "existing_dominant_count":    existing,
            "existing_dominant_fraction": existing / total_count if total_count > 0 else 0.0,
            "rsrp_in_absorbed_area":      _stats3(rsrp_arr),
        }

    # ------------------------------------------------------------------
    # 6. Geographic
    # ------------------------------------------------------------------
    centroid_lat = float(np.mean(lats)) if affected_count > 0 else 0.0
    centroid_lon = float(np.mean(lons)) if affected_count > 0 else 0.0

    get_area_profile_fn, get_geo_features_fn = _get_server_fns()

    if get_area_profile_fn is not None:
        try:
            area_profile = get_area_profile_fn(centroid_lat, centroid_lon, radius_m=1000)
        except Exception as exc:
            area_profile = {"error": str(exc)}
    else:
        area_profile = {"error": "server import failed"}

    geographic = {
        "centroid":     {"lat": centroid_lat, "lon": centroid_lon},
        "area_profile": area_profile,
    }

    # ------------------------------------------------------------------
    # 7. Maps
    # ------------------------------------------------------------------
    map_paths = _generate_maps(
        records=records,
        lats=lats, lons=lons,
        rsrp_d=rsrp_d, sinr_d=sinr_d, tput_d=tput_d,
        hole_mask=hole_mask,
        area_profile=area_profile,
        centroid_lat=centroid_lat, centroid_lon=centroid_lon,
        get_geo_features_fn=get_geo_features_fn,
        output_dir=output_dir,
    )

    return {
        "signal_statistics": signal_statistics,
        "coverage_hole":     coverage_hole,
        "per_backup":        per_backup,
        "geographic":        geographic,
        "map_paths":         map_paths,
    }


# ---------------------------------------------------------------------------
# Map generation
# ---------------------------------------------------------------------------
def _scatter_heatmap(lons, lats, values, title, cbar_label, path):
    """Generic scatter heatmap helper; saves and closes the figure."""
    vmax = float(np.max(values)) if len(values) > 0 else 1.0
    vmax = max(vmax, 0.01)
    fig, ax = plt.subplots(figsize=(8, 6))
    sc = ax.scatter(lons, lats, c=values, cmap="YlOrRd", s=12, vmin=0, vmax=vmax)
    fig.colorbar(sc, ax=ax, label=cbar_label)
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def _generate_maps(
    records: list,
    lats: np.ndarray,
    lons: np.ndarray,
    rsrp_d: np.ndarray,
    sinr_d: np.ndarray,
    tput_d: np.ndarray,
    hole_mask: np.ndarray,
    area_profile: dict,
    centroid_lat: float,
    centroid_lon: float,
    get_geo_features_fn,
    output_dir: str,
) -> dict:
    map_paths: dict = {}

    # ------------------------------------------------------------------
    # Map 1: RSRP drop heatmap
    # ------------------------------------------------------------------
    path = os.path.join(output_dir, "rsrp_drop_heatmap.png")
    _scatter_heatmap(lons, lats, rsrp_d,
                     "RSRP Drop (dB) after Outage", "RSRP Drop (dB)", path)
    map_paths["rsrp_drop"] = path

    # ------------------------------------------------------------------
    # Map 2: SINR drop heatmap
    # ------------------------------------------------------------------
    path = os.path.join(output_dir, "sinr_drop_heatmap.png")
    _scatter_heatmap(lons, lats, sinr_d,
                     "SINR Drop (dB) after Outage", "SINR Drop (dB)", path)
    map_paths["sinr_drop"] = path

    # ------------------------------------------------------------------
    # Map 3: Throughput drop heatmap
    # ------------------------------------------------------------------
    path = os.path.join(output_dir, "throughput_drop_heatmap.png")
    _scatter_heatmap(lons, lats, tput_d,
                     "Throughput Drop (Mbps) after Outage", "Throughput Drop (Mbps)", path)
    map_paths["throughput_drop"] = path

    # ------------------------------------------------------------------
    # Map 4: Dominant site before / after
    # ------------------------------------------------------------------
    path = os.path.join(output_dir, "dominant_site_before_after.png")
    dom_before = [r["dom_before"] for r in records]
    dom_after  = [r["dom_after"]  for r in records]
    all_sites  = sorted(set(dom_before) | set(dom_after))

    cmap_tab = plt.get_cmap("tab20")
    site_color = {s: cmap_tab(i % 20) for i, s in enumerate(all_sites)}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    for site in all_sites:
        mask = np.array([d == site for d in dom_before])
        if mask.any():
            ax1.scatter(lons[mask], lats[mask],
                        c=[site_color[site]], s=12, label=site)
    ax1.set_title("Dominant Site — Before Outage")
    ax1.set_xlabel("Longitude")
    ax1.set_ylabel("Latitude")

    for site in all_sites:
        mask = np.array([d == site for d in dom_after])
        if mask.any():
            ax2.scatter(lons[mask], lats[mask],
                        c=[site_color[site]], s=12, label=site)
    ax2.set_title("Dominant Site — After Outage")
    ax2.set_xlabel("Longitude")
    ax2.set_ylabel("Latitude")

    handles = [mpatches.Patch(color=site_color[s], label=s) for s in all_sites]
    fig.legend(handles=handles, loc="lower center",
               ncol=min(6, len(all_sites)), bbox_to_anchor=(0.5, -0.04), fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    map_paths["dominant_before_after"] = path

    # ------------------------------------------------------------------
    # Map 5: Coverage hole overlay + facility markers
    # ------------------------------------------------------------------
    path = os.path.join(output_dir, "coverage_hole_overlay.png")
    fig, ax = plt.subplots(figsize=(9, 7))

    normal_mask = ~hole_mask
    ax.scatter(lons[normal_mask], lats[normal_mask],
               c="lightgrey", s=12, label="Affected (no hole)", zorder=2)
    if hole_mask.any():
        ax.scatter(lons[hole_mask], lats[hole_mask],
                   c="red", s=20, label="Coverage Hole", zorder=3)

    legend_patches = [
        mpatches.Patch(color="lightgrey", label="Affected (no hole)"),
        mpatches.Patch(color="red",       label="Coverage Hole (<−110 dBm)"),
    ]

    # Facility markers: position at centroid with small offsets for visibility
    lat_step = (lats.max() - lats.min()) * 0.04 if len(lats) > 0 else 0.001
    lon_step = (lons.max() - lons.min()) * 0.04 if len(lons) > 0 else 0.001

    facility_defs = [
        ("has_hospital", "H", "royalblue",    0,         0,         "Hospital"),
        ("has_school",   "S", "forestgreen",  lat_step,  0,         "School"),
        ("has_railway",  "R", "darkorchid",   0,         lon_step,  "Railway"),
    ]
    for key, marker_text, color, dlat, dlon, label in facility_defs:
        if area_profile.get(key):
            ax.plot(centroid_lon + dlon, centroid_lat + dlat,
                    marker=f"${marker_text}$", color=color,
                    markersize=14, linestyle="None", zorder=4)
            legend_patches.append(mpatches.Patch(color=color, label=label))

    ax.legend(handles=legend_patches, loc="upper right", fontsize=8)
    ax.set_title("Coverage Hole Overlay")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    map_paths["coverage_hole_overlay"] = path

    # ------------------------------------------------------------------
    # Map 6: Landuse map (base64 PNG from get_geo_features)
    # ------------------------------------------------------------------
    path = os.path.join(output_dir, "landuse_map.png")
    dominant_lu = area_profile.get("dominant_landuse", "unknown")
    error_msg   = None

    if get_geo_features_fn is not None:
        try:
            geo_result = get_geo_features_fn(centroid_lat, centroid_lon, radius_km=5.0)
            img_bytes  = base64.b64decode(geo_result["image_base64"])
            import matplotlib.image as mpimg  # noqa: PLC0415
            img_arr = mpimg.imread(io.BytesIO(img_bytes), format="png")

            fig, ax = plt.subplots(figsize=(8, 8))
            ax.imshow(img_arr)
            ax.axis("off")
            ax.text(0.02, 0.02, f"Dominant landuse: {dominant_lu}",
                    transform=ax.transAxes, fontsize=10, color="white",
                    bbox=dict(boxstyle="round", facecolor="black", alpha=0.6))
            ax.set_title("Geo Features Map")
            fig.tight_layout()
            fig.savefig(path, dpi=100)
            plt.close(fig)
            map_paths["landuse_map"] = path
            return map_paths
        except Exception as exc:
            error_msg = str(exc)
    else:
        error_msg = "server import failed — get_geo_features unavailable"

    # Fallback: blank figure with error message
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.text(0.5, 0.5, f"Landuse map unavailable:\n{error_msg}",
            ha="center", va="center", transform=ax.transAxes,
            fontsize=10, wrap=True)
    ax.set_title("Geo Features Map (unavailable)")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    map_paths["landuse_map"] = path
    return map_paths
