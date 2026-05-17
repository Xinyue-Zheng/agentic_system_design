from __future__ import annotations

"""
Attribute preprocessing: derives capacity, tower, and technology metrics
for a target site and its backup sites from the usid_attributes CSV.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CSV_PATH = Path(__file__).parent.parent.parent / "version_3" / "data" / "usid_attributes.csv"

_BAND_COLUMNS = ["Band_700_cells", "Band_1800_cells", "Band_2600_cells", "Band_3500_cells"]
_BAND_LABELS   = ["Band_700",       "Band_1800",       "Band_2600",       "Band_3500"]


def _load_table() -> pd.DataFrame:
    df = pd.read_csv(_CSV_PATH)
    df = df.set_index("USID")
    return df


def _tower_type(height_m: float) -> str:
    if height_m < 25:
        return "micro"
    if height_m <= 45:
        return "macro"
    return "tall_macro"


def _capacity_score(row: pd.Series, active_bands: list) -> float:
    """
    capacity_score = (4g_cells * 1.0 + 5g_cells * 2.0) * (1 + 0.15 * len(active_bands))

    NOTE: Cell-count multipliers (1.0 for 4G, 2.0 for 5G) and the band-diversity
    factor (0.15 per active band) are rough engineering estimates; they have no
    normative source.
    """
    raw = row["4G_cells"] * 1.0 + row["5G_cells"] * 2.0
    return raw * (1 + 0.15 * len(active_bands))


def _site_base_fields(row: pd.Series) -> dict:
    active_bands = [
        label
        for col, label in zip(_BAND_COLUMNS, _BAND_LABELS)
        if row[col] > 0
    ]
    height = float(row["Tower_height_m"])
    score  = _capacity_score(row, active_bands)
    return {
        "4g_cell_count":  int(row["4G_cells"]),
        "5g_cell_count":  int(row["5G_cells"]),
        "active_bands":   active_bands,
        "tower_height_m": height,
        "tower_type":     _tower_type(height),
        "capacity_score": score,
    }


def _null_base_fields() -> dict:
    return {
        "4g_cell_count":  None,
        "5g_cell_count":  None,
        "active_bands":   None,
        "tower_height_m": None,
        "tower_type":     None,
        "capacity_score": None,
    }


def run_attribute_preprocessing(
    target_usid: str,
    backup_usids: list,
    per_backup_coverage: dict,
) -> dict:
    """
    Derive attribute-based metrics for a target site and its backup sites.

    Parameters
    ----------
    target_usid : str
        USID of the outage site.
    backup_usids : list[str]
        USIDs of candidate backup sites.
    per_backup_coverage : dict
        The ``per_backup`` sub-dict returned by coverage preprocessing,
        keyed by backup USID.  Each entry must contain
        ``newly_absorbed_fraction`` and ``existing_dominant_fraction``.

    Returns
    -------
    dict
        Keys: ``target``, ``per_backup``, ``tech_downgrade_affected_fraction``.
        Any USID absent from the CSV has all fields set to None.
    """
    table = _load_table()

    # --- target ---
    if target_usid in table.index:
        target_row    = table.loc[target_usid]
        target_fields = _site_base_fields(target_row)
        target_has_5g = target_fields["5g_cell_count"] > 0
    else:
        logger.warning("USID %s not found in attributes CSV (target)", target_usid)
        target_fields = _null_base_fields()
        target_has_5g = False  # treat as no-5G when unknown

    target_result = {"usid": target_usid, **target_fields}

    # --- backups ---
    per_backup_result: dict = {}
    total_absorbed      = 0.0
    downgrade_absorbed  = 0.0

    for usid in backup_usids:
        cov = per_backup_coverage.get(usid, {})
        newly_absorbed     = float(cov.get("newly_absorbed_fraction", 0.0))
        existing_dominant  = float(cov.get("existing_dominant_fraction", 0.0))

        if usid in table.index:
            row    = table.loc[usid]
            base   = _site_base_fields(row)
            score  = base["capacity_score"]

            has_5g = base["5g_cell_count"] > 0
            tech_downgrade = target_has_5g and not has_5g

            # load_pressure_ratio: spatial proxy only, not measured PRB utilization
            denom = score / 10.0
            load_pressure = (
                (existing_dominant + newly_absorbed) / denom
                if denom > 0
                else float("inf")
            )

            per_backup_result[usid] = {
                **base,
                "newly_absorbed_fraction":    newly_absorbed,
                "existing_dominant_fraction": existing_dominant,
                "load_pressure_ratio":        load_pressure,
                "has_5g":                     has_5g,
                "technology_downgrade":       tech_downgrade,
            }
        else:
            logger.warning("USID %s not found in attributes CSV (backup)", usid)
            per_backup_result[usid] = {
                **_null_base_fields(),
                "newly_absorbed_fraction":    newly_absorbed,
                "existing_dominant_fraction": existing_dominant,
                "load_pressure_ratio":        None,
                "has_5g":                     None,
                "technology_downgrade":       None,
            }
            tech_downgrade = False  # unknown — don't count against fraction

        total_absorbed     += newly_absorbed
        if tech_downgrade:
            downgrade_absorbed += newly_absorbed

    tech_downgrade_fraction = (
        downgrade_absorbed / total_absorbed if total_absorbed > 0 else 0.0
    )

    return {
        "target":                          target_result,
        "per_backup":                      per_backup_result,
        "tech_downgrade_affected_fraction": tech_downgrade_fraction,
    }
