import sys, os
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
import json, datetime
from collections import defaultdict
from mcp_server.server import get_kpi_history

OUTAGE_HOURS = list(range(10, 21))
AFFECTED_SECTORS = ["USID_09_S0", "USID_09_S2"]
OUTAGE_DATE = datetime.date(2026, 4, 17)


def agg_vol_by_ts(records, sectors=None, hours=None):
    by_ts = defaultdict(float)
    for r in records:
        sid = r['sector_id']
        if sectors and sid not in sectors:
            continue
        ts = r['timestamp_utc']
        hour = int(ts[11:13])
        if hours and hour not in hours:
            continue
        by_ts[ts] += r['volume_dl_gb']
    return by_ts


def agg_vol_stats(records, sectors=None, hours=None):
    by_ts = agg_vol_by_ts(records, sectors, hours)
    vals = list(by_ts.values())
    if not vals:
        return None
    arr = sorted(vals)
    n = len(arr)
    mean = sum(arr)/n
    p75 = arr[int(0.75*n)]
    p90 = arr[int(0.90*n)]
    return {"mean": round(mean, 4), "p75": round(p75, 4), "p90": round(p90, 4), "n": n}


hist09 = get_kpi_history("USID_09")
vol_stats = agg_vol_stats(hist09, sectors=AFFECTED_SECTORS, hours=OUTAGE_HOURS)
print(f"USID_09 S0+S2 volume_dl_gb stats: {vol_stats}")

NEIGHBORS = ["USID_01", "USID_25", "USID_43", "USID_29", "USID_45", "USID_10"]
for nb in NEIGHBORS:
    hist = get_kpi_history(nb)
    vs = agg_vol_stats(hist, hours=OUTAGE_HOURS)
    print(f"{nb} volume stats: {vs}")
