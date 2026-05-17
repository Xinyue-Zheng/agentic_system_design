import sys, os
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
from mcp_server.server import get_kpi_history
import numpy as np
from collections import defaultdict
import json

OUTAGE_HOURS = list(range(10, 21))
NEIGHBORS = ["USID_01", "USID_25", "USID_43", "USID_29", "USID_45", "USID_10"]
ABSORPTION_FRACTIONS = {
    "USID_01": 0.5714,
    "USID_25": 0.5,
    "USID_43": 0.4286,
    "USID_29": 0.1429,
    "USID_45": 0.119,
    "USID_10": 0.0952,
}

LOST_TRAFFIC_MBPS = 136.4263
LOST_VOLUME_GB = 0.033307
PEAK_HOURS = {15, 16, 17, 18, 19, 20}

def hour_of(rec):
    return int(rec['timestamp_utc'][11:13])

# Load all neighbor history once
neighbor_data = {}
for nusid in NEIGHBORS:
    hist_n = get_kpi_history(nusid)
    neighbor_data[nusid] = [r for r in hist_n if hour_of(r) in set(OUTAGE_HOURS)]

CLASS_ORDER = {"stable": 0, "stressed": 1, "overloaded": 2}

print("=== Hourly Sustained Analysis (site-level) ===")
hourly_results = {}

for H in OUTAGE_HOURS:
    hour_label = f"{H:02d}:00"
    worst_class = "stable"
    worst_neighbor = None
    worst_info = {}

    neighbor_hour_stats = {}
    for nusid in NEIGHBORS:
        recs_h = [r for r in neighbor_data[nusid] if hour_of(r) == H]
        if not recs_h:
            continue

        # Site-level baseline: sum of per-sector averages
        by_sec = defaultdict(list)
        by_sec_vol = defaultdict(list)
        for r in recs_h:
            by_sec[r['sector_id']].append(r['throughput_dl_mbps'])
            by_sec_vol[r['sector_id']].append(r['volume_dl_gb'])

        h_baseline = sum(np.mean(v) for v in by_sec.values())
        h_baseline_vol = sum(np.mean(v) for v in by_sec_vol.values())

        # p90: per-timestamp site totals
        by_ts = defaultdict(float)
        for r in recs_h:
            by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
        site_thr = list(by_ts.values())
        h_p90 = float(np.percentile(site_thr, 90))

        af = ABSORPTION_FRACTIONS[nusid]
        extra_mbps = LOST_TRAFFIC_MBPS * af
        extra_vol = LOST_VOLUME_GB * af
        new_total = h_baseline + extra_mbps
        new_vol = h_baseline_vol + extra_vol

        thresh85 = h_p90 * 0.85
        if new_total <= thresh85:
            cls = "stable"
        elif new_total <= h_p90:
            cls = "stressed"
        else:
            cls = "overloaded"

        neighbor_hour_stats[nusid] = {
            "h_baseline": round(h_baseline, 4),
            "h_p90": round(h_p90, 4),
            "h_baseline_vol": round(h_baseline_vol, 6),
            "extra_mbps": round(extra_mbps, 4),
            "extra_vol": round(extra_vol, 6),
            "new_total": round(new_total, 4),
            "new_vol": round(new_vol, 6),
            "thresh85": round(thresh85, 4),
            "classification": cls
        }

        if CLASS_ORDER[cls] > CLASS_ORDER[worst_class]:
            worst_class = cls
            worst_neighbor = nusid
            worst_info = neighbor_hour_stats[nusid]

    if worst_neighbor is None:
        worst_neighbor = NEIGHBORS[0]
        worst_info = neighbor_hour_stats.get(NEIGHBORS[0], {})

    hourly_results[H] = {
        "hour_label": hour_label,
        "worst_classification": worst_class,
        "worst_neighbor": worst_neighbor,
        "worst_new_total_mbps": worst_info.get("new_total"),
        "worst_baseline_mbps": worst_info.get("h_baseline"),
        "worst_p90_mbps": worst_info.get("h_p90"),
        "worst_baseline_vol_gb": worst_info.get("h_baseline_vol"),
        "worst_new_vol_gb": worst_info.get("new_vol"),
        "neighbor_stats": neighbor_hour_stats
    }

    # Brief per-hour neighbor summary
    summary = {n: neighbor_hour_stats[n]['classification'] for n in NEIGHBORS if n in neighbor_hour_stats}
    print(f"  Hour {hour_label}: worst={worst_class} ({worst_neighbor}) new_total={worst_info.get('new_total')} p90={worst_info.get('h_p90')} | {summary}")

classes_seq = [hourly_results[H]['worst_classification'] for H in OUTAGE_HOURS]
n_hours = len(OUTAGE_HOURS)
first_half = classes_seq[:n_hours//2]
second_half = classes_seq[n_hours//2:]

def avg_cls(lst):
    return sum(CLASS_ORDER[c] for c in lst) / len(lst) if lst else 0

if avg_cls(second_half) < avg_cls(first_half) - 0.1:
    trend = "improving"
elif avg_cls(second_half) > avg_cls(first_half) + 0.1:
    trend = "worsening"
else:
    trend = "stable"

stable_count = sum(1 for c in classes_seq if c == "stable")
stressed_count = sum(1 for c in classes_seq if c == "stressed")
overloaded_count = sum(1 for c in classes_seq if c == "overloaded")

print(f"\nstable={stable_count}, stressed={stressed_count}, overloaded={overloaded_count}")
print(f"trend={trend}")

if overloaded_count > n_hours / 2:
    sustained_verdict = "unsustainable"
elif trend == "worsening":
    sustained_verdict = "degrading"
else:
    sustained_verdict = "sustainable"

print(f"sustained_pressure_verdict={sustained_verdict}")

# Peak hour analysis
peak_class = {}
for ph in sorted(PEAK_HOURS):
    if ph in hourly_results:
        peak_class[f"{ph:02d}:00"] = hourly_results[ph]['worst_classification']

print(f"\nPeak hour classifications: {peak_class}")
peak_vals = list(peak_class.values())
if any(c == "overloaded" for c in peak_vals):
    peak_verdict = "critical"
elif all(c == "stressed" for c in peak_vals) and not any(c == "stable" for c in peak_vals):
    peak_verdict = "elevated_risk"
elif any(c == "stable" for c in peak_vals) and not any(c == "overloaded" for c in peak_vals):
    peak_verdict = "manageable"
else:
    peak_verdict = "elevated_risk"

print(f"peak_hour_verdict={peak_verdict}")

# Build sustained_reasoning_log
sustained_log = []
for H in OUTAGE_HOURS:
    r = hourly_results[H]
    worst = r['worst_neighbor']
    sustained_log.append({
        "hour": r['hour_label'],
        "worst_neighbor": worst,
        "hour_baseline_mbps": r['worst_baseline_mbps'],
        "hour_p90_mbps": r['worst_p90_mbps'],
        "new_total_mbps": r['worst_new_total_mbps'],
        "hour_baseline_vol_gb": r['worst_baseline_vol_gb'],
        "new_total_vol_gb": r['worst_new_vol_gb'],
        "classification": r['worst_classification']
    })

# Peak derivation
peak_derivation = {
    "peak_hours": [f"{ph:02d}:00" for ph in sorted(PEAK_HOURS)],
    "peak_classifications": peak_class,
    "derived_peak_hour_verdict": peak_verdict
}

output = {
    "stable_count": stable_count,
    "stressed_count": stressed_count,
    "overloaded_count": overloaded_count,
    "trend": trend,
    "sustained_verdict": sustained_verdict,
    "peak_class": peak_class,
    "peak_verdict": peak_verdict,
    "sustained_log": sustained_log,
    "peak_derivation": peak_derivation,
    "hourly_results": hourly_results
}

print("\n=== JSON ===")
print(json.dumps(output, indent=2))
