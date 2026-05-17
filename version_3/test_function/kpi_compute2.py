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
    return int(rec['timestamp_utc'][11:13])

# ---- Step 2: USID_09 lost traffic ----
hist_09 = get_kpi_history('USID_09')
filtered_09 = [r for r in hist_09 if hour_of(r) in OUTAGE_HOURS]

by_sector_09 = defaultdict(list)
for r in filtered_09:
    by_sector_09[r['sector_id']].append(r)

sector_stats = {}
for sid, recs in by_sector_09.items():
    mbps_vals = [r['throughput_dl_mbps'] for r in recs]
    vol_vals = [r['volume_dl_gb'] for r in recs]
    sector_stats[sid] = {
        'avg_mbps': float(np.mean(mbps_vals)),
        'avg_vol_gb': float(np.mean(vol_vals)),
        'n': len(recs)
    }

print("=== USID_09 Sector Stats (outage hours, filtered) ===")
for sid in sorted(sector_stats):
    s = sector_stats[sid]
    print(f"  {sid}: avg_mbps={s['avg_mbps']:.4f}, avg_vol_gb={s['avg_vol_gb']:.6f}, n={s['n']}")

lost_traffic_mbps = sum(sector_stats[s]['avg_mbps'] for s in FAILED_SECTORS if s in sector_stats)
lost_volume_gb = sum(sector_stats[s]['avg_vol_gb'] for s in FAILED_SECTORS if s in sector_stats)
baseline_mbps = sum(sector_stats[s]['avg_mbps'] for s in ALL_SECTORS if s in sector_stats)
loss_ratio = lost_traffic_mbps / baseline_mbps if baseline_mbps > 0 else 0.0

print(f"\nlost_traffic_mbps = {lost_traffic_mbps:.4f}")
print(f"lost_volume_gb    = {lost_volume_gb:.6f}")
print(f"baseline_mbps     = {baseline_mbps:.4f}")
print(f"loss_ratio        = {loss_ratio:.4f}")

# ---- Step 3: Neighbor analysis (site-level = sum of per-sector averages) ----
print("\n=== Neighbor Analysis (site-level aggregate) ===")
neighbor_results = {}

for nusid in NEIGHBORS:
    hist_n = get_kpi_history(nusid)
    filtered_n = [r for r in hist_n if hour_of(r) in OUTAGE_HOURS]

    # Group by sector, compute per-sector stats
    by_sec = defaultdict(list)
    by_sec_vol = defaultdict(list)
    for r in filtered_n:
        by_sec[r['sector_id']].append(r['throughput_dl_mbps'])
        by_sec_vol[r['sector_id']].append(r['volume_dl_gb'])

    if not by_sec:
        print(f"  {nusid}: NO DATA")
        continue

    # Site-level: sum of per-sector averages
    neighbor_baseline_mbps = sum(np.mean(v) for v in by_sec.values())
    neighbor_baseline_vol_gb = sum(np.mean(v) for v in by_sec_vol.values())

    # p90 at site level: group by timestamp, sum sectors per timestamp, then p90
    by_ts = defaultdict(float)
    for r in filtered_n:
        by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
    site_throughputs = list(by_ts.values())
    neighbor_p90_mbps = float(np.percentile(site_throughputs, 90))

    af = ABSORPTION_FRACTIONS[nusid]
    extra_throughput_mbps = lost_traffic_mbps * af
    extra_volume_gb = lost_volume_gb * af
    new_total_mbps = neighbor_baseline_mbps + extra_throughput_mbps

    thresh85 = neighbor_p90_mbps * 0.85
    if new_total_mbps <= thresh85:
        feasibility = "sufficient"
    elif new_total_mbps <= neighbor_p90_mbps:
        feasibility = "marginal"
    else:
        feasibility = "insufficient"

    neighbor_results[nusid] = {
        "absorption_fraction": af,
        "neighbor_baseline_mbps": round(neighbor_baseline_mbps, 4),
        "neighbor_p90_mbps": round(neighbor_p90_mbps, 4),
        "neighbor_baseline_vol_gb": round(neighbor_baseline_vol_gb, 6),
        "extra_throughput_mbps": round(extra_throughput_mbps, 4),
        "extra_volume_gb": round(extra_volume_gb, 6),
        "new_total_mbps": round(new_total_mbps, 4),
        "thresh85": round(thresh85, 4),
        "absorption_feasibility": feasibility,
    }
    print(f"  {nusid}: site_baseline={neighbor_baseline_mbps:.4f}, p90={neighbor_p90_mbps:.4f}, "
          f"extra={extra_throughput_mbps:.4f}, new_total={new_total_mbps:.4f}, "
          f"thresh85={thresh85:.4f} → {feasibility}")

# ---- Step 4: Verdict ----
feasibilities = [v['absorption_feasibility'] for v in neighbor_results.values()]
if any(f == 'sufficient' for f in feasibilities):
    overload_verdict = "no_overload"
elif all(f == 'insufficient' for f in feasibilities):
    overload_verdict = "overload"
else:
    overload_verdict = "marginal_risk"

print(f"\noverload_verdict: {overload_verdict}")

print("\n=== JSON ===")
print(json.dumps({
    "lost_traffic_mbps": round(lost_traffic_mbps, 4),
    "lost_volume_gb": round(lost_volume_gb, 6),
    "baseline_mbps": round(baseline_mbps, 4),
    "loss_ratio": round(loss_ratio, 4),
    "overload_verdict": overload_verdict,
    "neighbor_results": neighbor_results,
    "sector_stats": {k: {kk: round(vv, 4) if isinstance(vv, float) else vv
                         for kk, vv in v.items()} for k, v in sector_stats.items()}
}, indent=2))
