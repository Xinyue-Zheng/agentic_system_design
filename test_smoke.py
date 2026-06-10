"""Step 4 - Smoke test.

Two stages:
  A. Dry run (default): no Snowflake connection; prints the generated SQL
     for manual review.
  B. Reconciliation (RUN_LIVE=True): runs your 4 legacy hard-coded KPI
     queries and the new builder against the same scope, then compares
     values bucket by bucket -- proof that formulas were transcribed from
     the spreadsheet into SQL without errors.

Usage:  python test_smoke.py
"""

import pandas as pd

from query_builder import KPIQueryBuilder, UnknownKPIError

# ============ PLACEHOLDERS: edit to match your environment ============
RUN_LIVE = False
TEST_ENODEB = "PLACEHOLDER_ENODEB"
TEST_START = "2026-05-01"
TEST_END = "2026-05-08"

# Your 4 legacy hard-coded KPIs: registry name -> full legacy SQL.
# Each legacy query's output must include a 'bucket' column and the KPI column.
LEGACY_QUERIES = {
    "PLACEHOLDER_kpi_1": "PLACEHOLDER full legacy SQL",
    "PLACEHOLDER_kpi_2": "...",
    "PLACEHOLDER_kpi_3": "...",
    "PLACEHOLDER_kpi_4": "...",
}
# from your_snowflake_utils import run_query
# ======================================================================

REL_TOL = 1e-6   # relative tolerance (float aggregation-order differences)


def stage_a_dry_run(builder: KPIQueryBuilder) -> None:
    print("=" * 60, "\nStage A - dry run\n")
    kpis = list(LEGACY_QUERIES.keys())
    try:
        sql, params = builder.build(
            TEST_ENODEB, TEST_START, TEST_END, kpis, granularity="day"
        )
    except UnknownKPIError as e:
        print("Name resolution failed (fix names in LEGACY_QUERIES or the registry):")
        print(e.message)
        return
    print(sql, "\n\nparams:", params)
    print("\nReview checklist: ratio KPIs use SUM/NULLIF(SUM), counter KPIs use plain SUM,")
    print("aliases are snake_case, formulas match the spreadsheet source.")

    # Also exercise the fuzzy-correction path
    try:
        builder.build(TEST_ENODEB, TEST_START, TEST_END, ["rrc conected users"])
    except UnknownKPIError as e:
        print("\n[fuzzy-correction demo] the agent would receive:\n", e.message)


def stage_b_reconcile(builder: KPIQueryBuilder) -> None:
    from your_snowflake_utils import run_query  # placeholder import

    print("=" * 60, "\nStage B - legacy vs builder reconciliation\n")
    kpis = list(LEGACY_QUERIES.keys())
    sql, params = builder.build(
        TEST_ENODEB, TEST_START, TEST_END, kpis, granularity="day"
    )
    new_df = run_query(sql, params)
    new_df.columns = [c.lower() for c in new_df.columns]

    all_pass = True
    for kpi, legacy_sql in LEGACY_QUERIES.items():
        old_df = run_query(legacy_sql, None)
        old_df.columns = [c.lower() for c in old_df.columns]
        merged = old_df.merge(
            new_df[["bucket", kpi]], on="bucket", suffixes=("_old", "_new")
        )
        old_col = f"{kpi}_old" if f"{kpi}_old" in merged else kpi
        diff = (
            (merged[old_col] - merged[f"{kpi}_new"]).abs()
            / merged[old_col].abs().clip(lower=1e-12)
        )
        bad = merged[diff > REL_TOL]
        status = "PASS" if bad.empty else f"FAIL ({len(bad)} buckets)"
        if not bad.empty:
            all_pass = False
            print(f"  {kpi}: {status}")
            print(bad.head(3).to_string(index=False))
        else:
            print(f"  {kpi}: {status}")
    print("\nReconciliation result:",
          "all match -- builder is trustworthy" if all_pass
          else "differences found -- check formula transcription")


if __name__ == "__main__":
    builder = KPIQueryBuilder()
    stage_a_dry_run(builder)
    if RUN_LIVE:
        stage_b_reconcile(builder)
    else:
        print("\n(RUN_LIVE=False, Stage B skipped; fill placeholders and set True to reconcile)")
