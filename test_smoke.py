"""Step 4 — 冒烟测试.

两个阶段:
  A. 干跑(默认): 不连 Snowflake, 打印生成的 SQL 供人工 review.
  B. 对账(RUN_LIVE=True): 用你原来写死的 4 个 KPI 的旧 SQL 和新 builder
     各跑一次, 逐 bucket 比对数值 — 这是"公式从表格搬进 SQL 没搬错"的证明.

用法:  python test_smoke.py
"""

import pandas as pd

from query_builder import KPIQueryBuilder, UnknownKPIError

# ============ 占位区 ============
RUN_LIVE = False
TEST_ENODEB = "PLACEHOLDER_ENODEB"
TEST_START = "2026-05-01"
TEST_END = "2026-05-08"

# 你原来写死的 4 个 KPI: 名字(registry 里的) -> 旧脚本里的完整 SQL
LEGACY_QUERIES: dict[str, str] = {
    "PLACEHOLDER_kpi_1": "PLACEHOLDER 旧版完整 SQL, 输出列须含 bucket 和该 KPI",
    "PLACEHOLDER_kpi_2": "...",
    "PLACEHOLDER_kpi_3": "...",
    "PLACEHOLDER_kpi_4": "...",
}
# from your_snowflake_utils import run_query
# ================================

REL_TOL = 1e-6   # 相对误差容忍(浮点聚合顺序差异)


def stage_a_dry_run(builder: KPIQueryBuilder) -> None:
    print("=" * 60, "\nStage A — 干跑\n")
    kpis = list(LEGACY_QUERIES.keys())
    try:
        sql, params = builder.build(
            TEST_ENODEB, TEST_START, TEST_END, kpis, granularity="day"
        )
    except UnknownKPIError as e:
        print("名字解析失败(先修 LEGACY_QUERIES 里的名字或 registry):")
        print(e.message)
        return
    print(sql, "\n\nparams:", params)
    print("\n人工 review 重点: 比率型是否为 SUM/NULLIF(SUM), 计数型是否纯 SUM,")
    print("别名是否为 snake_case, 公式与 xlsx 原文是否一致.")

    # 顺手验证模糊纠错路径
    try:
        builder.build(TEST_ENODEB, TEST_START, TEST_END, ["rrc conected users"])
    except UnknownKPIError as e:
        print("\n[纠错路径演示] agent 将收到:\n", e.message)


def stage_b_reconcile(builder: KPIQueryBuilder) -> None:
    from your_snowflake_utils import run_query  # noqa: 占位 import

    print("=" * 60, "\nStage B — 新旧对账\n")
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
    print("\n对账结果:", "全部一致 — builder 可信" if all_pass else "存在差异 — 检查公式翻译")


if __name__ == "__main__":
    builder = KPIQueryBuilder()
    stage_a_dry_run(builder)
    if RUN_LIVE:
        stage_b_reconcile(builder)
    else:
        print("\n(RUN_LIVE=False, 跳过 Stage B; 填好占位符后置 True 跑对账)")
