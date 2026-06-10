"""Collision resolution - separate module (not part of dedup.py).

Two things:
  1. derive_kpi_id_v2: id derivation that preserves comparison operators
     ('>' -> _gt_, '<=' -> _lte_, ...), so names differing only by an
     operator no longer collide.
  2. resolve_id_collisions: for ids that STILL collide after v2, collapse
     groups whose formulas are identical (keep first row), and report
     groups whose formulas differ (kept untouched, manual decision).

Row removal only -- the KPI name column is never modified, so the spaced
display names survive into build_registry as display_name.
"""

import re
import unicodedata

import pandas as pd

# order matters: two-char operators first
OP_TOKENS = [(">=", " gte "), ("<=", " lte "), (">", " gt "), ("<", " lt ")]


def derive_kpi_id_v2(name: str) -> str:
    """display_name -> snake_case id, preserving comparison operators.

    'DL Thp > 5MHz'  -> 'dl_thp_gt_5mhz'
    'DL Thp <= 5MHz' -> 'dl_thp_lte_5mhz'

    NOTE: build_registry.py must use this same derivation -- replace its
    derive_kpi_id with this function (or import it) before building the
    registry, otherwise ids will be inconsistent.
    """
    s = unicodedata.normalize("NFKC", str(name)).strip().lower()
    for op, tok in OP_TOKENS:
        s = s.replace(op, tok)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def _canon(expr) -> str:
    """Formula canonicalization for comparison (trim, lowercase, no spaces)."""
    if expr is None or (isinstance(expr, float) and pd.isna(expr)):
        return ""
    return re.sub(r"\s+", "", str(expr).strip().lower())


def resolve_id_collisions(df, col_kpi, col_num, col_den, derive=derive_kpi_id_v2):
    """Collapse id-collision groups that share identical formulas.

    Args:
        df: DataFrame (already name-deduplicated by dedup_kpis).
        col_kpi / col_num / col_den: column names.
        derive: id derivation function (default v2, operator-aware).

    Returns:
        clean_df:   rows collapsed where (derived id) collides AND formulas
                    are identical -- first row of each such group is kept.
                    Name column untouched; original row order preserved.
        unresolved: dict {kpi_id: [(name, num, den), ...]} for collisions
                    whose formulas differ -- all rows kept, resolve manually.
    """
    work = df.copy()
    work["_id"] = work[col_kpi].map(derive)
    work["_num"] = work[col_num].map(_canon)
    work["_den"] = work[col_den].map(_canon)

    keep_idx = []
    unresolved = {}

    for kid, group in work.groupby("_id", sort=False):
        if len(group) == 1:
            keep_idx.append(group.index[0])
            continue
        sigs = group[["_num", "_den"]].drop_duplicates()
        if len(sigs) == 1:
            # same id + same formula -> same KPI written differently; keep first
            keep_idx.append(group.index[0])
        else:
            # same id + different formulas -> genuinely different KPIs whose
            # names still collide; keep all, needs manual rename / rule fix
            keep_idx.extend(group.index.tolist())
            unresolved[kid] = [
                (r[col_kpi], r[col_num], r[col_den]) for _, r in group.iterrows()
            ]

    clean_df = df.loc[sorted(keep_idx)].reset_index(drop=True)
    return clean_df, unresolved


# ---- example usage ----
if __name__ == "__main__":
    # df = <your loaded & name-deduplicated DataFrame>
    # clean_df, unresolved = resolve_id_collisions(df, "kpi_name", "nominator", "denominator")
    # print(f"{len(df)} -> {len(clean_df)} rows")
    # for kid, rows in unresolved.items():
    #     print("UNRESOLVED", kid)
    #     for name, num, den in rows:
    #         print("   ", repr(name), "| num:", num, "| den:", den)
    # clean_df.to_excel("kpi_formulas_resolved.xlsx", index=False)  # or keep in memory
    pass
