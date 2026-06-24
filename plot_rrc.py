"""
plot_rrc.py

Quick look at RRC vs time, one chart per eNodeB.

Input dataframe columns (adjust the CONFIG block to match yours):
    DATETIME        time point
    ENODEB          eNodeB id            <-- I GUESSED this name (see note)
    RRCConnUEsNum   numerator
    RRCConnUEsDen   denominator

rrc at each time point = RRCConnUEsNum / 180   (denominator column not used)
"""

import os
import pandas as pd
import matplotlib.pyplot as plt

# ---------------- CONFIG: change these if your columns differ ----------------
COL_TIME = "DATETIME"
COL_ENB  = "ENODEB"          # <-- you said "enodeb (uppercase)"; fix if it's e.g. "enodeb"
COL_NUM  = "RRCConnUEsNum"
COL_DEN  = "RRCConnUEsDen"  # not used in current rrc formula
RRC_DEN_FACTOR = 180.0       # rrc = num / RRC_DEN_FACTOR
# -----------------------------------------------------------------------------
https://www.openstreetmap.org/export/embed.html?bbox=-74.017848,40.703817,-73.994152,40.721783&layer=mapnik&marker=40.7128,-74.0060
def fill_gaps_with_zero(df, time_col="DATETIME", enb_col="ENODEB",
                        value_cols=("RRCConnUEsNum", "RRCConnUEsDen"), freq="1h"):
    """For each eNodeB, put it on a regular `freq` grid (its own min..max) and
    fill the value columns at the inserted time points with 0."""
    df = df.copy()
    df[time_col] = pd.to_datetime(df[time_col])
    out = []
    for enb, sub in df.groupby(enb_col):
        sub = sub.set_index(time_col).sort_index()
        sub = sub.reindex(pd.date_range(sub.index.min(), sub.index.max(), freq=freq))
        sub[enb_col] = enb
        for c in value_cols:
            if c in sub.columns:
                sub[c] = sub[c].fillna(0)
        out.append(sub.rename_axis(time_col).reset_index())
    return pd.concat(out, ignore_index=True)

def compute_rrc(df):
    """Add an 'rrc' column = num / 180."""
    df = df.copy()
    df[COL_TIME] = pd.to_datetime(df[COL_TIME])
    df["rrc"] = df[COL_NUM] / RRC_DEN_FACTOR
    return df


def plot_rrc_per_enodeb(df, save_dir="rrc_plots", show=False,
                        highlight=None, highlight_color="tab:red", highlight_alpha=0.15):
    """Draw one RRC-vs-time line chart for EVERY eNodeB in `df` and save them
    all into `save_dir` (one PNG per eNodeB).

    show=True also displays each figure inline (handy in a notebook).
    highlight=(start, end) shades that time window on every plot, e.g.
        highlight=("2026-06-01 10:00", "2026-06-01 12:30")
    """
    df = compute_rrc(df)
    enbs = sorted(df[COL_ENB].unique())
    os.makedirs(save_dir, exist_ok=True)

    # Pre-parse the highlight window once (numpy datetime64, matches the x axis).
    hl = None
    if highlight is not None:
        hs, he = highlight
        hl = (pd.to_datetime(hs).to_numpy(), pd.to_datetime(he).to_numpy())

    print(f"{len(enbs)} eNodeB(s) -> saving PNGs to '{save_dir}/'")

    for enb in enbs:
        sub = df[df[COL_ENB] == enb].sort_values(COL_TIME)

        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot(sub[COL_TIME].to_numpy(), sub["rrc"].to_numpy(), marker=".", linewidth=1)

        if hl is not None:
            ax.axvspan(hl[0], hl[1], color=highlight_color, alpha=highlight_alpha,
                       label="window")
            ax.legend(loc="upper right", fontsize=8)

        ax.set_title(f"eNodeB {enb} - RRC vs time")
        ax.set_xlabel("time")
        ax.set_ylabel("rrc = num / 180")
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()

        fig.savefig(os.path.join(save_dir, f"rrc_{enb}.png"), dpi=120)
        if show:
            plt.show()
        plt.close(fig)          # free the figure (avoids the >20 open-figures warning)

    print(f"done: {len(enbs)} plots written to '{save_dir}/'")


if __name__ == "__main__":
    # Example:
    # df = pd.read_parquet("sample1.parquet")
    # plot_rrc_per_enodeb(df, save_dir="rrc_plots")
    pass
