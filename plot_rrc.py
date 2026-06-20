"""
plot_rrc.py

Quick look at RRC vs time, one chart per eNodeB.

Input dataframe columns (adjust the CONFIG block to match yours):
    DATETIME        time point
    ENODEB          eNodeB id            <-- I GUESSED this name (see note)
    RRCConnUEsNum   numerator
    RRCConnUEsDen   denominator

rrc at each time point = RRCConnUEsNum / (180 * RRCConnUEsDen)   <-- CONFIRM this
"""

import os
import pandas as pd
import matplotlib.pyplot as plt

# ---------------- CONFIG: change these if your columns differ ----------------
COL_TIME = "DATETIME"
COL_ENB  = "ENODEB"          # <-- you said "enodeb (uppercase)"; fix if it's e.g. "enodeb"
COL_NUM  = "RRCConnUEsNum"
COL_DEN  = "RRCConnUEsDen"
RRC_DEN_FACTOR = 180.0       # rrc = num / (RRC_DEN_FACTOR * den)
# -----------------------------------------------------------------------------


def compute_rrc(df):
    """Add an 'rrc' column = num / (180 * den). den == 0 -> NaN (so no inf)."""
    df = df.copy()
    df[COL_TIME] = pd.to_datetime(df[COL_TIME])
    denom = RRC_DEN_FACTOR * df[COL_DEN]
    df["rrc"] = df[COL_NUM] / denom.where(denom != 0)   # divide-by-zero -> NaN
    return df


def plot_rrc_per_enodeb(df, save_dir="rrc_plots", show=False):
    """Draw one RRC-vs-time line chart for EVERY eNodeB in `df` and save them
    all into `save_dir` (one PNG per eNodeB).

    show=True also displays each figure inline (handy in a notebook).
    """
    df = compute_rrc(df)
    enbs = sorted(df[COL_ENB].unique())
    os.makedirs(save_dir, exist_ok=True)
    print(f"{len(enbs)} eNodeB(s) -> saving PNGs to '{save_dir}/'")

    for enb in enbs:
        sub = df[df[COL_ENB] == enb].sort_values(COL_TIME)

        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot(sub[COL_TIME], sub["rrc"], marker=".", linewidth=1)
        ax.set_title(f"eNodeB {enb} - RRC vs time")
        ax.set_xlabel("time")
        ax.set_ylabel("rrc = num / (180 * den)")
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
