import numpy as np
import pandas as pd


def build_lookup_inputs(row, id_col="ID", neighbors_col="nearest_ids",
                        start_col="start_time", end_col="end_time", weeks=4):
    """Build the lookup inputs for one selected case (one row).

    Returns a tuple (id_list, window_start, window_end):
        id_list      -> [own_id, *nearest_20_ids]  (own id first, duplicates removed)
        window_start -> start_time minus `weeks` weeks, as a pandas Timestamp
        window_end   -> end_time, as a pandas Timestamp

    Feed id_list + (window_start, window_end) into your own dataframe-b lookup function.
    """
    own_id = row[id_col]

    neighbors = row[neighbors_col]
    if isinstance(neighbors, (list, tuple, np.ndarray, pd.Series)):
        neighbors = list(neighbors)
    else:                                  # NaN / None when no neighbors were found
        neighbors = []

    # own id first, then neighbors, dropping any repeat of own id, keeping order
    id_list = [own_id] + [i for i in neighbors if i != own_id]

    start = pd.Timestamp(row[start_col])
    end = pd.Timestamp(row[end_col])
    window_start = start - pd.Timedelta(weeks=weeks)
    window_end = end

    return id_list, window_start, window_end


def add_lookup_inputs(df, id_col="ID", neighbors_col="nearest_ids",
                      start_col="start_time", end_col="end_time", weeks=4):
    """Apply build_lookup_inputs to every row and attach the results as columns.

    Adds: 'lookup_ids', 'window_start', 'window_end'.
    """
    res = df.apply(
        lambda r: build_lookup_inputs(r, id_col, neighbors_col, start_col, end_col, weeks),
        axis=1, result_type="expand",
    )
    df = df.copy()
    df["lookup_ids"] = res[0]
    df["window_start"] = res[1]
    df["window_end"] = res[2]
    return df


if __name__ == "__main__":
    selected = pd.DataFrame({
        "ID": ["loc0", "loc5"],
        "nearest_ids": [["loc3", "loc7", "loc1"], ["loc2", "loc9"]],
        "start_time": pd.to_datetime(["2026-03-10 09:00", "2026-04-01 23:00"]),
        "end_time":   pd.to_datetime(["2026-03-10 11:00", "2026-04-02 02:00"]),
    })

    # single-row use
    ids, w_start, w_end = build_lookup_inputs(selected.iloc[0])
    print("id_list     :", ids)
    print("window_start:", w_start, "(start - 4 weeks)")
    print("window_end  :", w_end)
    print()

    # whole-dataframe use
    print(add_lookup_inputs(selected).to_string())
