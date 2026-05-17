import os, sys, json
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
from mcp_server.server import get_kpi_history
from collections import defaultdict

outage_hours = set(range(10, 21))  # hours 10..20

def summarize_usid(usid):
    hist = get_kpi_history(usid)
    by_sector = defaultdict(list)
    by_sector_vol = defaultdict(list)
    for r in hist:
        h = int(r['timestamp_utc'][11:13])
        if h in outage_hours:
            by_sector[r['sector_id']].append(r['throughput_dl_mbps'])
            by_sector_vol[r['sector_id']].append(r['volume_dl_gb'])
    result = {}
    for sid in sorted(by_sector):
        vals = by_sector[sid]
        vols = by_sector_vol[sid]
        avg_mbps = sum(vals)/len(vals) if vals else 0
        sorted_vals = sorted(vals)
        n = len(sorted_vals)
        p90_idx = int(n * 0.9)
        p90_mbps = sorted_vals[min(p90_idx, n-1)] if sorted_vals else 0
        avg_vol = sum(vols)/len(vols) if vols else 0
        result[sid] = {
            'avg_mbps': round(avg_mbps, 4),
            'p90_mbps': round(p90_mbps, 4),
            'avg_vol_gb': round(avg_vol, 4),
            'n_records': n
        }
    return result

usids = ['USID_09', 'USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10']
output = {}
for u in usids:
    output[u] = summarize_usid(u)

print(json.dumps(output, indent=2))
