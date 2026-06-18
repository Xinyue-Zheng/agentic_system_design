import numpy as np
import pandas as pd


def diverse_sample(df, n=10, cols=("period", "DENSITY"), n_bins=4, random_state=None):
    """Randomly pick n rows while maximizing diversity across the given columns.

    For each column in `cols`:
        - string / categorical -> each distinct value is its own level
          (e.g. DENSITY in {RURAL, SUBURBAN, URBAN})
        - numeric with many distinct values -> binned into `n_bins` quantile levels
    The levels are combined into a group label, then rows are drawn round-robin
    across groups so the sample covers as many distinct combinations as possible.
    Randomness (group order + within-group order) is controlled by random_state.

    Returns the selected rows (original columns and index preserved).
    """
    n = min(n, len(df))
    df[col] = df[col].apply(ast.literal_eval)

    df = df[
        df[col].str.len().gt(0)
        & (df[col].str[0].str.len() == 13)
    ]
    rng = np.random.default_rng(random_state)

    # Build a categorical level for each diversity column.
    levels = []
    for c in cols:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) and s.nunique() > n_bins:
            lvl = pd.qcut(s, q=n_bins, labels=False, duplicates="drop")
            lvl = lvl.astype("Int64").astype(str)
        else:
            lvl = s.astype(str)
        levels.append(lvl)

    group = levels[0]
    for lvl in levels[1:]:
        group = group.str.cat(lvl, sep=" | ")

    # Shuffle rows within each group, and shuffle the group order.
    buckets = {}
    for g, sub in group.groupby(group):
        idx = list(sub.index)
        rng.shuffle(idx)
        buckets[g] = idx
    order = list(buckets.keys())
    rng.shuffle(order)

    # Round-robin: take one from each group per pass until we have n rows.
    picked = []
    while len(picked) < n and any(buckets[g] for g in order):
        for g in order:
            if buckets[g]:
                picked.append(buckets[g].pop())
                if len(picked) >= n:
                    break

    return df.loc[picked]


def coverage_summary(sample, cols=("period", "DENSITY")):
    """Quick look at how diverse a sample is: distinct combos + per-column counts."""
    combos = sample.groupby(list(cols)).ngroups
    print(f"{len(sample)} rows, {combos} distinct {' x '.join(cols)} combinations")
    for c in cols:
        print(f"  {c}: {sample[c].value_counts().to_dict()}")


if __name__ == "__main__":
    rng = np.random.default_rng(1)
    periods = ["early_morning", "morning", "afternoon", "night", "cross-day"]
    df = pd.DataFrame({
        "case": range(200),
        "period": rng.choice(periods, 200),
        "DENSITY": rng.choice(["RURAL", "SUBURBAN", "URBAN"], 200),
    })

    out = diverse_sample(df, n=10, cols=("period", "DENSITY"), random_state=42)
    print(out[["case", "period", "DENSITY"]].to_string(index=False))
    print()
    coverage_summary(out, cols=("period", "DENSITY"))
