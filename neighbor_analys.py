"""Why do the neighbours drop so many connections when the down site fails?

What-if framing: in HISTORICAL data the neighbours don't drop (no outage). What
history shows is whether they are already near-saturated at the outage window --
if their spare capacity is small, the down site's load (gross) overflows and the
overflow is what manifests as dropped connections during the real outage.

This module, given the neighbours' historical KPI (same window + day-of-week as
the outage), computes per-neighbour spare capacity and compares the total spare
to gross.

PRB utilisation = PrbUsedDl / PrbAvailDl.  Connected UEs = RRCConnUEsNum / Den.
Spare connections before PRB saturates (linear approx, no PDCCH yet):
    absorbable_i = RRC_i * (1 - PRB_i) / PRB_i
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def analyze_neighbor_headroom(df, cell_col, gross, *,
                              datetime_col="DATETIME",
                              num_col="RRCConnUEsNum",
                              den_col="RRCConnUEsDen",
                              prb_used_col="PrbUsedDl",
                              prb_avail_col="PrbAvailDl",
                              window=(19, 23),
                              dow=None,
                              out_path="neighbor_headroom.png"):
    """Per-neighbour spare capacity vs the load to absorb (gross).

    Args:
        df    : historical neighbour KPI (RRC num/den + PrbUsedDl/PrbAvailDl).
        gross : the down site's window load to be absorbed (from step 1).
        dow   : if set, keep only this day-of-week (0=Mon); else all weekdays.

    Returns (table, totals):
        table  : per-neighbour DataFrame [rrc, prb_util, absorbable].
        totals : dict with gross, total_absorbable, net_loss.
    """
    df = df.copy()
    df[datetime_col] = pd.to_datetime(df[datetime_col])
    df["hour"] = df[datetime_col].dt.hour
    df = df[df[datetime_col].dt.dayofweek == dow] if dow is not None \
        else df[df[datetime_col].dt.dayofweek < 5]

    lo, hi = window
    inwin = ((df["hour"] >= lo) & (df["hour"] < hi)) if lo < hi \
        else ((df["hour"] >= lo) | (df["hour"] < hi))      # wraps midnight

    # --- per-neighbour window aggregates (Den/Avail-weighted means) ---
    g = (df[inwin].groupby(cell_col)
            .agg(Num=(num_col, "sum"), Den=(den_col, "sum"),
                 Used=(prb_used_col, "sum"), Avail=(prb_avail_col, "sum")))
    g["rrc"] = g["Num"] / g["Den"].replace(0, np.nan)
    g["prb_util"] = g["Used"] / g["Avail"].replace(0, np.nan)
    # spare connections before PRB hits 100% (linear approx)
    g["absorbable"] = (g["rrc"] * (1 - g["prb_util"]) / g["prb_util"]).clip(lower=0)
    g = g.sort_values("prb_util", ascending=False)

    total_absorbable = float(g["absorbable"].sum())
    totals = {
        "gross": round(gross, 1),
        "total_absorbable": round(total_absorbable, 1),
        "net_loss": round(max(0.0, gross - total_absorbable), 1),
    }

    # --- PRB utilisation by hour-of-day (the "why"), per neighbour ---
    prof = (df.groupby([cell_col, "hour"])
              .agg(Used=(prb_used_col, "sum"), Avail=(prb_avail_col, "sum")))
    prof["util"] = prof["Used"] / prof["Avail"].replace(0, np.nan)
    prof = prof["util"].unstack(0)          # index=hour, columns=neighbour

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # left: PRB util vs hour-of-day -> are neighbours saturated in the window?
    for col in prof.columns:
        ax1.plot(prof.index, 100 * prof[col], lw=1, alpha=0.7)
    ax1.plot(prof.index, 100 * prof.mean(axis=1), color="k", lw=2.5, label="mean")
    ax1.axvspan(lo, hi, color="red", alpha=0.10, label="outage window")
    ax1.axhline(100, color="grey", ls="--", lw=1)
    ax1.set_xlabel("hour of day"); ax1.set_ylabel("PRB utilisation (%)")
    ax1.set_title("Neighbour PRB utilisation (historical)")
    ax1.legend(loc="lower center", fontsize=8)

    # right: demand vs capacity -> overflow = net loss
    ax2.bar(["load to absorb\n(gross)"], [gross], color="C3", label="gross")
    ax2.bar(["neighbour\nheadroom"], [total_absorbable], color="C2",
            label="Σ absorbable")
    ax2.set_ylabel("RRC connections")
    ax2.set_title(f"Demand vs capacity  |  net loss ≈ {totals['net_loss']:,.0f}")
    for x, v in [(0, gross), (1, total_absorbable)]:
        ax2.text(x, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=9)

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    print(totals)
    print(g[["rrc", "prb_util", "absorbable"]].round(2))
    return g[["rrc", "prb_util", "absorbable"]], totals


if __name__ == "__main__":
    # df_nbr = pd.read_csv("neighbor_kpi.csv")     # historical, same window+DoW
    # table, totals = analyze_neighbor_headroom(df_nbr, cell_col="CELLNAME",
    #                                            gross=480, window=(19, 23))
    pass
