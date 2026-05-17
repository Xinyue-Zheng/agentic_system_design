import sys, os
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
from mcp_server.server import get_kpi_history, get_kpi_timeseries
from collections import defaultdict
import json

START = "2026-04-17T10:31:15Z"
END   = "2026-04-17T20:58:56Z"
neighbors = ["USID_01", "USID_25", "USID_43", "USID_29", "USID_45", "USID_10"]

lost_traffic = 90.4748  # S0+S2 baselines from get_kpi_history(USID_09)

results = {}
for n in neighbors:
    hist = get_kpi_history(n)
    ts   = get_kpi_timeseries(n, START, END)

    by_sec_hist = defaultdict(list)
    for r in hist:
        by_sec_hist[r['sector_id']].append(r['throughput_dl_mbps'])
    hist_avg = sum(sum(v)/len(v) for v in by_sec_hist.values() if v)

    by_sec_ts = defaultdict(list)
    for r in ts:
        by_sec_ts[r['sector_id']].append(r['throughput_dl_mbps'])
    curr_load = sum(sum(v)/len(v) for v in by_sec_ts.values() if v)

    remaining = hist_avg - curr_load

    if remaining > lost_traffic * 1.2:
        feasibility = "sufficient"
    elif remaining >= 0:
        feasibility = "marginal"
    else:
        feasibility = "insufficient"

    results[n] = {
        "hist_avg_mbps": round(hist_avg, 4),
        "current_load_mbps": round(curr_load, 4),
        "remaining_capacity_mbps": round(remaining, 2),
        "absorption_feasibility": feasibility
    }

print(json.dumps(results, indent=2))
