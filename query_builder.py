"""Step 3 - Query builder.

Agent-side contract: the agent supplies KPI names only (display_name or
kpi_id, case/whitespace-insensitive), plus enodeb + time window + a
TWO-DIMENSIONAL granularity:
    time_granularity : day | hour | 15min
    spatial_level    : cell | enodeb
and an optional cell filter. This module resolves names (with fuzzy
correction), assembles the SELECT block from registry formulas, and returns
a parameterized SQL statement. The agent never touches SQL text.

All KPIs are ratio-type: SUM(numerator)/NULLIF(SUM(denominator),0) inside
each GROUP BY group, so aggregation is correct (ratio of sums) at any
time x spatial granularity automatically.

See __main__ at the bottom for a dry-run example.
"""

import difflib
import json
import re
import unicodedata

# ============ PLACEHOLDERS: edit to match your environment ============
REGISTRY_PATH = "kpi_registry.json"
KPI_TABLE = "MY_DB.MY_SCHEMA.PLACEHOLDER_KPI_RAW_TABLE"
COL_ENODEB = "PLACEHOLDER_ENODEB_ID"     # eNodeB identifier column
COL_CELL = "PLACEHOLDER_CELL_ID"         # cell identifier column
COL_TS = "PLACEHOLDER_EVENT_TS"          # timestamp column (15-min raw data)
# ======================================================================

TIME_GRAN_SQL = {
    "day":  f"DATE_TRUNC('DAY', {COL_TS})",
    "hour": f"DATE_TRUNC('HOUR', {COL_TS})",
    "15min": f"TIME_SLICE({COL_TS}, 15, 'MINUTE')",
}
SPATIAL_LEVELS = ("cell", "enodeb")

# Two-dimensional cost/quota policy: (time_granularity, spatial_level).
# Enforced by the tool-wrapper layer via a budget ledger; values here are
# starting points -- tune against real query latency/cost.
GRANULARITY_POLICY = {
    ("day", "enodeb"):   {"max_calls": None, "cost": 1},
    ("day", "cell"):     {"max_calls": None, "cost": 2},
    ("hour", "enodeb"):  {"max_calls": 20,   "cost": 3},
    ("hour", "cell"):    {"max_calls": 20,   "cost": 5},
    ("15min", "enodeb"): {"max_calls": 8,    "cost": 8},
    ("15min", "cell"):   {"max_calls": 8,    "cost": 13},
}


class UnknownKPIError(Exception):
    """Raised when name resolution fails; .message is returned to the agent
    verbatim to trigger self-correction (the L1 retry loop)."""

    def __init__(self, unknown, suggestions):
        self.unknown = unknown
        self.suggestions = suggestions
        lines = [f"Unknown KPI(s): {unknown}"]
        for name, cands in suggestions.items():
            if cands:
                lines.append(f"  '{name}' -- did you mean: {cands} ?")
        self.message = "\n".join(lines)
        super().__init__(self.message)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


class KPIQueryBuilder:
    def __init__(self, registry_path: str = REGISTRY_PATH):
        with open(registry_path, encoding="utf-8") as f:
            self.registry = json.load(f)
        # Both display_name and kpi_id map (normalized) to kpi_id, so
        # resolution is case- and whitespace-insensitive.
        self._lookup: dict = {}
        for kid, meta in self.registry.items():
            if not meta.get("valid", False):
                continue
            self._lookup[_norm(kid)] = kid
            self._lookup[_norm(meta["display_name"])] = kid

    # ---------- name resolution ----------
    def resolve(self, names):
        resolved, unknown, suggestions = [], [], {}
        for name in names:
            kid = self._lookup.get(_norm(name))
            if kid:
                if kid not in resolved:
                    resolved.append(kid)
            else:
                unknown.append(name)
                suggestions[name] = difflib.get_close_matches(
                    _norm(name), list(self._lookup.keys()), n=3, cutoff=0.6
                )
        if unknown:
            raise UnknownKPIError(unknown, suggestions)
        return resolved

    # ---------- SQL assembly ----------
    def _select_expr(self, kid: str) -> str:
        meta = self.registry[kid]
        num, den = meta["numerator_sql"], meta["denominator_sql"]
        if den:  # ratio KPI: ratio of sums, never average of ratios
            return f"SUM({num}) / NULLIF(SUM({den}), 0) AS {kid}"
        return f"SUM({num}) AS {kid}"   # defensive; all KPIs are ratio-type

    def build(self, start, end, kpi_names, cells,
              time_granularity="day", spatial_level="cell"):
        """Build one parameterized query. Scope is ALWAYS a cell list.

        Cell ids are globally unique in this deployment, so cells are the
        single scope primitive. Site-level scope = pass all cells of that
        site (cell<->site mapping comes from the attribute data).

        Args:
            start, end: time window (end exclusive).
            kpi_names: list of KPI names (display_name or kpi_id, any case).
            cells: list of globally-unique cell ids (single id also accepted).
            time_granularity: 'day' | 'hour' | '15min'.
            spatial_level: 'cell'   -> one row per cell per time bucket;
                           'enodeb' -> the selected cells grouped by their
                                       owning site (num & den summed across
                                       each site's cells before dividing).

        Returns:
            (sql, params)
        """
        if time_granularity not in TIME_GRAN_SQL:
            raise ValueError(f"time_granularity must be one of {list(TIME_GRAN_SQL)}")
        if spatial_level not in SPATIAL_LEVELS:
            raise ValueError(f"spatial_level must be one of {SPATIAL_LEVELS}")
        if isinstance(cells, str):
            cells = [cells]
        if not cells:
            raise ValueError("scope required: provide a non-empty cell list")

        kids = self.resolve(kpi_names)
        select_block = ",\n       ".join(self._select_expr(k) for k in kids)

        dims = [COL_ENODEB] + ([COL_CELL] if spatial_level == "cell" else [])
        n_groups = len(dims) + 1   # dimension columns + time bucket

        params = {"start": start, "end": end}
        ph = ", ".join(f"%(cell_{i})s" for i in range(len(cells)))
        params.update({f"cell_{i}": c for i, c in enumerate(cells)})

        sql = (
            f"SELECT {', '.join(dims)},\n"
            f"       {TIME_GRAN_SQL[time_granularity]} AS bucket,\n"
            f"       {select_block}\n"
            f"FROM   {KPI_TABLE}\n"
            f"WHERE  {COL_CELL} IN ({ph})\n"
            f"  AND  {COL_TS} >= %(start)s AND {COL_TS} < %(end)s\n"
            f"GROUP BY {', '.join(str(i) for i in range(1, n_groups + 1))}\n"
            f"ORDER BY bucket"
        )
        return sql, params

if __name__ == "__main__":
    # Dry run: prints generated SQL without connecting to Snowflake.
    b = KPIQueryBuilder()
    try:
        # 1. target-cell baseline: single cell, (day, cell)
        sql, params = b.build(
            start="2026-05-01", end="2026-05-29",
            kpi_names=["RRC Connected Users"],
            cells="CELL_X",
            time_granularity="day", spatial_level="cell",
        )
        print(sql, "\n", params, "\n", "-" * 50)

        # 2. neighbor cells from a coverage scan, per-cell hourly
        sql, params = b.build(
            start="2026-05-20", end="2026-05-22",
            kpi_names=["dl_prb_utilization"],
            cells=["CELL_A1", "CELL_B2", "CELL_C3"],
            time_granularity="hour", spatial_level="cell",
        )
        print(sql, "\n", params, "\n", "-" * 50)

        # 3. same cells grouped by owning site: (hour, enodeb)
        sql, params = b.build(
            start="2026-05-20", end="2026-05-22",
            kpi_names=["dl_prb_utilization"],
            cells=["CELL_A1", "CELL_B2", "CELL_C3"],
            time_granularity="hour", spatial_level="enodeb",
        )
        print(sql, "\n", params)
    except UnknownKPIError as e:
        print("Message the agent would receive:\n", e.message)
