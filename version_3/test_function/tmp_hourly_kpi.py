import os, sys, json
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
from mcp_server.server import get_kpi_history
from collections import defaultdict
import statistics

outage_hours = list(range(10, 21))

def hourly_stats(usid):
    hist = get_kpi_history(usid)
    by_hour = defaultdict(list)
    by_hour_vol = defaultdict(list)
    for r in hist:
        h = int(r['timestamp_utc'][11:13])
        if h in outage_hours:
            by_hour[h].append(r['throughput_dl_mbps'])
            by_hour_vol[h].append(r['volume_dl_gb'])

    result = {}
    for h in outage_hours:
        vals = by_hour[h]
        vols = by_hour_vol[h]
        if not vals:
            result[h] = {'avg_mbps': 0, 'p90_mbps': 0, 'avg_vol_gb': 0, 'n': 0}
            continue
        avg = sum(vals) / len(vals)
        sorted_v = sorted(vals)
        n = len(sorted_v)
        p90_idx = int(n * 0.9)
        p90 = sorted_v[min(p90_idx, n-1)]
        avg_vol = sum(vols) / len(vols)
        result[h] = {
            'avg_mbps': round(avg, 4),
            'p90_mbps': round(p90, 4),
            'avg_vol_gb': round(avg_vol, 6),
            'n': n
        }
    return result

usids = ['USID_09', 'USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10']
output = {}
for u in usids:
    output[u] = hourly_stats(u)

print(json.dumps(output, indent=2))
