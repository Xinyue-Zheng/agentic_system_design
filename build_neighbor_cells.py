"""Build the set of cells affected by an outage: each down cell + its overlapping
neighbour cells.

This consumes an outage table (CSV) whose `down_cell_observed` column names the
cell that was switched off, and for every such cell calls the neighbour API to
find the cells whose coverage overlaps it. The neighbour API is queried by
cell name only (no dense coverage scanning needed), which is why this is cheap
enough to run over many outage cases.

Output:
    * an in-memory dict  {down_cell: [down_cell, *neighbour_cells]}
    * a tidy CSV         (down_cell, cell_name, role, overlap_pct, ...)

The real endpoint/URL is intentionally left as a TODO, exactly like
query_data.make_probe -- pass in a `grab_url(url) -> dict` callable and fill in
the URL builder.
"""

import csv

import pandas as pd

from query_data import enb_of_cell  # reused so neighbour eNodeBs are derivable


# --- neighbour API -----------------------------------------------------------

def _build_neighbor_url(cell_name, *, cut_off_threshold_db, min_rsrp_db,
                        sector_range, percentile_cut_off):
    """Construct the neighbour-API request URL from its parameters.

    Returns the URL string consumed by grab_url. Left as a TODO so the
    company-private base URL is never committed.
    """
    # TODO: build the real request URL, e.g.
    #   return (f"{BASE_URL}/neighbors?cell={cell_name}"
    #           f"&cut_off_threshold_db={cut_off_threshold_db}"
    #           f"&min_rsrp_db={min_rsrp_db}"
    #           f"&sector_range={sector_range}"
    #           f"&percentile_cut_off={percentile_cut_off}")
    raise NotImplementedError("fill in _build_neighbor_url for your endpoint")


def query_neighbors(cell_name, grab_url, *,
                    cut_off_threshold_db=3.0,
                    min_rsrp_db=-120.0,
                    sector_range=5.0,
                    percentile_cut_off=10):
    """Query the neighbour API for one cell and return parsed neighbour records.

    Each returned record is a flat dict:
        cell_name   : the neighbour's sector_name
        overlap_pct : overlap_region_percentage (coverage overlap with the down cell)
        avg_power   : overlap_region_avg_power_dBm
        latitude    : neighbour latitude
        longitude   : neighbour longitude
        state       : overlap_region_state
    Records are sorted by overlap_pct (descending) and the down cell itself is
    excluded if the API ever returns it.
    """
    url = _build_neighbor_url(
        cell_name,
        cut_off_threshold_db=cut_off_threshold_db,
        min_rsrp_db=min_rsrp_db,
        sector_range=sector_range,
        percentile_cut_off=percentile_cut_off,
    )
    obj = grab_url(url) or {}

    out = []
    seen = set()
    for nb in obj.get("neighbors", []):
        name = nb.get("sector_name")
        if not name or name == cell_name or name in seen:
            continue
        seen.add(name)
        out.append({
            "cell_name": name,
            "overlap_pct": nb.get("overlap_region_percentage"),
            "avg_power": nb.get("overlap_region_avg_power_dBm"),
            "latitude": nb.get("latitude"),
            "longitude": nb.get("longitude"),
            "state": nb.get("overlap_region_state"),
        })

    out.sort(key=lambda r: (r["overlap_pct"] is not None, r["overlap_pct"]),
             reverse=True)
    return out


# --- driver over the outage table -------------------------------------------

def build_affected_cells(outage_csv, grab_url, *,
                         down_cell_col="down_cell_observed",
                         out_csv="affected_cells.csv",
                         cut_off_threshold_db=3.0,
                         min_rsrp_db=-120.0,
                         sector_range=5.0,
                         percentile_cut_off=10):
    """For every down cell in the outage table, collect [down_cell, *neighbours].

    Returns:
        affected : {down_cell: [down_cell, *neighbour_cell_names]}
    Side effect:
        writes `out_csv` with one row per (down_cell, cell) pair, role marking
        which is the down cell vs a neighbour, plus the overlap fields.
    """
    df = pd.read_csv(outage_csv)
    if down_cell_col not in df.columns:
        raise KeyError(f"{down_cell_col!r} not in {outage_csv}; "
                       f"columns are {list(df.columns)}")

    # de-dupe down cells so we don't re-query the same cell across rows
    down_cells = [c for c in df[down_cell_col].dropna().astype(str).unique()]

    affected = {}
    rows = []
    for down_cell in down_cells:
        neighbours = query_neighbors(
            down_cell, grab_url,
            cut_off_threshold_db=cut_off_threshold_db,
            min_rsrp_db=min_rsrp_db,
            sector_range=sector_range,
            percentile_cut_off=percentile_cut_off,
        )

        affected[down_cell] = [down_cell] + [n["cell_name"] for n in neighbours]

        # the down cell itself
        rows.append({
            "down_cell": down_cell,
            "cell_name": down_cell,
            "role": "down",
            "enb": enb_of_cell(down_cell),
            "overlap_pct": None,
            "avg_power": None,
            "latitude": None,
            "longitude": None,
            "state": None,
        })
        # its neighbours
        for n in neighbours:
            rows.append({
                "down_cell": down_cell,
                "cell_name": n["cell_name"],
                "role": "neighbour",
                "enb": enb_of_cell(n["cell_name"]),
                "overlap_pct": n["overlap_pct"],
                "avg_power": n["avg_power"],
                "latitude": n["latitude"],
                "longitude": n["longitude"],
                "state": n["state"],
            })

        print(f"{down_cell}: {len(neighbours)} overlapping neighbour cell(s)")

    _write_csv(out_csv, rows)
    print(f"Wrote {len(rows)} rows for {len(affected)} down cell(s) -> {out_csv}")
    return affected


def _write_csv(path, rows):
    fields = ["down_cell", "cell_name", "role", "enb", "overlap_pct",
              "avg_power", "latitude", "longitude", "state"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    # from your_project import grab_url
    # affected = build_affected_cells("outages.csv", grab_url)
    # print(affected)
    pass
