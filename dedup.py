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


# ============================================================
# kpi_id collision handling (different names -> same derived id)
# ============================================================
import unicodedata


def derive_kpi_id(name: str) -> str:
    """Must stay IDENTICAL to build_registry.derive_kpi_id."""
    s = unicodedata.normalize("NFKC", str(name)).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def resolve_id_collisions(df, col_kpi, col_num, col_den):
    """Handle rows whose DIFFERENT names derive the SAME kpi_id.

    Two sub-cases per colliding id:
      A. same formula  -> truly the same KPI written differently: collapse to one row
      B. diff formula  -> genuinely different KPIs: keep all, disambiguate by
                          appending _2, _3 ... to kpi_id (never dropped)

    Returns:
        out_df:      df with an added 'kpi_id' column, collisions resolved,
                     A-cases collapsed, B-cases disambiguated.
        collapsed:   dict {kpi_id: [names...]} that were merged (sub-case A)
        disambiguated: dict {base_id: [(assigned_id, name, num, den), ...]} (sub-case B)
    """
    work = df.copy().reset_index(drop=True)
    work["_id"] = work[col_kpi].map(derive_kpi_id)
    work["_num"] = work[col_num].map(_canon)
    work["_den"] = work[col_den].map(_canon)

    assigned_id = {}          # original row index -> final kpi_id
    drop_rows = set()
    collapsed = {}
    disambiguated = {}

    for base_id, group in work.groupby("_id", sort=False):
        if len(group) == 1:
            assigned_id[group.index[0]] = base_id
            continue

        # distinct formula signatures among the colliding rows
        sig_groups = group.groupby(["_num", "_den"], sort=False)

        if len(sig_groups) == 1:
            # sub-case A: all same formula -> keep first, drop rest, collapse
            keep = group.index[0]
            assigned_id[keep] = base_id
            drop_rows.update(group.index[1:])
            collapsed[base_id] = group[col_kpi].tolist()
        else:
            # sub-case B: different formulas -> disambiguate, keep ALL
            recs = []
            for n, (_, sg) in enumerate(sig_groups, start=1):
                final_id = base_id if n == 1 else f"{base_id}_{n}"
                idx = sg.index[0]               # one row per distinct formula
                assigned_id[idx] = final_id
                # if a formula sig itself repeats, drop its extra rows too
                drop_rows.update(sg.index[1:])
                recs.append((final_id, sg[col_kpi].iloc[0],
                             sg[col_num].iloc[0], sg[col_den].iloc[0]))
            disambiguated[base_id] = recs

    keep_idx = [i for i in work.index if i not in drop_rows]
    out_df = df.loc[keep_idx].copy().reset_index(drop=True)
    out_df["kpi_id"] = [assigned_id[i] for i in keep_idx]
    return out_df, collapsed, disambiguated


# ============================================================
# id-collision diagnosis + dedup
# ============================================================
import unicodedata


def derive_kpi_id(name: str) -> str:
    """Same derivation as build_registry: display_name -> snake_case id.
    Lossy: non-alphanumerics -> underscore, so distinct names can collide."""
    s = unicodedata.normalize("NFKC", str(name)).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def show_id_collisions(df, col_kpi, col_num=None, col_den=None):
    """Diagnose kpi_id collisions: print each colliding id with the ORIGINAL
    names (and formulas, if columns given) that produced it. Read-only."""
    ids = df[col_kpi].map(derive_kpi_id)
    coll_ids = ids[ids.duplicated(keep=False)].unique()
    print(f"{len(coll_ids)} kpi_id(s) have collisions:\n")
    for cid in coll_ids:
        rows = df.loc[ids == cid]
        print(f"id '{cid}':")
        for _, r in rows.iterrows():
            extra = ""
            if col_num and col_den:
                extra = f"   | num={r[col_num]!r} den={r[col_den]!r}"
            print(f"    name={r[col_kpi]!r}{extra}")
        print()
    return coll_ids
