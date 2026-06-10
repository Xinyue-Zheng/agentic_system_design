"""Standalone dedup function. Pass in a DataFrame you already loaded.

Removes rows where KPI name AND both formulas are identical (true redundancy),
keeps one. Rows with the same name but different formulas are kept and reported
as conflicts for you to resolve manually.
"""

import re

import pandas as pd


def _canon(expr) -> str:
    """Canonicalize a formula for comparison: trim, lowercase, strip all spaces.
    So '100 * COL_A' and '100*col_a' count as the same formula."""
    if expr is None or (isinstance(expr, float) and pd.isna(expr)):
        return ""
    return re.sub(r"\s+", "", str(expr).strip().lower())


def dedup_kpis(df, col_kpi, col_num, col_den):
    """Deduplicate KPI rows by (name, numerator, denominator).

    Args:
        df: DataFrame already loaded (any read method).
        col_kpi, col_num, col_den: the three column names in df.

    Returns:
        clean_df:  df with same-name-same-formula duplicates collapsed to one row,
                   original columns preserved, original row order kept.
        conflicts: dict {kpi_name: [(num, den), ...]} for same-name-different-formula
                   cases (these rows are NOT removed). Empty dict if none.
    """
    work = df.copy()
    work["_name"] = work[col_kpi].astype(str).str.strip().str.lower()
    work["_num"] = work[col_num].map(_canon)
    work["_den"] = work[col_den].map(_canon)

    keep_idx = []
    conflicts = {}

    for _, group in work.groupby("_name", sort=False):
        if len(group) == 1:
            keep_idx.append(group.index[0])
            continue
        sigs = group[["_num", "_den"]].drop_duplicates()
        if len(sigs) == 1:
            # same name + same formula -> keep first only
            keep_idx.append(group.index[0])
        else:
            # same name + different formula -> keep all, flag for manual review
            keep_idx.extend(group.index.tolist())
            conflicts[group[col_kpi].iloc[0]] = (
                group[[col_num, col_den]].drop_duplicates()
                     .apply(lambda r: (r[col_num], r[col_den]), axis=1).tolist()
            )

    clean_df = df.loc[sorted(keep_idx)].reset_index(drop=True)
    return clean_df, conflicts


# ---- example usage ----
if __name__ == "__main__":
    # df = <however you load it now>
    # clean_df, conflicts = dedup_kpis(df, "kpi_name", "nominator", "denominator")
    # print(f"{len(df)} -> {len(clean_df)} rows")
    # for name, variants in conflicts.items():
    #     print("CONFLICT", name, variants)
    pass
