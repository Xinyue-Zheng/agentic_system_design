def site_overlap_weights(overlap_df, *, cell_col="cell_name",
                         overlap_col="overlap_pct", method="max"):
    """Collapse per-(down_cell, neighbour) overlap into one weight per neighbour.

    A neighbour can overlap several of the 9 down cells; we need one site-level
    overlap per neighbour to allocate the site's gross. method:
        "max"  -> the neighbour's strongest overlap with any down sector
        "sum"  -> covers more of the site -> bigger weight
        "mean" -> average overlap
    Returns a Series indexed by neighbour cell name.
    """
    return overlap_df.groupby(cell_col)[overlap_col].agg(method)


def analyze_neighbor_headroom(df, cell_col, gross, *,
                              overlap=None,
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
    g["headroom"] = (g["rrc"] * (1 - g["prb_util"]) / g["prb_util"]).clip(lower=0)

    if overlap is not None:
        # allocate gross to neighbours by overlap share, then each neighbour
        # only has to absorb ITS share -> overflow where share > its headroom.
        w = overlap.reindex(g.index).fillna(0.0)
        g["overlap"] = w
        share = w / w.sum() if w.sum() > 0 else w
        g["demand"] = gross * share
        g["absorbed"] = np.minimum(g["demand"], g["headroom"])
        g["overflow"] = (g["demand"] - g["absorbed"]).clip(lower=0)
        g = g.sort_values("overlap", ascending=False)
        net_loss = float(g["overflow"].sum())
        totals = {
            "gross": round(gross, 1),
            "absorbed": round(float(g["absorbed"].sum()), 1),
            "net_loss": round(net_loss, 1),
        }
    else:
        # no overlap: fall back to pooling all headroom (overestimates capacity)
        g = g.sort_values("prb_util", ascending=False)
        total_absorbable = float(g["headroom"].sum())
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

    if overlap is not None:
        # right: per-neighbour allocated demand vs its headroom -> overflow visible
        x = np.arange(len(g))
        ax2.bar(x - 0.2, g["demand"], width=0.4, color="C3", label="allocated demand")
        ax2.bar(x + 0.2, g["headroom"], width=0.4, color="C2", label="headroom")
        ax2.set_xticks(x)
        ax2.set_xticklabels(g.index, rotation=90, fontsize=6)
        ax2.set_ylabel("RRC connections")
        ax2.set_title(f"Per-neighbour demand vs headroom  |  net loss "
                      f"≈ {totals['net_loss']:,.0f}")
        cols = ["rrc", "prb_util", "overlap", "demand", "headroom", "overflow"]
    else:
        # right: gross vs pooled headroom (overestimate)
        ax2.bar(["load to absorb\n(gross)"], [gross], color="C3")
        ax2.bar(["Σ neighbour\nheadroom"], [totals["total_absorbable"]], color="C2")
        ax2.set_ylabel("RRC connections")
        ax2.set_title(f"Demand vs capacity  |  net loss ≈ {totals['net_loss']:,.0f}")
        cols = ["rrc", "prb_util", "headroom"]
    ax2.legend(loc="upper right", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    print(totals)
    print(g[cols].round(2))
    return g[cols], totals


def gross_by_hour(df, cell_col, *, datetime_col="DATETIME",
                  num_col="RRCConnUEsNum", den_col="RRCConnUEsDen",
                  window=None, dow=None):
    """Down site's connections-at-risk per hour-of-day (historical).

    For a long outage that spans night->day, don't collapse to one gross: this
    returns a Series indexed by hour. window=(lo,hi) keeps only the outage hours
    (wraps midnight); order follows the outage.
    """
    df = df.copy()
    df[datetime_col] = pd.to_datetime(df[datetime_col])
    df["hour"] = df[datetime_col].dt.hour
    df = df[df[datetime_col].dt.dayofweek == dow] if dow is not None \
        else df[df[datetime_col].dt.dayofweek < 5]

    g = df.groupby([cell_col, "hour"]).agg(n=(num_col, "sum"), de=(den_col, "sum"))
    g["conn"] = g["n"] / g["de"].replace(0, np.nan)
    site = g["conn"].groupby(level="hour").sum()          # sum across down cells

    if window is not None:
        lo, hi = window
        hours = [h for h in range(24)
                 if (lo <= h < hi) if lo < hi else (h >= lo or h < hi)]
        site = site.reindex(hours)
    return site

def plot_neighbor_prb_hourly(df, cell_col, *, datetime_col="DATETIME",
                             prb_used_col="PrbUsedDl", prb_avail_col="PrbAvailDl",
                             window=None, dow=None,
                             out_path="neighbor_prb_hourly.png"):
    """Heatmap of each neighbour's PRB utilisation by hour-of-day (historical).

    Rows = neighbours (sorted by their PRB util in the outage window), cols =
    hour. Lets you see DIRECTLY who is near-saturated, instead of trusting the
    (1-prb)/prb headroom extrapolation. The outage hours are boxed.
    """
    df = df.copy()
    df[datetime_col] = pd.to_datetime(df[datetime_col])
    df["hour"] = df[datetime_col].dt.hour
    df = df[df[datetime_col].dt.dayofweek == dow] if dow is not None \
        else df[df[datetime_col].dt.dayofweek < 5]

    g = df.groupby([cell_col, "hour"]).agg(used=(prb_used_col, "sum"),
                                           avail=(prb_avail_col, "sum"))
    g["util"] = g["used"] / g["avail"].replace(0, np.nan)
    mat = g["util"].unstack(level=cell_col).T          # rows=neighbour, cols=hour
    mat = mat.reindex(columns=sorted(mat.columns))

    if window is None:
        wcols = list(mat.columns)
    else:
        lo, hi = window
        if lo < hi:
            wcols = [h for h in mat.columns if lo <= h < hi]
        else:                                            # wraps midnight
            wcols = [h for h in mat.columns if h >= lo or h < hi]
    order = mat[wcols].mean(axis=1).sort_values(ascending=False).index
    mat = mat.loc[order]

    fig, ax = plt.subplots(figsize=(12, max(5, 0.14 * len(mat))))
    im = ax.imshow(100 * mat.values, aspect="auto", cmap="viridis",
                   vmin=0, vmax=100)
    ax.set_xticks(range(len(mat.columns)))
    ax.set_xticklabels(mat.columns, fontsize=7)
    ax.set_yticks(range(len(mat)))
    ax.set_yticklabels(mat.index, fontsize=4)
    ax.set_xlabel("hour of day")
    win_pos = [i for i, h in enumerate(mat.columns) if h in wcols]
    if win_pos:
        ax.axvspan(min(win_pos) - 0.5, max(win_pos) + 0.5,
                   fill=False, edgecolor="red", lw=1.5)   # outage hours
    ax.set_title("Neighbour PRB utilisation (%) by hour — sorted by window load")
    fig.colorbar(im, ax=ax, label="PRB util (%)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    print(f"{len(mat)} neighbours -> {out_path}")
    return mat

def headroom_by_hour(df, cell_col, gross_hourly, overlap, *,
                     datetime_col="DATETIME",
                     num_col="RRCConnUEsNum", den_col="RRCConnUEsDen",
                     prb_used_col="PrbUsedDl", prb_avail_col="PrbAvailDl",
                     dow=None, out_path="headroom_by_hour.png"):
    """Per-hour net loss: allocate each hour's gross by overlap, compare to each
    neighbour's headroom THAT hour. Returns DataFrame [gross, absorbed, net_loss]
    indexed by hour; total net loss is in connection-hours.
    """
    df = df.copy()
    df[datetime_col] = pd.to_datetime(df[datetime_col])
    df["hour"] = df[datetime_col].dt.hour
    df = df[df[datetime_col].dt.dayofweek == dow] if dow is not None \
        else df[df[datetime_col].dt.dayofweek < 5]
    hours = list(gross_hourly.index)
    df = df[df["hour"].isin(hours)]

    g = df.groupby([cell_col, "hour"]).agg(
        n=(num_col, "sum"), de=(den_col, "sum"),
        used=(prb_used_col, "sum"), avail=(prb_avail_col, "sum"))
    g["rrc"] = g["n"] / g["de"].replace(0, np.nan)
    g["prb"] = g["used"] / g["avail"].replace(0, np.nan)
    g["headroom"] = (g["rrc"] * (1 - g["prb"]) / g["prb"]).clip(lower=0)

    w = overlap.reindex(g.index.get_level_values(cell_col).unique()).fillna(0.0)
    share = w / w.sum() if w.sum() > 0 else w

    rows = []
    for hh in hours:
        gh = g.xs(hh, level="hour")                       # index = neighbour
        demand = gross_hourly[hh] * share.reindex(gh.index).fillna(0.0)
        absorbed = np.minimum(demand, gh["headroom"])
        overflow = (demand - absorbed).clip(lower=0)
        rows.append({"hour": hh, "gross": gross_hourly[hh],
                     "headroom": float(gh["headroom"].sum()),   # total capacity
                     "absorbed": float(absorbed.sum()),
                     "net_loss": float(overflow.sum())})
    res = pd.DataFrame(rows).set_index("hour")

    fig, ax = plt.subplots(figsize=(11, 5))
    x = np.arange(len(res))
    # stacked bar: absorbed (within headroom) + net loss = gross
    ax.bar(x, res["absorbed"], color="C2", label="absorbed (within headroom)")
    ax.bar(x, res["net_loss"], bottom=res["absorbed"], color="C3", label="net loss")
    # total available headroom as a line (the capacity that existed)
    ax.plot(x, res["headroom"], "k--o", ms=4, lw=1, label="total headroom (capacity)")
    ax.set_xticks(x); ax.set_xticklabels(res.index)
    ax.set_xlabel("hour of day"); ax.set_ylabel("RRC connections")
    ax.set_title(f"Per-hour: gross = absorbed + net loss  |  total net loss "
                 f"≈ {res['net_loss'].sum():,.0f} conn·h")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    print(res.round(1))
    return res
