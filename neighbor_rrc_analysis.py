"""Confirm the mechanism: did the neighbours' own load drop because incoming
users displaced existing ones (control-plane overload), not because PRB ran out?

This is the REVERSE-ENGINEERING / labelling step -- it deliberately compares the
real outage window against the historical baseline (same window hours + same
day-of-week, before the outage). It is NOT part of the what-if predictor.

Smoking gun for "new pushes out old":
    during the outage window, vs baseline ->
        RRC connected   DOWN
        RRC drops       UP        (existing users released)
        setup failures  UP        (new users rejected)
        PRB util        ~FLAT     (so it is not a data-plane limit)

Aggregation: connected/PRB are levels (per-cell sum(Num)/sum(Den), connected then
summed across cells); drops/attempts/failures are counts (summed).
"""

import matplotlib.pyplot as plt
import pandas as pd


def compare_outage_vs_baseline(df, cell_col, outage_start, outage_end, *,
                               datetime_col="DATETIME",
                               conn_num="RRCConnUEsNum", conn_den="RRCConnUEsDen",
                               prb_used="PrbUsedDl", prb_avail="PrbAvailDl",
                               drop_col=None, att_col=None, fail_col=None,
                               out_path="outage_vs_baseline.png"):
    """Outage-window vs historical-baseline change, pooled over neighbours.

    Args:
        outage_start/outage_end : the real outage window (datetimes).
        drop_col   : RRC abnormal-release / drop count column (optional).
        att_col/fail_col : RRC setup attempt / failure count columns (optional).

    Returns a DataFrame [baseline, outage, pct_change] per metric and saves a
    bar chart of pct_change.
    """
    df = df.copy()
    df[datetime_col] = pd.to_datetime(df[datetime_col])
    df["date"] = df[datetime_col].dt.date
    outage_start = pd.to_datetime(outage_start)
    outage_end = pd.to_datetime(outage_end)

    lo, hi = outage_start.hour, outage_end.hour
    dow = outage_start.dayofweek
    h = df[datetime_col].dt.hour
    inwin = ((h >= lo) & (h < hi)) if lo < hi else ((h >= lo) | (h < hi))

    is_outage = (df[datetime_col] >= outage_start) & (df[datetime_col] < outage_end)
    is_base = (df[datetime_col] < outage_start) & \
              (df[datetime_col].dt.dayofweek == dow) & inwin

    def site_per_date(mask):
        d = df[mask]
        out = {}
        # connected: level -> per (cell,date) weighted mean, then sum across cells
        cc = d.groupby([cell_col, "date"]).agg(n=(conn_num, "sum"),
                                               de=(conn_den, "sum"))
        cc["v"] = cc["n"] / cc["de"].replace(0, pd.NA)
        out["RRC connected"] = cc["v"].groupby(level="date").sum()
        # PRB util: pooled used/avail per date
        out["PRB util"] = (d.groupby("date")[prb_used].sum() /
                           d.groupby("date")[prb_avail].sum().replace(0, pd.NA))
        if drop_col:
            out["RRC drops"] = d.groupby("date")[drop_col].sum()
        if att_col and fail_col:
            out["setup fail rate"] = (d.groupby("date")[fail_col].sum() /
                                      d.groupby("date")[att_col].sum().replace(0, pd.NA))
        return out

    base, outg = site_per_date(is_base), site_per_date(is_outage)

    rows = {}
    for m in base:
        b = float(base[m].mean())
        o = float(outg[m].mean()) if len(outg.get(m, [])) else float("nan")
        rows[m] = {"baseline": b, "outage": o,
                   "pct_change": (o / b - 1) * 100 if b else float("nan")}
    comp = pd.DataFrame(rows).T[["baseline", "outage", "pct_change"]]

    # plot: % change from baseline per metric (one axis -> easy to read)
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = ["C2" if v >= 0 else "C3" for v in comp["pct_change"]]
    ax.bar(comp.index, comp["pct_change"], color=colors)
    ax.axhline(0, color="k", lw=1)
    ax.set_ylabel("change vs baseline (%)")
    ax.set_title("Neighbours: outage window vs historical baseline")
    for x, v in enumerate(comp["pct_change"]):
        ax.text(x, v, f"{v:+.0f}%", ha="center",
                va="bottom" if v >= 0 else "top", fontsize=9)
    plt.xticks(rotation=20)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)

    print(comp.round(2))
    return comp


if __name__ == "__main__":
    # df_nbr = pd.read_csv("neighbor_kpi.csv")   # spans baseline month + outage day
    # comp = compare_outage_vs_baseline(
    #     df_nbr, cell_col="cell_name",
    #     outage_start="2026-05-21 19:00", outage_end="2026-05-21 23:00",
    #     drop_col="RRCConnAbnormRel", att_col="RRCConnReq", fail_col="RRCConnFail")
    pass
