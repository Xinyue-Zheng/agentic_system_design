"""
find_overlapping_enodebs.py

Adaptively scan a target eNodeB's coverage and return every other eNodeB that
overlaps it -- i.e. every neighbour eNodeB that shows up on the coordinates the
target actually serves.

This module reuses objects that already exist in your project:
    adaptive_coverage_scan  -- the adaptive coverage scanner
    make_probe              -- builds the probe callback used by the scanner
    grab_url                -- fetches the raw measurement object for a point
Adjust the import below to point at wherever they live.
"""

import re

# from your_project import adaptive_coverage_scan, make_probe, grab_url


def enb_of_cell(cell_name):
    """Return the eNodeB id of a cell.

    A cell/sector name encodes its eNodeB as the part before its first
    separator, e.g. "123456-7" or "123456_7" -> "123456".
    """
    if not cell_name:
        return None
    # Split on the first '-' or '_' so either naming convention works.
    return re.split(r"[-_]", str(cell_name), maxsplit=1)[0]


def find_overlapping_enodebs(target_enb, latitude, longitude):
    """Find all neighbour eNodeBs overlapping the target eNodeB's serving area.

    Args:
        target_enb: the target eNodeB id.
        latitude:   latitude of the target site / scan centre.
        longitude:  longitude of the target site / scan centre.

    Returns:
        A sorted list of neighbour eNodeB ids (the target itself excluded).
    """
    target_enb = str(target_enb)

    # Run the adaptive coverage scan around the target site.
    probe = make_probe(target_enb, grab_url, enb_of_cell)
    result = adaptive_coverage_scan(target_enb, latitude, longitude, probe)

    # Walk only the coordinates the target actually serves, and collect every
    # other eNodeB that appears there (serving cell + all topN neighbour cells).
    neighbour_enbs = set()
    for point in result["points"]:
        if not point.get("is_self"):
            continue  # skip coordinates not served by the target eNodeB
        for record in point.get("raw", {}).get("array", []):
            info = record.get("info", {})
            for cell in info.values():
                if not isinstance(cell, dict):
                    continue  # scalar fields (rsrp, sinr, ...) are not cells
                nb_enb = enb_of_cell(cell.get("sector_name"))
                if nb_enb and nb_enb != target_enb:
                    neighbour_enbs.add(nb_enb)

    neighbour_enbs = sorted(neighbour_enbs)
    print(f"Target eNodeB {target_enb}: "
          f"{len(neighbour_enbs)} overlapping neighbour eNodeB(s) found")
    return neighbour_enbs
