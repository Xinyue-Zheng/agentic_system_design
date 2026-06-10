"""Step 3 - Query builder.

Agent-side contract: the agent supplies KPI names only (display_name or
kpi_id, case/whitespace-insensitive), plus enodeb + time window + granularity.
This module resolves names (with fuzzy correction), assembles the SELECT
block from registry formulas, and returns a parameterized SQL statement.
The agent never touches SQL text.

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

# Granularity ladder: "day" is unrestricted; hour/15min quotas are enforced
# by the wrapper layer via GRANULARITY_POLICY (budget ledger decrements).
GRAN_SQL = {
    "day":  f"DATE_TRUNC('DAY', {COL_TS})",
    "hour": f"DATE_TRUNC('HOUR', {COL_TS})",
    "15min": f"TIME_SLICE({COL_TS}, 15, 'MINUTE')",
}
GRANULARITY_POLICY = {
    "day": {"max_calls": None},
    "hour": {"max_calls": 20},
    "15min": {"max_calls": 8},   # fine granularity only near the outage window
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
        return f"SUM({num}) AS {kid}"   # counter KPI

    def build(self, enodeb, start, end, kpi_names,
              granularity="day", cell_level=True):
        if granularity not in GRAN_SQL:
            raise ValueError(f"granularity must be one of {list(GRAN_SQL)}")
        kids = self.resolve(kpi_names)
        select_block = ",\n       ".join(self._select_expr(k) for k in kids)

        dims = [COL_ENODEB] + ([COL_CELL] if cell_level else [])
        dim_block = ", ".join(dims)
        n_groups = len(dims) + 1  # dimension columns + time bucket

        sql = (
            f"SELECT {dim_block},\n"
            f"       {GRAN_SQL[granularity]} AS bucket,\n"
            f"       {select_block}\n"
            f"FROM   {KPI_TABLE}\n"
            f"WHERE  {COL_ENODEB} = %(enodeb)s\n"
            f"  AND  {COL_TS} >= %(start)s AND {COL_TS} < %(end)s\n"
            f"GROUP BY {', '.join(str(i) for i in range(1, n_groups + 1))}\n"
            f"ORDER BY bucket"
        )
        params = {"enodeb": enodeb, "start": start, "end": end}
        return sql, params

    # ---------- batch variant: same formulas across a set of eNodeBs ----------
    def build_multi(self, enodebs, start, end, kpi_names, granularity="day"):
        sql, params = self.build(enodebs[0], start, end, kpi_names, granularity)
        placeholder_list = ", ".join(f"%(enodeb_{i})s" for i in range(len(enodebs)))
        sql = sql.replace(
            f"{COL_ENODEB} = %(enodeb)s",
            f"{COL_ENODEB} IN ({placeholder_list})",
        )
        params.pop("enodeb")
        params.update({f"enodeb_{i}": e for i, e in enumerate(enodebs)})
        return sql, params


if __name__ == "__main__":
    # Dry run: prints the generated SQL without connecting to Snowflake,
    # for manual review of the assembled statement.
    b = KPIQueryBuilder()
    try:
        sql, params = b.build(
            enodeb="123456",
            start="2026-05-01",
            end="2026-05-29",
            kpi_names=["RRC Connected Users", "dl_prb_utilization"],  # mixed name styles
            granularity="day",
        )
        print(sql)
        print(params)
    except UnknownKPIError as e:
        print("Message the agent would receive:\n", e.message)
