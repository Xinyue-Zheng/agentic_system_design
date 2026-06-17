import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

EARTH_RADIUS_KM = 6371.0


def attach_nearest_ids(a, b, k=20, id_col="ID", lat_col="latitude", lon_col="longitude"):
    """For every ID in b, find the k geographically nearest *other* IDs from a.

    a : DataFrame with id_col, lat_col, lon_col (duplicate IDs allowed; they must
        share the same coordinates -- only the first occurrence is kept).
    b : DataFrame with id_col. Each ID is looked up in a to get its location.

    Returns a copy of b with two extra columns:
        nearest_ids     -> list of up to k nearest other IDs, nearest first
        nearest_dist_km -> matching great-circle distances in km
    IDs in b that are not present in a get None.
    """
    # Unique location table from a.
    locs = a.drop_duplicates(id_col)[[id_col, lat_col, lon_col]].reset_index(drop=True)
    ids = locs[id_col].to_numpy()
    coords = np.radians(locs[[lat_col, lon_col]].to_numpy())   # haversine wants radians
    id_to_pos = {i: p for p, i in enumerate(ids)}

    tree = BallTree(coords, metric="haversine")

    # Query once for all unique, resolvable IDs in b.
    b_ids = pd.unique(b[id_col])
    valid = [i for i in b_ids if i in id_to_pos]
    result = {}
    if valid:
        positions = [id_to_pos[i] for i in valid]
        kq = min(k + 1, len(ids))                              # +1 because self is included
        dist, idx = tree.query(coords[positions], k=kq)
        for bid, self_pos, d_row, idx_row in zip(valid, positions, dist, idx):
            keep = idx_row != self_pos                         # drop the point itself
            near_idx = idx_row[keep][:k]
            near_dist = d_row[keep][:k] * EARTH_RADIUS_KM
            result[bid] = (ids[near_idx].tolist(), np.round(near_dist, 3).tolist())

    b = b.copy()
    b["nearest_ids"] = b[id_col].map(lambda i: result.get(i, (None, None))[0])
    b["nearest_dist_km"] = b[id_col].map(lambda i: result.get(i, (None, None))[1])
    return b


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    a = pd.DataFrame({
        "ID": [f"loc{i}" for i in range(30)],
        "latitude": 40.7 + rng.normal(0, 0.1, 30),
        "longitude": -74.0 + rng.normal(0, 0.1, 30),
    })
    a = pd.concat([a, a.head(3)], ignore_index=True)           # add duplicate IDs
    b = pd.DataFrame({"ID": ["loc0", "loc5", "loc0", "missing_id"]})

    out = attach_nearest_ids(a, b, k=20)
    for _, row in out.iterrows():
        ids = row["nearest_ids"]
        print(row["ID"], "->", "not found" if not isinstance(ids, list) else f"{len(ids)} ids, first 3: {ids[:3]}, dist[0]={row['nearest_dist_km'][0]}km")
