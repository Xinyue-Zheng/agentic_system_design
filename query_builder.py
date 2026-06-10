"""Step 3 — 查询构建器.

Agent 侧契约: 只给 KPI 名(display_name 或 kpi_id 均可)+ enodeb + 时间窗 + 粒度.
本模块负责: 名字解析(含模糊纠错) -> 按 registry 公式拼 SELECT 块 -> 返回
参数化 SQL. Agent 永远不接触 SQL 文本.

用法示例见文件底部 __main__.
"""

import difflib
import json
import re
import unicodedata

# ============ 占位区 ============
REGISTRY_PATH = "kpi_registry.json"
KPI_TABLE = "MY_DB.MY_SCHEMA.PLACEHOLDER_KPI_RAW_TABLE"
COL_ENODEB = "PLACEHOLDER_ENODEB_ID"     # 表里的 eNodeB 标识列
COL_CELL = "PLACEHOLDER_CELL_ID"         # cell 标识列
COL_TS = "PLACEHOLDER_EVENT_TS"          # 时间戳列(15min 粒度原始数据)
# ================================

# 粒度阶梯: day 不设限; hour/15min 由包装层控制配额(见 GRANULARITY_POLICY)
GRAN_SQL = {
    "day":  f"DATE_TRUNC('DAY', {COL_TS})",
    "hour": f"DATE_TRUNC('HOUR', {COL_TS})",
    "15min": f"TIME_SLICE({COL_TS}, 15, 'MINUTE')",
}
GRANULARITY_POLICY = {
    "day": {"max_calls": None},
    "hour": {"max_calls": 20},
    "15min": {"max_calls": 8},   # 细粒度只允许 outage 窗口附近, 配额由调用方账本扣减
}


class UnknownKPIError(Exception):
    """名字解析失败时抛出; .message 直接回传给 agent 触发自我纠错."""

    def __init__(self, unknown: list[str], suggestions: dict[str, list[str]]):
        self.unknown = unknown
        self.suggestions = suggestions
        lines = [f"未知 KPI: {unknown}"]
        for name, cands in suggestions.items():
            if cands:
                lines.append(f"  '{name}' 是否指: {cands} ?")
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
        # display_name 与 kpi_id 都归一化后指向 kpi_id, 解析时大小写/空格不敏感
        self._lookup: dict[str, str] = {}
        for kid, meta in self.registry.items():
            if not meta.get("valid", False):
                continue
            self._lookup[_norm(kid)] = kid
            self._lookup[_norm(meta["display_name"])] = kid

    # ---------- 名字解析 ----------
    def resolve(self, names: list[str]) -> list[str]:
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

    # ---------- SQL 拼装 ----------
    def _select_expr(self, kid: str) -> str:
        meta = self.registry[kid]
        num, den = meta["numerator_sql"], meta["denominator_sql"]
        if den:  # 比率型: 和的比, 而非比的均值
            return f"SUM({num}) / NULLIF(SUM({den}), 0) AS {kid}"
        return f"SUM({num}) AS {kid}"   # 计数型

    def build(
        self,
        enodeb: str,
        start: str,
        end: str,
        kpi_names: list[str],
        granularity: str = "day",
        cell_level: bool = True,
    ) -> tuple[str, dict]:
        if granularity not in GRAN_SQL:
            raise ValueError(f"granularity 必须是 {list(GRAN_SQL)}")
        kids = self.resolve(kpi_names)
        select_block = ",\n       ".join(self._select_expr(k) for k in kids)

        dims = [COL_ENODEB] + ([COL_CELL] if cell_level else [])
        dim_block = ", ".join(dims)
        n_groups = len(dims) + 1  # 维度列 + 时间桶

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

    # ---------- 邻区批量版: 同公式查一组 cell/enodeb ----------
    def build_multi(
        self,
        enodebs: list[str],
        start: str,
        end: str,
        kpi_names: list[str],
        granularity: str = "day",
    ) -> tuple[str, dict]:
        sql, params = self.build(
            enodebs[0], start, end, kpi_names, granularity
        )
        sql = sql.replace(
            f"{COL_ENODEB} = %(enodeb)s",
            f"{COL_ENODEB} IN (%(enodeb_list)s)".replace(
                "%(enodeb_list)s",
                ", ".join(f"%(enodeb_{i})s" for i in range(len(enodebs))),
            ),
        )
        params.pop("enodeb")
        params.update({f"enodeb_{i}": e for i, e in enumerate(enodebs)})
        return sql, params


if __name__ == "__main__":
    # 干跑演示: 不连 Snowflake, 只打印 SQL — 用来人工 review 拼装是否正确
    b = KPIQueryBuilder()
    try:
        sql, params = b.build(
            enodeb="123456",
            start="2026-05-01",
            end="2026-05-29",
            kpi_names=["RRC Connected Users", "dl_prb_utilization"],  # 混用两种名字
            granularity="day",
        )
        print(sql)
        print(params)
    except UnknownKPIError as e:
        print("agent 应收到的纠错信息:\n", e.message)
