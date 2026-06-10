"""Step 2 - Registry builder.

Converts the KPI formula spreadsheet (xlsx) into:
  - kpi_registry.json : machine-readable registry used by the query builder
  - kpi_menu.md       : grouped KPI menu to inject into the agent prompt

Re-run only when the formula spreadsheet changes. At runtime the system
reads the registry only and never touches the xlsx.

Usage:  python build_registry.py
"""

import json
import re
import shutil
import unicodedata
import zipfile

import pandas as pd

# ============ PLACEHOLDERS: edit to match your environment ============
XLSX_PATH = "PLACEHOLDER_kpi_formulas.xlsx"
SHEET_NAME = 0
COL_KPI = "PLACEHOLDER_kpi_name"
COL_NUM = "PLACEHOLDER_nominator"
COL_DEN = "PLACEHOLDER_denominator"

OUT_REGISTRY = "kpi_registry.json"
OUT_MENU = "kpi_menu.md"

CHECK_SCHEMA = False                # if True, flag KPIs referencing columns missing from the table
SNOWFLAKE_TABLE = "MY_DB.MY_SCHEMA.PLACEHOLDER_KPI_RAW_TABLE"
# from your_snowflake_utils import run_query
# ======================================================================

# Keyword -> category rules (menu grouping only; never used in SQL).
# Adjust patterns to your KPI naming conventions.
CATEGORY_RULES = [
    (r"rrc|erab|setup|access|attempt", "accessibility"),
    (r"drop|abnormal|release|retain", "retainability"),
    (r"handover|\bho\b|x2|mobility", "mobility"),
    (r"throughput|thp|thrp|latency", "quality"),
    (r"prb|utilization|util|cce|load", "resource"),
    (r"volume|traffic|data|byte|user", "traffic"),
]

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SQL_KEYWORDS = {
    "sum", "avg", "min", "max", "count", "case", "when", "then", "else",
    "end", "and", "or", "not", "null", "nullif", "if", "iff", "div0",
    "coalesce", "greatest", "least", "abs", "round",
}
# Common non-SQL characters left behind by Excel / export tools
CHAR_FIXES = {"\u00d7": "*", "\u00f7": "/", "\u2013": "-", "\u2014": "-",
              "\uff08": "(", "\uff09": ")", "\uff0a": "*", "\uff0c": ",",
              "\uff05": "%", "\u00a0": " "}

MINIMAL_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="1"><font/></fonts>'
    '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
    '<cellXfs count="1"><xf/></cellXfs></styleSheet>'
)


def strip_styles(src: str, dst: str) -> str:
    """Replace a malformed styles.xml inside the xlsx with a minimal valid one."""
    shutil.copy(src, dst)
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for item in zin.namelist():
            data = MINIMAL_STYLES.encode() if item == "xl/styles.xml" else zin.read(item)
            zout.writestr(item, data)
    return dst


def load_xlsx(path: str, sheet=0) -> pd.DataFrame:
    """Read xlsx robustly, in order of preference:
    1. pandas calamine engine (pandas >= 2.2)
    2. python_calamine directly (works on any pandas version)
    3. openpyxl
    4. openpyxl on a style-stripped copy (handles malformed Fill styles)
    """
    try:  # 1. pandas >= 2.2 with python-calamine installed
        return pd.read_excel(path, sheet_name=sheet, engine="calamine")
    except Exception:
        pass
    try:  # 2. python-calamine directly, bypassing the pandas engine check
        from python_calamine import CalamineWorkbook
        wb = CalamineWorkbook.from_path(path)
        ws = (wb.get_sheet_by_index(sheet) if isinstance(sheet, int)
              else wb.get_sheet_by_name(sheet))
        rows = ws.to_python()
        return pd.DataFrame(rows[1:], columns=[str(c) for c in rows[0]])
    except Exception:
        pass
    try:  # 3. plain openpyxl
        return pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    except Exception:
        # 4. strip malformed styles.xml, then retry openpyxl
        fixed = strip_styles(path, path.replace(".xlsx", "_fixed.xlsx"))
        return pd.read_excel(fixed, sheet_name=sheet, engine="openpyxl")


def derive_kpi_id(name: str) -> str:
    """Deterministically derive a snake_case kpi_id from the display name."""
    s = unicodedata.normalize("NFKC", str(name)).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


def normalize_expr(expr):
    """Clean a formula: trim, fix special characters, collapse whitespace.

    Returns None for empty values. A denominator of "1" / "-" / blank is
    treated as 'no denominator' (counter-type KPI) -- adjust if your sheet
    uses a different convention.
    """
    if expr is None or (isinstance(expr, float) and pd.isna(expr)):
        return None
    s = str(expr).strip()
    if not s or s in {"-", "1"} or s.lower() in {"nan", "none"}:
        return None
    for bad, good in CHAR_FIXES.items():
        s = s.replace(bad, good)
    return re.sub(r"\s+", " ", s)


def extract_identifiers(expr: str) -> set:
    """Extract candidate column names (excluding SQL keywords/functions)."""
    return {t for t in IDENT_RE.findall(expr) if t.lower() not in SQL_KEYWORDS}


def assign_category(display_name: str) -> str:
    low = display_name.lower()
    for pattern, cat in CATEGORY_RULES:
        if re.search(pattern, low):
            return cat
    return "other"


def main() -> None:
    df = load_xlsx(XLSX_PATH, SHEET_NAME)

    real_cols = None
    if CHECK_SCHEMA:
        from your_snowflake_utils import run_query  # placeholder import
        db, schema, table = SNOWFLAKE_TABLE.split(".")
        cols_df = run_query(
            f"SELECT column_name FROM {db}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE table_schema = %(s)s AND table_name = %(t)s",
            {"s": schema, "t": table},
        )
        real_cols = {c.lower() for c in cols_df["COLUMN_NAME"]}

    registry: dict = {}
    errors: list = []

    for idx, row in df.iterrows():
        display = str(row[COL_KPI]).strip()
        if not display or display.lower() == "nan":
            errors.append(f"row {idx}: empty KPI name, skipped")
            continue

        kid = derive_kpi_id(display)
        if kid in registry:
            errors.append(
                f"row {idx}: kpi_id collision '{kid}' "
                f"(existing '{registry[kid]['display_name']}', current '{display}') "
                f"-- needs manual resolution"
            )
            continue

        num = normalize_expr(row[COL_NUM])
        den = normalize_expr(row[COL_DEN])

        issues: list = []
        if num is None:
            issues.append("numerator is empty")
        for label, expr in (("numerator", num), ("denominator", den)):
            if expr and expr.count("(") != expr.count(")"):
                issues.append(f"{label} has unbalanced parentheses")
        if real_cols is not None:
            refs = set()
            for expr in (num, den):
                if expr:
                    refs |= extract_identifiers(expr)
            unknown = {t for t in refs if t.lower() not in real_cols}
            if unknown:
                issues.append(f"references columns missing from table: {sorted(unknown)}")

        registry[kid] = {
            "display_name": display,
            "numerator_sql": num,
            "denominator_sql": den,        # None = counter-type KPI, plain SUM
            "category": assign_category(display),
            "valid": len(issues) == 0,
            "issues": issues,
        }

    with open(OUT_REGISTRY, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    # ----- Build the grouped menu for the agent prompt (valid KPIs only) -----
    by_cat: dict = {}
    for kid, meta in registry.items():
        if meta["valid"]:
            by_cat.setdefault(meta["category"], []).append(
                f"- `{kid}` -- {meta['display_name']}"
            )
    with open(OUT_MENU, "w", encoding="utf-8") as f:
        f.write("# KPI menu (refer by name; aggregation formulas applied automatically)\n\n")
        for cat in sorted(by_cat):
            f.write(f"## {cat}\n" + "\n".join(sorted(by_cat[cat])) + "\n\n")

    n_valid = sum(m["valid"] for m in registry.values())
    print(f"registry: {len(registry)} KPIs, valid={n_valid}")
    print(f"written: {OUT_REGISTRY}, {OUT_MENU}")
    if errors:
        print(f"\n{len(errors)} rows need manual attention:")
        for e in errors:
            print(" ", e)
    invalid = {k: m["issues"] for k, m in registry.items() if not m["valid"]}
    if invalid:
        print(f"\n{len(invalid)} KPIs marked invalid (excluded from menu):")
        for k, iss in list(invalid.items())[:20]:
            print(f"  {k}: {iss}")


if __name__ == "__main__":
    main()
