"""Step 1 — 体检脚本.

在写 registry 之前先了解公式表的真实形态。只读 xlsx、只打印报告,
不写任何文件; 仅当 CHECK_SCHEMA=True 时连一次 Snowflake 查表结构。

用法:  python inspect_formulas.py
"""

import re
import unicodedata
from collections import Counter

import pandas as pd

# ============ 占位区: 按你的真实情况修改 ============
XLSX_PATH = "PLACEHOLDER_kpi_formulas.xlsx"
SHEET_NAME = 0                      # sheet 名或序号
COL_KPI = "PLACEHOLDER_kpi_name"    # KPI 名字所在列的表头
COL_NUM = "PLACEHOLDER_nominator"   # 分子表达式列的表头
COL_DEN = "PLACEHOLDER_denominator" # 分母表达式列的表头

CHECK_SCHEMA = False                # True 则对账 Snowflake 真实列名
SNOWFLAKE_TABLE = "MY_DB.MY_SCHEMA.PLACEHOLDER_KPI_RAW_TABLE"
# 你已写好的下载函数, 假设签名为 run_query(sql, params=None) -> pd.DataFrame
# from your_snowflake_utils import run_query
# ====================================================

SQL_KEYWORDS = {
    "sum", "avg", "min", "max", "count", "case", "when", "then", "else",
    "end", "and", "or", "not", "null", "nullif", "if", "iff", "div0",
    "coalesce", "greatest", "least", "abs", "round",
}
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def extract_identifiers(expr: str) -> set:
    """从公式里抽出疑似列名的标识符(排除 SQL 关键字/函数名/纯数字)."""
    if not isinstance(expr, str):
        return set()
    return {
        tok for tok in IDENT_RE.findall(expr)
        if tok.lower() not in SQL_KEYWORDS
    }


def derive_kpi_id(name: str) -> str:
    """display_name -> snake_case kpi_id 的确定性派生(与 build_registry 保持一致)."""
    s = unicodedata.normalize("NFKC", str(name)).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def find_suspicious_chars(expr: str) -> set:
    """找出公式里的非 ASCII 字符(全角符号、×、÷、长破折号等 Excel 常见残留)."""
    if not isinstance(expr, str):
        return set()
    return {ch for ch in expr if ord(ch) > 127}


def main() -> None:
    df = pd.read_excel(XLSX_PATH, sheet_name=SHEET_NAME, engine="openpyxl")

    print("=" * 60)
    print(f"行数: {len(df)}    列: {list(df.columns)}")
    expected = [COL_KPI, COL_NUM, COL_DEN]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        print(f"!! 期望的列不存在: {missing} — 先改占位区的表头再继续")
        return

    # --- 1. 空值情况 ---
    print("\n[1] 空值统计")
    for c in expected:
        n_null = df[c].isna().sum()
        n_blank = (df[c].astype(str).str.strip() == "").sum()
        print(f"  {c}: NaN={n_null}, 空白串={n_blank}")
    no_den = df[df[COL_DEN].isna() | (df[COL_DEN].astype(str).str.strip() == "")]
    print(f"  无分母的 KPI(计数型候选): {len(no_den)} 个")
    if len(no_den):
        print("  示例:", no_den[COL_KPI].head(5).tolist())

    # --- 2. 重名与 kpi_id 碰撞 ---
    print("\n[2] 重名检查")
    dup = df[COL_KPI].astype(str).str.strip().str.lower()
    dup_names = dup[dup.duplicated()].unique()
    print(f"  归一化后重名: {len(dup_names)} 个", list(dup_names[:5]))
    ids = df[COL_KPI].map(derive_kpi_id)
    collisions = ids[ids.duplicated()].unique()
    print(f"  kpi_id 派生碰撞: {len(collisions)} 个", list(collisions[:5]))

    # --- 3. 公式形态 ---
    print("\n[3] 公式形态")
    all_tokens: Counter = Counter()
    bad_paren, weird = [], {}
    for _, row in df.iterrows():
        for c in (COL_NUM, COL_DEN):
            expr = row[c]
            if not isinstance(expr, str):
                continue
            all_tokens.update(extract_identifiers(expr))
            if expr.count("(") != expr.count(")"):
                bad_paren.append((row[COL_KPI], c))
            sus = find_suspicious_chars(expr)
            if sus:
                weird.setdefault(row[COL_KPI], set()).update(sus)
    print(f"  去重后的列名 token 总数: {len(all_tokens)}")
    print(f"  括号不配对的公式: {len(bad_paren)} 条", bad_paren[:5])
    print(f"  含非 ASCII 字符的 KPI: {len(weird)} 个")
    for k, v in list(weird.items())[:5]:
        print(f"    {k}: {sorted(v)}")
    print("  出现频率最高的 20 个 token:")
    for tok, n in all_tokens.most_common(20):
        print(f"    {tok}: {n}")

    # --- 4. 可选: 与 Snowflake schema 对账 ---
    if CHECK_SCHEMA:
        from your_snowflake_utils import run_query  # noqa: 占位 import
        db, schema, table = SNOWFLAKE_TABLE.split(".")
        cols_df = run_query(
            f"SELECT column_name FROM {db}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE table_schema = %(s)s AND table_name = %(t)s",
            {"s": schema, "t": table},
        )
        real_cols = {c.lower() for c in cols_df["COLUMN_NAME"]}
        unknown = {t for t in all_tokens if t.lower() not in real_cols}
        print(f"\n[4] schema 对账: 公式引用但表里不存在的 token: {len(unknown)} 个")
        for t in sorted(unknown)[:30]:
            print(f"    {t}")

    print("\n体检完成 — 把这份输出贴回来, 我们据此定 build_registry 的清洗规则.")


if __name__ == "__main__":
    main()
