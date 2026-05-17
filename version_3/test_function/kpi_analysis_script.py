import sys, json, statistics
sys.path.insert(0, '.')
from mcp_server.server import get_kpi_history

OUTAGE_HOURS = set(range(10, 21))

def hour_of(ts):
    return int(ts[11:13])

def site_stats_window(usid):
    records = get_kpi_history(usid)
    filtered = [r for r in records if hour_of(r['timestamp_utc']) in OUTAGE_HOURS]
    sectors = {}
    for r in filtered:
        sid = r['sector_id']
        if sid not in sectors:
            sectors[sid] = {'mbps': [], 'vol': []}
        sectors[sid]['mbps'].append(r['throughput_dl_mbps'])
        sectors[sid]['vol'].append(r['volume_dl_gb'])
    result = {}
    for sid, data in sectors.items():
        result[sid] = {
            'avg_mbps': round(statistics.mean(data['mbps']), 4),
            'p90_mbps': round(sorted(data['mbps'])[int(len(data['mbps']) * 0.90)], 4),
            'avg_vol_gb': round(statistics.mean(data['vol']), 6),
            'n': len(data['mbps'])
        }
    site_avg_mbps = sum(v['avg_mbps'] for v in result.values())
    site_p90_mbps = sum(v['p90_mbps'] for v in result.values())
    site_avg_vol = sum(v['avg_vol_gb'] for v in result.values())
    return {'sectors': result, 'site_avg_mbps': round(site_avg_mbps, 4), 'site_p90_mbps': round(site_p90_mbps, 4), 'site_avg_vol_gb': round(site_avg_vol, 6)}

def site_hourly_stats(usid):
    records = get_kpi_history(usid)
    filtered = [r for r in records if hour_of(r['timestamp_utc']) in OUTAGE_HOURS]
    hourly = {}
    for r in filtered:
        h = hour_of(r['timestamp_utc'])
        if h not in hourly:
            hourly[h] = {'mbps': [], 'vol': []}
        hourly[h]['mbps'].append(r['throughput_dl_mbps'])
        hourly[h]['vol'].append(r['volume_dl_gb'])
    result = {}
    for h in sorted(hourly.keys()):
        mbps_list = hourly[h]['mbps']
        vol_list = hourly[h]['vol']
        result[h] = {
            'avg_mbps': round(statistics.mean(mbps_list), 4),
            'p90_mbps': round(sorted(mbps_list)[int(len(mbps_list) * 0.90)], 4),
            'avg_vol_gb': round(statistics.mean(vol_list), 6),
            'n': len(mbps_list)
        }
    return result

usids = ['USID_09', 'USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10']
print("=== WINDOW STATS ===")
for u in usids:
    stats = site_stats_window(u)
    print(f"{u}: {json.dumps(stats)}")

print("\n=== HOURLY STATS (neighbors only) ===")
for u in usids[1:]:
    h_stats = site_hourly_stats(u)
    print(f"{u}_hourly: {json.dumps(h_stats)}")
