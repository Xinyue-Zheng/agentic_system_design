from __future__ import annotations

"""
Coverage impact analysis for base station outage simulation — new JSONL input format.

New input format
----------------
Data is organized under a root directory with one subfolder per USID (named by USID).
Each subfolder contains 100+ JSONL files. Each line in a JSONL file is one JSON object:

  {"<cor_x_y>": [   ← key name varies per record (x/y are pixel coordinates)
    {
      "info": {
        "rsrq": float,
        "rssi": float,
        "serving": {
          "id": ...,
          "latitude": float, "longitude": float,
          "rsrp": float,
          "sector_name": "<enodebname>_<suffix>"   ← enodebname maps to a USID
        },
        "sinr": float,
        "throughput": float,
        "top_1": {"id": ..., "latitude": float, "longitude": float,
                  "rsrp": float, "sector_name": ...},
        "top_2": {...},
        "top_3": {...}
      },
      "latitude": float,
      "longitude": float
    },
    ...
  ]}

All pixels in a USID subfolder have that USID's cells as the serving cell.
top_1 / top_2 / top_3 are backup candidates ranked by RSRP.

USID mapping
------------
sector_name = "<enodebname>_<suffix>".  Strip the last "_suffix" to get the eNodeB name.
An enodeb→USID CSV (two columns: enodeb_name, usid) maps each eNodeB to its USID.
Pass enodeb_csv=None to skip mapping (raw eNodeB names will be used as IDs).

Simulation logic — Case A (all affected pixels)
-------------------------------------------------
All pixels in a USID folder have that USID as dominant, so every affected pixel
is Case A: R0 (dominant) goes down and the serving cell switches to rank-2 (top_1).

Post-outage signal is estimated per pixel from the pre-outage measurements using
a physical interference model:

  P1 = dominant RSRP  (R0, the cell going down)
  P2 = backup1 RSRP   (new serving; top_1)
  P3 = backup2 RSRP   (2nd strongest interferer; top_2)
  P4 = backup3 RSRP   (3rd strongest interferer; top_3)

  N_eff   = P1_lin / SINR_before_lin - P3_lin - P4_lin   (noise + other interference)
  SINR_after_lin = P2_lin / (P3_lin + P4_lin + N_eff)
  RSSI_before    = N_RB * P1_lin / RSRQ_before_lin
  RSSI_after     = RSSI_before - 12 * N_RB * P1_lin      (remove R0's subcarrier power)
  RSRQ_after_lin = N_RB * P2_lin / RSSI_after
  tput_after     = ALPHA * B_HZ * log2(1 + SINR_after_lin) / 1e6  [Mbps]

Fallback when no valid backup exists: RSRP=-120, SINR=-20, RSRQ=-20, tput=0.

Modelling assumptions
---------------------
  - N_RB   = 100       (20 MHz LTE; update if deployment uses a different bandwidth)
  - ALPHA  = 0.6       (Shannon efficiency factor, per 3GPP TR 36.942)
  - B_HZ   = 20e6      (system bandwidth in Hz; matches N_RB = 100)
  - Full PRB utilisation assumed for RSSI (occupancy ρ = 1)
  - All affected pixels treated as Case A (dominant → rank-2 handover)

No LLM calls are made.
"""

import csv
import json
import os
from collections import Counter
from math import log2, log10
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_FLOOR_RSRP = -120.0
_FLOOR_SINR =  -20.0
_FLOOR_RSRQ =  -20.0
_HOLE_RSRP_THRESHOLD = -110.0

# LTE physical-layer parameters — update N_RB and B_HZ together if the
# deployment uses a bandwidth other than 20 MHz.
N_RB  = 100    # number of resource blocks (20 MHz LTE)
ALPHA = 0.6    # Shannon efficiency factor (3GPP TR 36.942)
B_HZ  = 20e6   # system bandwidth in Hz (20 MHz)


# ---------------------------------------------------------------------------
# eNodeB / USID mapping
# ---------------------------------------------------------------------------
def _extract_enodeb(sector_name: str) -> str:
    """Strip the trailing '_<suffix>' from a sector_name to get the eNodeB name."""
    if not sector_name:
        return sector_name
    parts = sector_name.rsplit("_", 1)
    return parts[0] if len(parts) == 2 else sector_name


def load_enodeb_usid_map(csv_path: str) -> dict[str, str]:
    """
    Load eNodeB→USID mapping from a CSV file.
    The CSV must have at least two columns named 'enodeb_name' and 'usid'.
    """
    mapping: dict[str, str] = {}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            enodeb = row["enodeb_name"].strip()
            usid   = row["usid"].strip()
            if enodeb:
                mapping[enodeb] = usid
    return mapping


def _sector_to_usid(
    sector_name: str,
    enodeb_map: dict[str, str],
    unknown_enodebs: set,
) -> str:
    """
    Map a sector_name to a USID.
    Falls back to the raw eNodeB name if the mapping is missing, and records it.
    """
    enodeb = _extract_enodeb(sector_name)
    usid   = enodeb_map.get(enodeb)
    if usid is None and enodeb:
        unknown_enodebs.add(enodeb)
        usid = enodeb          # use eNodeB name as a stand-in USID
    return usid or sector_name


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_pixels_from_folder(
    usid_folder: str,
    enodeb_map: dict[str, str],
) -> tuple[list, set]:
    """
    Read all JSONL files in usid_folder and build an internal pixel list.

    Each pixel mirrors the schema used by coverage_preprocessing.py:
      {
        "lat": float, "lon": float,
        "info": {
          "dominant": {"ID": str, "lat": float, "lon": float, "rsrp": float,
                       "sector_name": str},
          "backup1": {...} | None,
          "backup2": {...} | None,
          "backup3": {...} | None,
          "sinr_db": float,
          "throughput_mbps": float,
          "rsrq_db": float,
        }
      }

    Returns
    -------
    pixels         : list of pixel dicts
    unknown_enodebs: set of eNodeB names not present in enodeb_map
    """
    pixels: list = []
    unknown_enodebs: set = set()

    folder = Path(usid_folder)
    files  = sorted(folder.glob("*.jsonl")) + sorted(folder.glob("*.json"))

    for fpath in files:
        with open(fpath, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                for entries in record.values():
                    for entry in (entries if isinstance(entries, list) else []):
                        lat = entry.get("latitude")
                        lon = entry.get("longitude")
                        if lat is None or lon is None:
                            continue

                        info    = entry.get("info", {})
                        serving = info.get("serving", {})

                        serving_sector = serving.get("sector_name", "")
                        serving_usid   = _sector_to_usid(serving_sector, enodeb_map, unknown_enodebs)

                        dominant = {
                            "ID":          serving_usid,
                            "lat":         serving.get("latitude"),
                            "lon":         serving.get("longitude"),
                            "rsrp":        serving.get("rsrp", _FLOOR_RSRP),
                            "sector_name": serving_sector,
                        }

                        backups: list = []
                        for key in ("top_1", "top_2", "top_3"):
                            top = info.get(key)
                            if not top:
                                break
                            top_sector = top.get("sector_name", "")
                            top_usid   = _sector_to_usid(top_sector, enodeb_map, unknown_enodebs)
                            backups.append({
                                "ID":          top_usid,
                                "lat":         top.get("latitude"),
                                "lon":         top.get("longitude"),
                                "rsrp":        top.get("rsrp", _FLOOR_RSRP),
                                "sector_name": top_sector,
                            })

                        pixels.append({
                            "lat": lat,
                            "lon": lon,
                            "info": {
                                "dominant":        dominant,
                                "backup1":         backups[0] if len(backups) > 0 else None,
                                "backup2":         backups[1] if len(backups) > 1 else None,
                                "backup3":         backups[2] if len(backups) > 2 else None,
                                "sinr_db":         info.get("sinr", _FLOOR_SINR),
                                "throughput_mbps": info.get("throughput", 0.0),
                                "rsrq_db":         info.get("rsrq", _FLOOR_RSRQ),
                            },
                        })

    return pixels, unknown_enodebs


# ---------------------------------------------------------------------------
# Affected-cell helpers
# ---------------------------------------------------------------------------
def _is_backup_affected(
    backup: Optional[dict],
    target_usid: str,
    affected_sectors: Optional[list],
) -> bool:
    """Return True if a backup cell is itself part of the outage."""
    if backup is None:
        return False
    if affected_sectors is None:
        return backup["ID"] == target_usid
    return backup.get("sector_name", "") in affected_sectors


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------
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
# Public utility: enumerate unique eNodeBs across all files of a USID folder
# ---------------------------------------------------------------------------
def get_unique_enodebs_for_usid(usid_folder: str) -> set[str]:
    """
    Scan all JSONL files in a USID folder and return every unique eNodeB name
    found in serving / top_1 / top_2 / top_3 sector_name fields.

    Use this output to build the enodeb→USID CSV mapping.
    """
    enodebs: set = set()
    folder  = Path(usid_folder)

    for fpath in sorted(folder.glob("*.jsonl")) + sorted(folder.glob("*.json")):
        with open(fpath, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for entries in record.values():
                    for entry in (entries if isinstance(entries, list) else []):
                        info = entry.get("info", {})
                        for key in ("serving", "top_1", "top_2", "top_3"):
                            cell = info.get(key)
                            if cell:
                                sn = cell.get("sector_name", "")
                                if sn:
                                    enodebs.add(_extract_enodeb(sn))

    return enodebs


def get_unique_enodebs_all(data_root: str) -> dict[str, set[str]]:
    """
    Scan all USID subfolders under data_root and return a dict:
      { usid_folder_name → set_of_enodeb_names }

    Also prints a combined sorted list of all unique eNodeB names across every folder,
    which you can use to populate the enodeb→USID CSV.
    """
    root    = Path(data_root)
    result  = {}
    all_ebs: set = set()

    for subdir in sorted(root.iterdir()):
        if subdir.is_dir():
            ebs = get_unique_enodebs_for_usid(str(subdir))
            result[subdir.name] = ebs
            all_ebs.update(ebs)

    print("=== All unique eNodeB names across every USID folder ===")
    for eb in sorted(all_ebs):
        print(f"  {eb}")
    print(f"Total: {len(all_ebs)} unique eNodeBs")

    return result


# ---------------------------------------------------------------------------
# Public helper: get neighbor USIDs
# ---------------------------------------------------------------------------
def get_neighbor_usids(
    data_root: str,
    target_usid: str,
    enodeb_map: dict[str, str],
) -> list[str]:
    """
    Return backup USIDs that absorb signal for >5 % of target's affected pixels.
    Call this before run_coverage_preprocessing_new to identify neighbours whose
    KPI history needs to be pulled.
    """
    usid_folder = Path(data_root) / target_usid
    pixels, _   = load_pixels_from_folder(str(usid_folder), enodeb_map)

    threshold = 0.05 * len(pixels)
    counts: Counter = Counter()
    for p in pixels:
        for key in ("backup1", "backup2", "backup3"):
            cell = p["info"].get(key)
            if cell and cell.get("ID"):
                counts[cell["ID"]] += 1

    return [usid for usid, cnt in counts.items() if cnt > threshold]


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------
def run_coverage_preprocessing_new(
    data_root: str,
    target_usid: str,
    enodeb_csv: Optional[str],
    affected_sectors: Optional[list[str]],
    output_dir: str,
) -> dict:
    """
    Run deterministic coverage impact analysis for a base station outage using
    the new JSONL per-USID input format.

    Parameters
    ----------
    data_root:        Root directory whose subdirectories are named by USID.
    target_usid:      The USID to analyse (must match a subdirectory name).
    enodeb_csv:       Path to CSV with columns [enodeb_name, usid].
                      Pass None to run without mapping (raw eNodeB names used as IDs).
    affected_sectors: None  → full outage (all pixels in folder are affected).
                      list  → partial outage; each element is a sector_name string
                              whose pixels are affected.
    output_dir:       Directory where PNG maps are written (created if absent).

    Returns
    -------
    dict with keys:
      signal_statistics, coverage_hole, per_backup, geographic, map_paths,
      unique_enodebs (sorted list of all eNodeBs seen),
      unknown_enodebs (eNodeBs not found in enodeb_csv — need CSV entries).
    """
    os.makedirs(output_dir, exist_ok=True)

    # Load enodeb→USID mapping
    enodeb_map: dict[str, str] = {}
    if enodeb_csv and os.path.exists(enodeb_csv):
        enodeb_map = load_enodeb_usid_map(enodeb_csv)

    # Load pixels from the target USID folder
    usid_folder = Path(data_root) / target_usid
    if not usid_folder.exists():
        raise FileNotFoundError(f"USID folder not found: {usid_folder}")

    pixels, unknown_enodebs = load_pixels_from_folder(str(usid_folder), enodeb_map)
    if not pixels:
        raise ValueError(f"No pixels loaded from {usid_folder}. Check folder contents.")

    # Collect all unique eNodeBs for reporting
    all_enodebs: set = set()
    for p in pixels:
        for key in ("dominant", "backup1", "backup2", "backup3"):
            cell = p["info"].get(key)
            if cell:
                sn = cell.get("sector_name", "")
                if sn:
                    all_enodebs.add(_extract_enodeb(sn))

    # ------------------------------------------------------------------
    # 1. Classify affected pixels
    # ------------------------------------------------------------------
    if affected_sectors is None:
        # Full outage: every pixel in the folder is affected
        affected_rows = pixels
    else:
        # Partial outage: only pixels served by a listed sector_name
        affected_rows = [
            p for p in pixels
            if p["info"]["dominant"].get("sector_name", "") in affected_sectors
        ]

    total_count    = len(pixels)
    affected_count = len(affected_rows)

    if affected_count == 0:
        raise ValueError(
            "No affected pixels found. "
            "Check that target_usid matches the folder name or that affected_sectors "
            "contains valid sector_name values."
        )

    # ------------------------------------------------------------------
    # 2. Simulate post-outage signal for each affected pixel (Case A)
    # All pixels have target as dominant, so every pixel is Case A:
    # serving switches from R0 (dominant) to rank-2 (backup1 / top_1).
    # ------------------------------------------------------------------
    records = []
    for p in affected_rows:
        info = p["info"]
        dom  = info["dominant"]
        b2   = info.get("backup2")   # P3 — 2nd-strongest interferer
        b3   = info.get("backup3")   # P4 — 3rd-strongest interferer

        P1          = dom["rsrp"]
        sinr_before = info["sinr_db"]
        rsrq_before = info["rsrq_db"]
        tput_before = info["throughput_mbps"]

        # Select first valid (non-affected) backup: top_1 → top_2 → top_3
        backup = None
        for key in ("backup1", "backup2", "backup3"):
            candidate = info.get(key)
            if candidate and not _is_backup_affected(candidate, target_usid, affected_sectors):
                backup = candidate
                break

        # Step 1 — effective noise + other-interference floor (derived from
        # pre-outage measurement; P3/P4 are the two strongest co-channel
        # interferers visible before the outage).
        SINR_before_lin = 10.0 ** (sinr_before / 10.0)
        P1_lin          = 10.0 ** (P1 / 10.0)
        P3_lin          = 10.0 ** (b2["rsrp"] / 10.0) if b2 else 0.0
        P4_lin          = 10.0 ** (b3["rsrp"] / 10.0) if b3 else 0.0
        N_eff           = max(P1_lin / SINR_before_lin - P3_lin - P4_lin, 1e-12)

        # Step 2 — RSRP after outage
        if backup is not None:
            rsrp_after = backup["rsrp"]
            P2_lin     = 10.0 ** (rsrp_after / 10.0)
        else:
            rsrp_after = _FLOOR_RSRP
            P2_lin     = None

        # Step 3 — SINR after (Case A: new serving = P2, interferers = P3 + P4)
        if backup is not None:
            SINR_after_lin = P2_lin / (P3_lin + P4_lin + N_eff)
            sinr_after     = 10.0 * log10(SINR_after_lin)
        else:
            SINR_after_lin = 10.0 ** (_FLOOR_SINR / 10.0)
            sinr_after     = _FLOOR_SINR

        # Step 4 — RSSI before and after (full-load, ρ = 1 assumed)
        RSRQ_before_lin = 10.0 ** (rsrq_before / 10.0)
        if backup is not None:
            RSSI_before = N_RB * P1_lin / RSRQ_before_lin
            # Remove R0's per-subcarrier power over all N_RB * 12 REs
            RSSI_after  = max(RSSI_before - 12.0 * N_RB * P1_lin, 1e-12)
        else:
            RSSI_after  = 1e-12

        # Step 5 — RSRQ after (Case A)
        if backup is not None:
            RSRQ_after_lin = N_RB * P2_lin / RSSI_after
            rsrq_after     = 10.0 * log10(RSRQ_after_lin)
        else:
            rsrq_after = _FLOOR_RSRQ

        # Step 6 — Throughput after (Shannon upper bound)
        if backup is not None:
            tput_after = ALPHA * B_HZ * log2(1.0 + SINR_after_lin) / 1e6
        else:
            tput_after = 0.0

        backup_usid = backup["ID"] if backup is not None else None
        dom_after   = backup_usid  if backup is not None else "NO_SIGNAL"

        records.append({
            "lat":          p["lat"],
            "lon":          p["lon"],
            "rsrp_before":  P1,
            "rsrp_after":   rsrp_after,
            "sinr_before":  sinr_before,
            "sinr_after":   sinr_after,
            "rsrq_before":  rsrq_before,
            "rsrq_after":   rsrq_after,
            "tput_before":  tput_before,
            "tput_after":   tput_after,
            "backup_usid":  backup_usid,
            "dom_before":   dom["ID"],
            "dom_after":    dom_after,
        })

    # Numpy arrays for vectorised statistics
    lats   = np.array([r["lat"]         for r in records])
    lons   = np.array([r["lon"]         for r in records])
    rsrp_b = np.array([r["rsrp_before"] for r in records])
    rsrp_a = np.array([r["rsrp_after"]  for r in records])
    rsrp_d = rsrp_b - rsrp_a
    sinr_b = np.array([r["sinr_before"] for r in records])
    sinr_a = np.array([r["sinr_after"]  for r in records])
    sinr_d = sinr_b - sinr_a
    rsrq_b = np.array([r["rsrq_before"] for r in records])
    rsrq_a = np.array([r["rsrq_after"]  for r in records])
    rsrq_d = rsrq_b - rsrq_a
    tput_b = np.array([r["tput_before"] for r in records])
    tput_a = np.array([r["tput_after"]  for r in records])
    tput_d = tput_b - tput_a

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
    hole_mask   = rsrp_a < _HOLE_RSRP_THRESHOLD
    hole_count  = int(np.sum(hole_mask))
    hole_coords = [
        {"lat": r["lat"], "lon": r["lon"]}
        for r, is_hole in zip(records, hole_mask)
        if is_hole
    ]

    coverage_hole = {
        "coverage_hole_count":       hole_count,
        "coverage_hole_fraction":    hole_count / affected_count if affected_count > 0 else 0.0,
        "coverage_hole_coords":      hole_coords,
        "affected_coordinate_count": affected_count,
        "total_coordinate_count":    total_count,
    }

    # ------------------------------------------------------------------
    # 5. Per-backup statistics
    # Note: existing_dominant_count is omitted here because the new format
    # only loads the target USID's folder. To compute it, call
    # get_unique_enodebs_all() and load backup folders separately.
    # ------------------------------------------------------------------
    absorbed_counts: dict = {}
    absorbed_rsrp:   dict = {}
    for r in records:
        bu = r["backup_usid"]
        if bu is None:
            continue
        absorbed_counts[bu] = absorbed_counts.get(bu, 0) + 1
        absorbed_rsrp.setdefault(bu, []).append(r["rsrp_after"])

    per_backup: dict = {}
    for bu, cnt in absorbed_counts.items():
        rsrp_arr = np.array(absorbed_rsrp[bu])
        per_backup[bu] = {
            "newly_absorbed_count":    cnt,
            "newly_absorbed_fraction": cnt / affected_count if affected_count > 0 else 0.0,
            "rsrp_in_absorbed_area":   _stats3(rsrp_arr),
        }

    # ------------------------------------------------------------------
    # 6. Geographic
    # ------------------------------------------------------------------
    centroid_lat = float(np.mean(lats)) if affected_count > 0 else 0.0
    centroid_lon = float(np.mean(lons)) if affected_count > 0 else 0.0

    geographic = {
        "centroid": {"lat": centroid_lat, "lon": centroid_lon},
    }

    # ------------------------------------------------------------------
    # 7. Maps
    # ------------------------------------------------------------------
    map_paths = _generate_maps(
        records=records,
        lats=lats, lons=lons,
        rsrp_d=rsrp_d, sinr_d=sinr_d, tput_d=tput_d,
        hole_mask=hole_mask,
        output_dir=output_dir,
    )

    # ------------------------------------------------------------------
    # 8. Print unknown eNodeBs so the user can fill in the CSV
    # ------------------------------------------------------------------
    if unknown_enodebs:
        print("\n=== eNodeBs not found in enodeb_csv (add them to the CSV) ===")
        for eb in sorted(unknown_enodebs):
            print(f"  {eb}")

    return {
        "signal_statistics": signal_statistics,
        "coverage_hole":     coverage_hole,
        "per_backup":        per_backup,
        "geographic":        geographic,
        "map_paths":         map_paths,
        "unique_enodebs":    sorted(all_enodebs),
        "unknown_enodebs":   sorted(unknown_enodebs),
    }


# ---------------------------------------------------------------------------
# Map generation (identical to coverage_preprocessing.py)
# ---------------------------------------------------------------------------
def _scatter_heatmap(lons, lats, values, title, cbar_label, path):
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
    records, lats, lons,
    rsrp_d, sinr_d, tput_d,
    hole_mask,
    output_dir,
) -> dict:
    map_paths: dict = {}

    # Map 1: RSRP drop
    path = os.path.join(output_dir, "rsrp_drop_heatmap.png")
    _scatter_heatmap(lons, lats, rsrp_d,
                     "RSRP Drop (dB) after Outage", "RSRP Drop (dB)", path)
    map_paths["rsrp_drop"] = path

    # Map 2: SINR drop
    path = os.path.join(output_dir, "sinr_drop_heatmap.png")
    _scatter_heatmap(lons, lats, sinr_d,
                     "SINR Drop (dB) after Outage", "SINR Drop (dB)", path)
    map_paths["sinr_drop"] = path

    # Map 3: Throughput drop
    path = os.path.join(output_dir, "throughput_drop_heatmap.png")
    _scatter_heatmap(lons, lats, tput_d,
                     "Throughput Drop (Mbps) after Outage", "Throughput Drop (Mbps)", path)
    map_paths["throughput_drop"] = path

    # Map 4: Dominant site before / after
    path = os.path.join(output_dir, "dominant_site_before_after.png")
    dom_before = [r["dom_before"] for r in records]
    dom_after  = [r["dom_after"]  for r in records]
    all_sites  = sorted(set(dom_before) | set(dom_after))

    cmap_tab   = plt.get_cmap("tab20")
    site_color = {s: cmap_tab(i % 20) for i, s in enumerate(all_sites)}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    for site in all_sites:
        mask = np.array([d == site for d in dom_before])
        if mask.any():
            ax1.scatter(lons[mask], lats[mask], c=[site_color[site]], s=12, label=site)
    ax1.set_title("Dominant Site — Before Outage")
    ax1.set_xlabel("Longitude")
    ax1.set_ylabel("Latitude")

    for site in all_sites:
        mask = np.array([d == site for d in dom_after])
        if mask.any():
            ax2.scatter(lons[mask], lats[mask], c=[site_color[site]], s=12, label=site)
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

    # Map 5: Coverage hole overlay
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
    ax.legend(handles=legend_patches, loc="upper right", fontsize=8)
    ax.set_title("Coverage Hole Overlay")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    map_paths["coverage_hole_overlay"] = path

    return map_paths


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Coverage impact analysis — new JSONL input format."
    )
    parser.add_argument("--data-root",   required=True,
                        help="Root directory containing USID-named subfolders.")
    parser.add_argument("--usid",        required=True,
                        help="Target USID (must match a subfolder name).")
    parser.add_argument("--enodeb-csv",  default=None,
                        help="CSV with columns [enodeb_name, usid]. Omit to skip mapping.")
    parser.add_argument("--output-dir",  default="./coverage_output",
                        help="Directory for output maps.")
    parser.add_argument("--list-enodebs", action="store_true",
                        help="Only list unique eNodeBs in the USID folder and exit.")
    parser.add_argument("--list-all-enodebs", action="store_true",
                        help="List unique eNodeBs across ALL USID folders and exit.")
    args = parser.parse_args()

    if args.list_all_enodebs:
        enodeb_report = get_unique_enodebs_all(args.data_root)
        out_path = os.path.join(args.output_dir, "all_enodebs.json")
        os.makedirs(args.output_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump({k: sorted(v) for k, v in enodeb_report.items()}, fh, indent=2)
        print(f"Saved to {out_path}")
    elif args.list_enodebs:
        ebs = get_unique_enodebs_for_usid(
            str(Path(args.data_root) / args.usid)
        )
        out_path = os.path.join(args.output_dir, f"{args.usid}_enodebs.json")
        os.makedirs(args.output_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump({"usid": args.usid, "enodebs": sorted(ebs)}, fh, indent=2)
        print(f"Saved to {out_path}")
    else:
        result = run_coverage_preprocessing_new(
            data_root=args.data_root,
            target_usid=args.usid,
            enodeb_csv=args.enodeb_csv,
            affected_sectors=None,
            output_dir=args.output_dir,
        )
        output = {
            "signal_statistics": result["signal_statistics"],
            "coverage_hole":     {k: v for k, v in result["coverage_hole"].items()
                                  if k != "coverage_hole_coords"},
            "coverage_hole_coords": result["coverage_hole"]["coverage_hole_coords"],
            "per_backup":        result["per_backup"],
            "geographic":        result["geographic"],
            "map_paths":         result["map_paths"],
            "unique_enodebs":    result["unique_enodebs"],
            "unknown_enodebs":   result["unknown_enodebs"],
        }
        out_path = os.path.join(args.output_dir, f"{args.usid}_coverage_result.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(output, fh, indent=2)
        print(f"Saved to {out_path}")
