import sys, os
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
import datetime
from collections import defaultdict
from mcp_server.server import get_kpi_history

OUTAGE_HOURS = list(range(10, 21))
OUTAGE_DATE = datetime.date(2026, 4, 17)


def agg_by_ts(records, sectors=None, hours=None):
    by_ts = defaultdict(float)
    for r in records:
        sid = r['sector_id']
        if sectors and sid not in sectors:
            continue
        ts = r['timestamp_utc']
        hour = int(ts[11:13])
        if hours and hour not in hours:
            continue
        by_ts[ts] += r['throughput_dl_mbps']
    return by_ts


def agg_stats(records, sectors=None, hours=None):
    by_ts = agg_by_ts(records, sectors, hours)
    vals = list(by_ts.values())
    if not vals:
        return None
    arr = sorted(vals)
    n = len(arr)
    return {"mean": round(sum(arr)/n, 2), "p75": round(arr[int(0.75*n)], 2),
            "p90": round(arr[int(0.90*n)], 2), "n": n}


hist09 = get_kpi_history("USID_09")
all_sectors = agg_stats(hist09, hours=OUTAGE_HOURS)
print(f"Full USID_09 (all 3 sectors) aggregate: {all_sectors}")

s0_s2 = agg_stats(hist09, sectors=["USID_09_S0", "USID_09_S2"], hours=OUTAGE_HOURS)
print(f"S0+S2 only: {s0_s2}")

s1_only = agg_stats(hist09, sectors=["USID_09_S1"], hours=OUTAGE_HOURS)
print(f"S1 only (active): {s1_only}")

loss_ratio = s0_s2['mean'] / all_sectors['mean']
print(f"loss_ratio (S0+S2 / all): {round(loss_ratio, 2)}")
