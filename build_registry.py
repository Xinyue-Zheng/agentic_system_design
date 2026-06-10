"""Step 2 — Registry 构建脚本.

xlsx 公式表 -> kpi_registry.json (机器用) + kpi_menu.md (注入 agent prompt 用).
只在公式表更新时重跑; 系统运行时只读 registry, 不再碰 xlsx.

用法:  python build_registry.py
"""

import json
import re
import unicodedata

import pandas as pd

# ============ 占位区 ============
XLSX_PATH = "PLACEHOLDER_kpi_formulas.xlsx"
SHEET_NAME = 0
COL_KPI = "PLACEHOLDER_kpi_name"
COL_NUM = "PLACEHOLDER_nominator"
COL_DEN = "PLACEHOLDER_denominator"

OUT_REGISTRY = "kpi_registry.json"
OUT_MENU = "kpi_menu.md"

CHECK_SCHEMA = False                # True 则把引用了不存在列的 KPI 标 invalid
SNOWFLAKE_TABLE = "MY_DB.MY_SCHEMA.PLACEHOLDER_KPI_RAW_TABLE"
# from your_snowflake_utils import run_query
# ================================

# 名字关键词 -> 分类(给 agent 菜单分组用; 不参与 SQL)。按你的命名习惯增删。
CATEGORY_RULES = [
    (r"rrc|erab|setup|access|attempt", "accessibility 接入"),
    (r"drop|abnormal|release|retain", "retainability 保持"),
    (r"handover|\bho\b|x2|mobility", "mobility 移动性"),
    (r"throughput|thp|thrp|latency", "quality 速率与质量"),
    (r"prb|utilization|util|cce|load", "resource 资源利用"),
    (r"volume|traffic|data|byte|user", "traffic 流量与用户数"),
]

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SQL_KEYWORDS = {
    "sum", "avg", "min", "max", "count", "case", "when", "then", "else",
    "end", "and", "or", "not", "null", "nullif", "if", "iff", "div0",
    "coalesce", "greatest", "least", "abs", "round",
}
# Excel 常见非法字符 -> SQL 等价物
CHAR_FIXES = {"×": "*", "÷": "/", "–": "-", "—": "-", "（": "(", "）": ")",
              "＊": "*", "，": ",", "％": "%", "\u00a0": " "}


def derive_kpi_id(name: str) -> str:
    s = unicodedata.normalize("NFKC", str(name)).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def normalize_expr(expr) -> str | None:
    """清洗公式: 去首尾空白、替换全角/特殊符号、压缩空格. 空值返回 None."""
    if expr is None or (isinstance(expr, float) and pd.isna(expr)):
        return None
    s = str(expr).strip()
    if not s or s.lower() in {"nan", "none", "-", "1"}:
        # 分母填 "1" 视为无分母(纯求和), 按你表里的真实约定调整
        return None if s in {"", "-", "1"} or s.lower() in {"nan", "none"} else s
    for bad, good in CHAR_FIXES.items():
        s = s.replace(bad, good)
    return re.sub(r"\s+", " ", s)


def extract_identifiers(expr: str) -> set:
    return {t for t in IDENT_RE.findall(expr) if t.lower() not in SQL_KEYWORDS}


def assign_category(display_name: str) -> str:
    low = display_name.lower()
    for pattern, cat in CATEGORY_RULES:
        if re.search(pattern, low):
            return cat
    return "other 其他"


def main() -> None:
    df = pd.read_excel(XLSX_PATH, sheet_name=SHEET_NAME, engine="openpyxl")

    real_cols = None
    if CHECK_SCHEMA:
        from your_snowflake_utils import run_query  # noqa: 占位 import
        db, schema, table = SNOWFLAKE_TABLE.split(".")
        cols_df = run_query(
            f"SELECT column_name FROM {db}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE table_schema = %(s)s AND table_name = %(t)s",
            {"s": schema, "t": table},
        )
        real_cols = {c.lower() for c in cols_df["COLUMN_NAME"]}

    registry: dict = {}
    errors: list[str] = []

    for idx, row in df.iterrows():
        display = str(row[COL_KPI]).strip()
        if not display or display.lower() == "nan":
            errors.append(f"row {idx}: KPI 名为空, 跳过")
            continue

        kid = derive_kpi_id(display)
        if kid in registry:
            errors.append(
                f"row {idx}: kpi_id 碰撞 '{kid}' "
                f"(已存在 '{registry[kid]['display_name']}', 当前 '{display}') — 需人工裁决"
            )
            continue

        num = normalize_expr(row[COL_NUM])
        den = normalize_expr(row[COL_DEN])

        issues: list[str] = []
        if num is None:
            issues.append("分子为空")
        for label, expr in (("num", num), ("den", den)):
            if expr and expr.count("(") != expr.count(")"):
                issues.append(f"{label} 括号不配对")
        if real_cols is not None:
            refs = set()
            for expr in (num, den):
                if expr:
                    refs |= extract_identifiers(expr)
            unknown = {t for t in refs if t.lower() not in real_cols}
            if unknown:
                issues.append(f"引用了表中不存在的列: {sorted(unknown)}")

        registry[kid] = {
            "display_name": display,
            "numerator_sql": num,
            "denominator_sql": den,        # None = 计数型, 纯 SUM
            "category": assign_category(display),
            "valid": len(issues) == 0,
            "issues": issues,
        }

    with open(OUT_REGISTRY, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    # ----- 生成给 agent prompt 用的分组菜单(只含 valid 的 KPI) -----
    by_cat: dict[str, list[str]] = {}
    for kid, meta in registry.items():
        if meta["valid"]:
            by_cat.setdefault(meta["category"], []).append(
                f"- `{kid}` — {meta['display_name']}"
            )
    with open(OUT_MENU, "w", encoding="utf-8") as f:
        f.write("# KPI 菜单 (按名引用, 系统自动套用聚合公式)\n\n")
        for cat in sorted(by_cat):
            f.write(f"## {cat}\n" + "\n".join(sorted(by_cat[cat])) + "\n\n")

    n_valid = sum(m["valid"] for m in registry.values())
    print(f"registry: {len(registry)} 个 KPI, 其中 valid={n_valid}")
    print(f"写出: {OUT_REGISTRY}, {OUT_MENU}")
    if errors:
        print(f"\n需要人工处理的 {len(errors)} 条:")
        for e in errors:
            print(" ", e)
    invalid = {k: m["issues"] for k, m in registry.items() if not m["valid"]}
    if invalid:
        print(f"\n标为 invalid 的 {len(invalid)} 个 KPI(不进菜单):")
        for k, iss in list(invalid.items())[:20]:
            print(f"  {k}: {iss}")


if __name__ == "__main__":
    main()
