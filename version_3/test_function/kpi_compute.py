import sys, os
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
from mcp_server.server import get_kpi_history
import numpy as np
from collections import defaultdict
import json

OUTAGE_HOURS = set(range(10, 21))
FAILED_SECTORS = {'USID_09_S0', 'USID_09_S2'}
ALL_SECTORS = {'USID_09_S0', 'USID_09_S1', 'USID_09_S2'}
NEIGHBORS = ["USID_01", "USID_25", "USID_43", "USID_29", "USID_45", "USID_10"]

ABSORPTION_FRACTIONS = {
    "USID_01": 0.5714,
    "USID_25": 0.5,
    "USID_43": 0.4286,
    "USID_29": 0.1429,
    "USID_45": 0.119,
    "USID_10": 0.0952,
}

def hour_of(rec):
    ts = rec['timestamp_utc']
    return int(ts[11:13])

hist_09 = get_kpi_history('USID_09')
filtered_09 = [r for r in hist_09 if hour_of(r) in OUTAGE_HOURS]

by_sector = defaultdict(list)
for r in filtered_09:
    by_sector[r['sector_id']].append(r)

sector_stats = {}
for sid, recs in by_sector.items():
    mbps_vals = [r['throughput_dl_mbps'] for r in recs]
    vol_vals = [r['volume_dl_gb'] for r in recs]
    sector_stats[sid] = {
        'avg_mbps': np.mean(mbps_vals),
        'avg_vol_gb': np.mean(vol_vals),
        'n': len(recs)
    }

print("=== USID_09 Sector Stats (outage hours filtered) ===")
for sid, s in sorted(sector_stats.items()):
    print(f"  {sid}: avg_mbps={s['avg_mbps']:.4f}, avg_vol_gb={s['avg_vol_gb']:.4f}, n={s['n']}")

lost_traffic_mbps = sum(sector_stats[s]['avg_mbps'] for s in FAILED_SECTORS if s in sector_stats)
lost_volume_gb = sum(sector_stats[s]['avg_vol_gb'] for s in FAILED_SECTORS if s in sector_stats)
baseline_mbps = sum(sector_stats[s]['avg_mbps'] for s in ALL_SECTORS if s in sector_stats)
loss_ratio = lost_traffic_mbps / baseline_mbps if baseline_mbps > 0 else 0.0

print(f"\nlost_traffic_mbps={lost_traffic_mbps:.4f}")
print(f"lost_volume_gb={lost_volume_gb:.4f}")
print(f"baseline_mbps={baseline_mbps:.4f}")
print(f"loss_ratio={loss_ratio:.4f}")

print("\n=== Neighbor Analysis ===")
neighbor_results = {}
for nusid in NEIGHBORS:
    hist_n = get_kpi_history(nusid)
    filtered_n = [r for r in hist_n if hour_of(r) in OUTAGE_HOURS]

    mbps_all = [r['throughput_dl_mbps'] for r in filtered_n]
    vol_all = [r['volume_dl_gb'] for r in filtered_n]

    if not mbps_all:
        print(f"  {nusid}: NO DATA")
        continue

    baseline_n = float(np.mean(mbps_all))
    p90_n = float(np.percentile(mbps_all, 90))
    baseline_vol_n = float(np.mean(vol_all))

    af = ABSORPTION_FRACTIONS[nusid]
    extra_mbps = lost_traffic_mbps * af
    extra_vol = lost_volume_gb * af
    new_total = baseline_n + extra_mbps

    threshold_85 = p90_n * 0.85
    if new_total <= threshold_85:
        feasibility = "sufficient"
    elif new_total <= p90_n:
        feasibility = "marginal"
    else:
        feasibility = "insufficient"

    neighbor_results[nusid] = {
        "absorption_fraction": af,
        "baseline_mbps": round(baseline_n, 4),
        "p90_mbps": round(p90_n, 4),
        "baseline_vol_gb": round(baseline_vol_n, 4),
        "extra_mbps": round(extra_mbps, 4),
        "extra_vol_gb": round(extra_vol, 4),
        "new_total_mbps": round(new_total, 4),
        "threshold_85pct": round(threshold_85, 4),
        "feasibility": feasibility,
        "n_records": len(filtered_n)
    }
    print(f"  {nusid}: baseline={baseline_n:.4f}, p90={p90_n:.4f}, extra={extra_mbps:.4f}, new_total={new_total:.4f}, 85%={threshold_85:.4f} -> {feasibility}")

feasibilities = [v['feasibility'] for v in neighbor_results.values()]
if any(f == 'sufficient' for f in feasibilities):
    verdict = "no_overload"
elif all(f == 'insufficient' for f in feasibilities):
    verdict = "overload"
else:
    verdict = "marginal_risk"

print(f"\noverload_verdict: {verdict}")

results = {
    "lost_traffic_mbps": round(lost_traffic_mbps, 4),
    "lost_volume_gb": round(lost_volume_gb, 4),
    "baseline_mbps": round(baseline_mbps, 4),
    "loss_ratio": round(loss_ratio, 4),
    "sector_stats": {k: {kk: round(vv, 4) if isinstance(vv, float) else vv for kk, vv in v.items()} for k, v in sector_stats.items()},
    "neighbor_results": neighbor_results,
    "overload_verdict": verdict
}
print("\n=== JSON RESULTS ===")
print(json.dumps(results, indent=2))
