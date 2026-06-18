"""Plot the historical RRC load profile of the down cells, to read off the
what-if impact: how many connections the site carries during the outage window.

RRC connected UEs is a LEVEL (a stock), not an event count:
    * across time (days / sub-hour bins) -> AVERAGE   (weighted by the Den)
    * across cells (same instant)        -> SUM
RRCConnUEsNum / RRCConnUEsDen is the average connected UEs in that bin, so
sum(Num)/sum(Den) is the correct time-weighted average whether the rows are
15-min or hourly.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_rrc_load_profile(df, cell_col, *,
                          datetime_col="DATETIME",
                          num_col="RRCConnUEsNum",
                          den_col="RRCConnUEsDen",
                          window=(19, 23),          # 7pm-11pm, hour-of-day
                          out_path="rrc_load_profile.png"):
    """Two-panel hour-of-day profile of the down cells (averaged over baseline days).

    Top    : total RRC connected UEs (mean line + day-to-day min-max band).
    Bottom : per-cell stacked area, so you see which sectors carry the load.
    The outage window is shaded on both. Returns (band, pivot) and prints the
    average total connections at risk during the window.
    """
    df = df.copy()
    df[datetime_col] = pd.to_datetime(df[datetime_col])
    df["hour"] = df[datetime_col].dt.hour
    df["date"] = df[datetime_col].dt.date

    # --- per-cell hour-of-day profile, weighted-averaged across baseline days ---
    per_cell = (df.groupby([cell_col, "hour"])
                  .agg(Num=(num_col, "sum"), Den=(den_col, "sum"))
                  .reset_index())
    per_cell["conn"] = per_cell["Num"] / per_cell["Den"].replace(0, np.nan)
    pivot = per_cell.pivot(index="hour", columns=cell_col, values="conn").sort_index()

    # --- total per (date, hour) -> day-to-day variability band ---
    per_cell_day = (df.groupby([cell_col, "date", "hour"])
                      .agg(Num=(num_col, "sum"), Den=(den_col, "sum"))
                      .reset_index())
    per_cell_day["conn"] = per_cell_day["Num"] / per_cell_day["Den"].replace(0, np.nan)
    daily_total = per_cell_day.groupby(["date", "hour"])["conn"].sum().reset_index()
    band = daily_total.groupby("hour")["conn"].agg(["mean", "min", "max"]).sort_index()

    # headline number: avg total connected during the outage window
    lo, hi = window
    in_win = band.index[(band.index >= lo) & (band.index < hi)]
    window_avg = band.loc[in_win, "mean"].mean() if len(in_win) else float("nan")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    # top: total + day-to-day band
    ax1.plot(band.index, band["mean"], color="C0", lw=2,
             label="total RRC conn UEs (mean over days)")
    ax1.fill_between(band.index, band["min"], band["max"], color="C0", alpha=0.2,
                     label="day-to-day min-max")
    ax1.axvspan(lo, hi, color="red", alpha=0.10, label="outage window")
    ax1.set_ylabel("RRC connected UEs (site total)")
    ax1.set_title(f"Down-site evening load  |  avg connections at risk in window "
                  f"≈ {window_avg:,.0f}")
    ax1.legend(loc="upper left", fontsize=8)

    # bottom: per-cell stacked area
    pivot_filled = pivot.fillna(0)
    ax2.stackplot(pivot_filled.index, pivot_filled.T.values,
                  labels=[str(c) for c in pivot_filled.columns], alpha=0.85)
    ax2.axvspan(lo, hi, color="red", alpha=0.10)
    ax2.set_ylabel("RRC connected UEs (per cell)")
    ax2.set_xlabel("hour of day")
    ax2.set_xticks(range(0, 24, 2))
    ax2.set_xlim(band.index.min(), band.index.max())
    ax2.legend(loc="upper left", ncol=3, fontsize=7)

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    print(f"avg total RRC connected UEs in window {lo}:00-{hi}:00 ≈ "
          f"{window_avg:.1f}   ->  {out_path}")
    return band, pivot


def summarize_at_risk(df, cell_col, *,
                      datetime_col="DATETIME",
                      num_col="RRCConnUEsNum",
                      den_col="RRCConnUEsDen",
                      window=(19, 23),
                      weekday_only=True):
    
    df = df.copy()
    df[datetime_col] = pd.to_datetime(df[datetime_col])
    df["conn"] = df[num_col] / df[den_col].replace(0, np.nan)

    
    site = df.groupby(datetime_col)["conn"].sum().to_frame("conn")
    site["date"] = site.index.date
    site["hour"] = site.index.hour
    if weekday_only:
        site = site[site.index.dayofweek < 5]      

    lo, hi = window
    win = site[(site["hour"] >= lo) & (site["hour"] < hi)]

    per_date_window = win.groupby("date")["conn"].mean()   
    per_date_peak   = site.groupby("date")["conn"].max()   

    return {
        "window_avg": round(per_date_window.mean(), 1),    # 值1
        "busy_ratio": round(per_date_window.mean() / per_date_peak.mean(), 2),  # 值2
        "window_std": round(per_date_window.std(), 1),     # 值3
    }


if __name__ == "__main__":
    df = pd.read_csv("rrc_down_cells.csv")            # your already-queried data
    print(summarize_at_risk(df, cell_col="CELLNAME"))   # the three routing numbers
    plot_rrc_load_profile(df, cell_col="CELLNAME")      # the profile plot

