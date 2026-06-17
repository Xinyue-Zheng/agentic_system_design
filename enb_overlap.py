"""
enb_overlap.py

Find the neighbour eNodeBs overlapping a target eNodeB's serving area.

The two pieces I sent earlier as fragments are now consolidated here and made
consistent with each other:
    enb_of_cell(...)              cell/sector name -> eNodeB id
    make_probe(...)              builds the probe(lat, lon) callback  (FIXED)
    find_overlapping_enodebs(...) the function you asked for

It still depends on objects that live in YOUR project. I did NOT rewrite these:
    adaptive_coverage_scan(...)  your adaptive scanner -- it was already correct,
                                 I only analysed it, so it stays as-is in your file
    grab_url(url)                fetches the raw measurement object
    km_to_dlat / km_to_dlon / approx_km / _metrics / _converged
                                 geo + metric helpers used INSIDE the scanner
                                 (never shown to me, so not reproduced here)
Adjust the import below to match where they live.
"""

import re

# from your_project import adaptive_coverage_scan, grab_url


def enb_of_cell(cell_name):
    """eNodeB id = the part of a cell/sector name before its first separator.

    e.g. "123456-7" or "123456_7" -> "123456". Returns None for empty input.
    This supersedes the old enb_of(): it splits on the first '-' OR '_'.
    """
    if not cell_name:
        return None
    return re.split(r"[-_]", str(cell_name), maxsplit=1)[0]


def make_probe(enb, grab_url, enb_of, contest_db=3.0):
    """Build the probe(lat, lon) callback used by adaptive_coverage_scan.

    `enb` is kept only so existing call sites don't break -- it is NOT used
    inside, because the scanner itself sets is_self by comparing served_by==enb.

    probe returns the flat dict the scanner expects:
        served_by : eNodeB serving this point, or None (coverage hole)
        contested : True when the two strongest cells are different eNodeBs
                    within `contest_db` dB of each other
        raw       : the full fetched object (kept for downstream neighbour use)
    """
    def probe(lat, lon):
        url = ""  # TODO: build the request URL from (lat, lon)
        obj = grab_url(url)
        arr = obj.get("array", [])
        if not arr:
            return {"served_by": None, "contested": False, "raw": obj}

        info = arr[0].get("info", {})

        # Serving cell -> who serves this point (None means a coverage hole).
        serving = info.get("serving") or {}
        served = enb_of(serving.get("sector_name"))

        # Strongest neighbour cells, used only for the contested flag.
        tops = [info.get(f"top_{k}") or {} for k in range(1, 5)]
        tops = [t for t in tops if t.get("sector_name")]

        contested = False
        if len(tops) >= 2 and tops[0].get("rsrp") is not None and tops[1].get("rsrp") is not None:
            contested = (
                enb_of(tops[0]["sector_name"]) != enb_of(tops[1]["sector_name"])
                and abs(tops[0]["rsrp"] - tops[1]["rsrp"]) <= contest_db
            )

        return {"served_by": served, "contested": contested, "raw": obj}

    return probe


def find_overlapping_enodebs(target_enb, latitude, longitude):
    """Adaptively scan the target eNodeB and return every other eNodeB that
    shows up on the coordinates the target actually serves.

    Args:
        target_enb: the target eNodeB id.
        latitude:   latitude of the target site / scan centre.
        longitude:  longitude of the target site / scan centre.

    Returns:
        A sorted list of neighbour eNodeB ids (the target itself excluded).
    """
    target_enb = str(target_enb)

    # Reuse your existing scanner + the fixed probe above.
    probe = make_probe(target_enb, grab_url, enb_of_cell)
    result = adaptive_coverage_scan(target_enb, latitude, longitude, probe)

    # Walk only the coordinates the target serves, and collect every other
    # eNodeB present there (serving cell + all topN neighbour cells).
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
