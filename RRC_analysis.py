"""
outage_analysis.py

End-to-end, for a target eNodeB tied to an outage ticket:
  1. build the query window from the ticket (ALARM_TIME - 1 month .. RTS + 2 days)
  2. find the NEAREST k neighbour eNodeBs (haversine), with distances
  3. pull hourly RRC KPI for {target + neighbours} into ONE dataframe (saved),
     reusing YOUR Snowflake query script (private-key auth + RRC merge)
  4. fill missing hours with 0, compute rrc, find where rrc drops to 0 and when
  5. if the TARGET itself hit rrc=0, plot everyone into a folder named after the
     target, each neighbour annotated with its distance to the target

WHAT YOU NEED TO FILL / CHANGE
  - the CONFIG blocks below (column names, pull paths/proxy, RRC factor)
  - in YOUR query script, change `enb_list = []` to:
        enb_list = sys.argv[4].split(",")
    (it already takes argv[1]=outfile, [2]=start, [3]=end; we add [4]=enb list)
  - your Snowflake credentials stay INSIDE your query script (not needed here)
"""

import os
import subprocess
import tempfile
import numpy as np
import pandas as pd

# ---- CONFIG: KPI dataframe columns (match what your query script writes) ----
COL_TIME = "DATETIME"
COL_ENB  = "ENODEB"
COL_NUM  = "RRCConnUEsNum"
COL_DEN  = "RRCConnUEsDen"      # not used in rrc; kept for reference
RRC_FACTOR = 180.0             # rrc = num / RRC_FACTOR  (hourly data may want 720 - check)
FREQ = "1h"

# ---- CONFIG: locations table columns (eNodeB -> lat/lon). CONFIRM these. ----
LOC_ENB = "ENODEB"
LOC_LAT = "LATITUDE"
LOC_LON = "LONGITUDE"

# ---- CONFIG: the Snowflake pull (mirrors what your bash sets). FILL these. ----
QUERY_SCRIPT = "/path/to/your_query_script.py"   # the python script you showed me
PYTHON_BIN   = "python"                           # or your conda env's python
CA_BUNDLE    = "/path/to/your_cert.crt"           # REQUESTS_CA_BUNDLE (your .crt)
HTTPS_PROXY  = "http://your.proxy:port"           # https_proxy
# -----------------------------------------------------------------------------


# ============================== time window ==============================

def times_for_ticket(alarm_unix, rts_unix):
    """Build the query window from a ticket (unix seconds, e.g. 1700000000):
        start = ALARM_TIME        - 1 month
        end   = RETURN_TO_SERVICE + 2 days
    Returns (start_str, end_str) as 'YYYY-MM-DD HH:MM:SS' in UTC.
    """
    alarm = pd.to_datetime(int(alarm_unix), unit="s", utc=True)
    rts   = pd.to_datetime(int(rts_unix),   unit="s", utc=True)
    start = alarm - pd.DateOffset(months=1)
    end   = rts + pd.Timedelta(days=2)
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt)


# ============================== KPI pull ==============================

def pull_hourly_kpi(batch, start, end):
    """Run your query script for one batch of eNodeBs over [start, end] and read
    the CSV it writes back. Returns DATETIME, ENODEB, RRCConnUEsNum, RRCConnUEsDen.
    """
    enb_csv = ",".join(str(e) for e in batch)
    out = tempfile.NamedTemporaryFile(suffix=".csv", delete=False).name

    env = dict(os.environ)
    env["REQUESTS_CA_BUNDLE"] = CA_BUNDLE      # same cert your bash exports
    env["HTTPS_PROXY"] = HTTPS_PROXY           # same proxy your bash exports
    env["TZ"] = "UTC"

    # script args: outfile, start, end, enb_list (the argv[4] you add)
    subprocess.run([PYTHON_BIN, QUERY_SCRIPT, out, start, end, enb_csv],
                   env=env, check=True)

    df = pd.read_csv(out)
    os.remove(out)
    return df


def fetch_kpi(enodebs, start, end, batch_size=200, save_path=None):
    """Pull hourly RRC KPI for {target + neighbours} -> one dataframe, and save it.
    ids are batched into ONE IN-clause query per call (not one id at a time)."""
    enodebs = [str(e) for e in enodebs]
    frames = []
    for i in range(0, len(enodebs), batch_size):
        frames.append(pull_hourly_kpi(enodebs[i:i + batch_size], start, end))
    kpi_df = pd.concat(frames, ignore_index=True)
    if save_path:
        kpi_df.to_parquet(save_path)
        print(f"saved KPI dataframe -> {save_path}  "
              f"({len(kpi_df)} rows, {kpi_df[COL_ENB].nunique()} eNodeBs)")
    return kpi_df


# ============================== neighbours ==============================

def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. Accepts scalars or numpy arrays."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def get_neighbors(target_enb, locations_df, k=20):
    """Nearest k eNodeBs to the target by great-circle distance.
    Returns [ENODEB, distance_km] for the k closest (target excluded), nearest first.
    """
    target_enb = str(target_enb)
    loc = locations_df.copy()
    loc[LOC_ENB] = loc[LOC_ENB].astype(str)
    sites = loc.groupby(LOC_ENB)[[LOC_LAT, LOC_LON]].mean().reset_index()  # one point/eNodeB

    if target_enb not in set(sites[LOC_ENB]):
        raise ValueError(f"target {target_enb} not found in locations table")
    t = sites.loc[sites[LOC_ENB] == target_enb].iloc[0]

    others = sites[sites[LOC_ENB] != target_enb].copy()
    others["distance_km"] = haversine_km(t[LOC_LAT], t[LOC_LON],
                                         others[LOC_LAT].to_numpy(),
                                         others[LOC_LON].to_numpy())
    return (others.sort_values("distance_km")
                  .head(k)[[LOC_ENB, "distance_km"]]
                  .rename(columns={LOC_ENB: COL_ENB})
                  .reset_index(drop=True))


# ============================== rrc + down detection ==============================

def fill_gaps_with_zero(df, freq=FREQ):
    """For each eNodeB, put it on a regular `freq` grid (its own min..max) and
    fill the counter columns at the inserted time points with 0."""
    df = df.copy()
    df[COL_TIME] = pd.to_datetime(df[COL_TIME])
    out = []
    for enb, sub in df.groupby(COL_ENB):
        sub = sub.set_index(COL_TIME).sort_index()
        sub = sub.reindex(pd.date_range(sub.index.min(), sub.index.max(), freq=freq))
        sub[COL_ENB] = enb
        for c in (COL_NUM, COL_DEN):
            if c in sub.columns:
                sub[c] = sub[c].fillna(0)
        out.append(sub.rename_axis(COL_TIME).reset_index())
    return pd.concat(out, ignore_index=True)


def add_rrc(df):
    """Add rrc = num / RRC_FACTOR."""
    df = df.copy()
    df["rrc"] = df[COL_NUM] / RRC_FACTOR
    return df


def find_zero_intervals(df, window=None, zero_threshold=0.0, min_len=1):
    """For each eNodeB, find contiguous runs where rrc <= zero_threshold.
    window=(start, end) restricts the search. min_len = min consecutive points
    (hourly: hours). Returns ENODEB, start, end, n_points."""
    df = df.copy()
    df[COL_TIME] = pd.to_datetime(df[COL_TIME])
    if window is not None:
        s, e = pd.to_datetime(window[0]), pd.to_datetime(window[1])
        df = df[(df[COL_TIME] >= s) & (df[COL_TIME] <= e)]

    rows = []
    for enb, sub in df.groupby(COL_ENB):
        sub = sub.sort_values(COL_TIME)
        is_zero = (sub["rrc"] <= zero_threshold).to_numpy()
        times = sub[COL_TIME].to_numpy()
        i, n = 0, len(is_zero)
        while i < n:
            if is_zero[i]:
                j = i
                while j + 1 < n and is_zero[j + 1]:
                    j += 1
                if j - i + 1 >= min_len:
                    rows.append({COL_ENB: enb,
                                 "start": pd.Timestamp(times[i]),
                                 "end": pd.Timestamp(times[j]),
                                 "n_points": j - i + 1})
                i = j + 1
            else:
                i += 1
    return pd.DataFrame(rows, columns=[COL_ENB, "start", "end", "n_points"])


# ============================== plotting ==============================

def plot_target_and_neighbors(kpi_df, target_enb, neighbor_dist, window=None,
                              out_dir=None, highlight_color="tab:red",
                              highlight_alpha=0.15):
    """One RRC-vs-time chart per eNodeB into a folder named after the target.
    Neighbour titles annotated with distance to the target; window=(start, end)
    is shaded on every plot."""
    import matplotlib.pyplot as plt
    target_enb = str(target_enb)
    out_dir = out_dir or f"{target_enb}"
    os.makedirs(out_dir, exist_ok=True)

    df = add_rrc(kpi_df.copy())
    df[COL_TIME] = pd.to_datetime(df[COL_TIME])
    dist_map = dict(zip(neighbor_dist[COL_ENB].astype(str), neighbor_dist["distance_km"]))

    hl = None
    if window is not None:
        hl = (pd.to_datetime(window[0]).to_numpy(), pd.to_datetime(window[1]).to_numpy())

    enbs = sorted(df[COL_ENB].astype(str).unique())
    for enb in enbs:
        sub = df[df[COL_ENB].astype(str) == enb].sort_values(COL_TIME)

        if enb == target_enb:
            title = f"eNodeB {enb} (TARGET) - RRC vs time"
        else:
            d = dist_map.get(enb)
            tag = f"{d:.2f} km from target {target_enb}" if d is not None else f"neighbour of {target_enb}"
            title = f"eNodeB {enb} - {tag} - RRC vs time"

        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot(sub[COL_TIME].to_numpy(), sub["rrc"].to_numpy(), marker=".", linewidth=1)
        if hl is not None:
            ax.axvspan(hl[0], hl[1], color=highlight_color, alpha=highlight_alpha, label="window")
            ax.legend(loc="upper right", fontsize=8)
        ax.set_title(title)
        ax.set_xlabel("time")
        ax.set_ylabel(f"rrc = num / {RRC_FACTOR:g}")
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"rrc_{enb}.png"), dpi=120)
        plt.close(fig)

    print(f"plotted {len(enbs)} eNodeB(s) -> '{out_dir}/'")


# ============================== orchestration ==============================

def analyze_target(target_enb, locations_df, start, end,
                   k=20, kpi_path=None, zero_threshold=0.0, min_len=1,
                   plot_on_target_down=True):
    """Nearest-k neighbours -> KPI for target+neighbours -> rrc-zero intervals.
    If the TARGET hits rrc=0, plot everyone into a folder named after it,
    neighbours annotated with distance, the target's down period shaded."""
    target_enb = str(target_enb)

    # 1. nearest-k neighbours (with distances)
    nbr = get_neighbors(target_enb, locations_df, k=k)
    enb_list = [target_enb] + nbr[COL_ENB].astype(str).tolist()
    print(f"target {target_enb} + {len(nbr)} nearest neighbour(s)")

    # 2. KPI for everyone -> one dataframe (saved)
    kpi_path = kpi_path or f"kpi_{target_enb}.parquet"
    kpi_df = fetch_kpi(enb_list, start, end, save_path=kpi_path)

    # 3. fill gaps with 0, compute rrc
    kpi_df = add_rrc(fill_gaps_with_zero(kpi_df))

    # 4. rrc-zero intervals in the window
    zeros = find_zero_intervals(kpi_df, window=(start, end),
                                zero_threshold=zero_threshold, min_len=min_len)

    # 5. if the TARGET went rrc=0, plot everyone (distances annotated)
    target_down = (not zeros.empty) and (target_enb in set(zeros[COL_ENB].astype(str)))
    if plot_on_target_down and target_down:
        tz = zeros[zeros[COL_ENB].astype(str) == target_enb]
        window_hl = (tz["start"].min(), tz["end"].max())     # the target's own down period
        plot_target_and_neighbors(kpi_df, target_enb, nbr, window=window_hl,
                                  out_dir=f"{target_enb}")
        print(f"target {target_enb} hit rrc=0 -> plots saved to '{target_enb}/'")
    elif plot_on_target_down:
        print(f"target {target_enb} did NOT hit rrc=0 in the window - no plots")

    return {"enb_list": enb_list, "neighbours": nbr,
            "kpi_df": kpi_df, "zero_intervals": zeros, "target_down": target_down}

import os, json
import pandas as pd

OUT_CSV = "case_results.csv"

# 断点续跑:已经写过的 target 跳过(重启就接着没跑完的继续)
done = set(pd.read_csv(OUT_CSV)["target"].astype(str)) if os.path.exists(OUT_CSV) else set()

for _, t in tickets.iterrows():
    tgt = str(t["ENODEB"])
    if tgt in done:
        continue

    s, e = times_for_ticket(t["ALARM_TIME"], t["RETURN_TO_SERVICE"])
    out = analyze_target(tgt, locations, s, e, k=20, min_len=3)

    z = out["zero_intervals"]
    down_hours_by_enb = z.groupby("ENODEB")["n_points"].sum().to_dict() if not z.empty else {}
    tz = z[z["ENODEB"].astype(str) == tgt] if not z.empty else z   # target 自己的 down 段

    neighbours = [
        {"enb": r["ENODEB"],
         "distance_km": round(float(r["distance_km"]), 3),
         "down_hours": int(down_hours_by_enb.get(r["ENODEB"], 0))}   # 这个邻站有没有也掉 0
        for _, r in out["neighbours"].iterrows()
    ]

    row = {
        "target": tgt,
        "target_down": out["target_down"],
        "down_hours": int(tz["n_points"].sum()) if len(tz) else 0,   # target 掉 0 共多少小时
        "down_start": tz["start"].min() if len(tz) else None,
        "down_end":   tz["end"].max()   if len(tz) else None,
        "n_neighbors": len(neighbours),
        "n_neighbors_down": sum(n["down_hours"] > 0 for n in neighbours),
        "neighbours": json.dumps(neighbours, default=str),   # 邻站列表 + 距离 + 各自 down 小时
    }

    pd.DataFrame([row]).to_csv(OUT_CSV, mode="a", header=not os.path.exists(OUT_CSV), index=False)
    print(f"appended {tgt} -> {OUT_CSV}", flush=True)
# ================================ USAGE EXAMPLE ================================
# import pandas as pd
# from outage_analysis import analyze_target, times_for_ticket
#
# tickets   = pd.read_parquet("tickets.parquet")     # has ALARM_TIME, RETURN_TO_SERVICE (unix) + target eNodeB
# locations = pd.read_parquet("locations.parquet")   # eNodeB -> lat/lon (LOC_* columns above)
#
# # ---- one ticket ----
# ticket = tickets.iloc[0]
# target = str(ticket["ENODEB"])                     # <- adjust to your target-eNodeB column
# start, end = times_for_ticket(ticket["ALARM_TIME"], ticket["RETURN_TO_SERVICE"])
#
# out = analyze_target(target, locations, start, end, k=20, min_len=3)
# #   min_len=3  -> need >=3 consecutive hours of rrc=0 to count as "down"
#
# out["neighbours"]      # nearest 20 eNodeBs + distance_km
# out["zero_intervals"]  # who hit rrc=0 and when (ENODEB / start / end / n_points)
# out["target_down"]     # did the target itself hit rrc=0? if True, plots are in ./<target>/
#
# # ---- loop over all tickets ----
# for _, t in tickets.iterrows():
#     tgt = str(t["ENODEB"])
#     s, e = times_for_ticket(t["ALARM_TIME"], t["RETURN_TO_SERVICE"])
#     analyze_target(tgt, locations, s, e, k=20, min_len=3)
# ==============================================================================
