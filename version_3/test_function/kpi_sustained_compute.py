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
LOST_VOLUME_GB = 0.0333
PEAK_HOURS = {15, 16, 17, 18, 19, 20}

def hour_of(rec):
    ts = rec['timestamp_utc']
    return int(ts[11:13])

neighbor_data = {}
for nusid in NEIGHBORS:
    hist_n = get_kpi_history(nusid)
    by_hour = defaultdict(list)
    for r in hist_n:
        h = hour_of(r)
        if h in set(OUTAGE_HOURS):
            by_hour[h].append(r)
    neighbor_data[nusid] = by_hour

print("=== Hourly Neighbor Stats ===")
hourly_results = {}

for H in OUTAGE_HOURS:
    hour_label = f"{H:02d}:00"
    worst_class = "stable"
    worst_neighbor = None
    worst_new_total = None
    worst_baseline = None
    worst_p90 = None
    worst_baseline_vol = None
    worst_new_vol = None

    neighbor_hour_stats = {}
    for nusid in NEIGHBORS:
        recs = neighbor_data[nusid].get(H, [])
        if not recs:
            continue
        mbps_vals = [r['throughput_dl_mbps'] for r in recs]
        vol_vals = [r['volume_dl_gb'] for r in recs]

        h_baseline = float(np.mean(mbps_vals))
        h_p90 = float(np.percentile(mbps_vals, 90))
        h_baseline_vol = float(np.mean(vol_vals))

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

        CLASS_ORDER = {"stable": 0, "stressed": 1, "overloaded": 2}
        if CLASS_ORDER[cls] > CLASS_ORDER[worst_class]:
            worst_class = cls
            worst_neighbor = nusid
            worst_new_total = round(new_total, 4)
            worst_baseline = round(h_baseline, 4)
            worst_p90 = round(h_p90, 4)
            worst_baseline_vol = round(h_baseline_vol, 6)
            worst_new_vol = round(new_vol, 6)

    if worst_neighbor is None and NEIGHBORS:
        first = NEIGHBORS[0]
        if H in neighbor_data.get(first, {}):
            stats = neighbor_hour_stats.get(first, {})
            worst_neighbor = first
            worst_new_total = stats.get("new_total", 0)
            worst_baseline = stats.get("h_baseline", 0)
            worst_p90 = stats.get("h_p90", 0)
            worst_baseline_vol = stats.get("h_baseline_vol", 0)
            worst_new_vol = stats.get("new_vol", 0)

    hourly_results[H] = {
        "hour_label": hour_label,
        "worst_classification": worst_class,
        "worst_neighbor": worst_neighbor,
        "worst_new_total_mbps": worst_new_total,
        "worst_baseline_mbps": worst_baseline,
        "worst_p90_mbps": worst_p90,
        "worst_baseline_vol_gb": worst_baseline_vol,
        "worst_new_vol_gb": worst_new_vol,
        "neighbor_stats": neighbor_hour_stats
    }
    print(f"  Hour {hour_label}: worst={worst_class} (by {worst_neighbor}), new_total={worst_new_total}, p90={worst_p90}")

classes_seq = [hourly_results[H]['worst_classification'] for H in OUTAGE_HOURS]
CLASS_ORDER = {"stable": 0, "stressed": 1, "overloaded": 2}
n_hours = len(OUTAGE_HOURS)
first_half = classes_seq[:n_hours//2]
second_half = classes_seq[n_hours//2:]

def avg_class(lst):
    vals = [CLASS_ORDER[c] for c in lst]
    return sum(vals) / len(vals) if vals else 0

if avg_class(second_half) < avg_class(first_half) - 0.1:
    trend = "improving"
elif avg_class(second_half) > avg_class(first_half) + 0.1:
    trend = "worsening"
else:
    trend = "stable"

stable_count = sum(1 for c in classes_seq if c == "stable")
stressed_count = sum(1 for c in classes_seq if c == "stressed")
overloaded_count = sum(1 for c in classes_seq if c == "overloaded")

print(f"\nHourly class counts: stable={stable_count}, stressed={stressed_count}, overloaded={overloaded_count}")
print(f"Trend: {trend}")

if overloaded_count > n_hours / 2:
    sustained_verdict = "unsustainable"
elif trend == "worsening":
    sustained_verdict = "degrading"
else:
    sustained_verdict = "sustainable"

print(f"sustained_pressure_verdict: {sustained_verdict}")

peak_class = {}
for ph in sorted(PEAK_HOURS):
    if ph in hourly_results:
        peak_class[f"{ph:02d}:00"] = hourly_results[ph]['worst_classification']

print(f"\nPeak hour classifications: {peak_class}")
peak_vals = list(peak_class.values())
if any(c == "overloaded" for c in peak_vals):
    peak_verdict = "critical"
elif all(c == "stressed" for c in peak_vals):
    peak_verdict = "elevated_risk"
elif any(c in ("stable","stressed") for c in peak_vals) and not any(c == "overloaded" for c in peak_vals):
    if any(c == "stable" for c in peak_vals):
        peak_verdict = "manageable"
    else:
        peak_verdict = "elevated_risk"
else:
    peak_verdict = "manageable"

print(f"peak_hour_verdict: {peak_verdict}")

output = {
    "hourly_results": hourly_results,
    "stable_count": stable_count,
    "stressed_count": stressed_count,
    "overloaded_count": overloaded_count,
    "trend": trend,
    "sustained_verdict": sustained_verdict,
    "peak_class": peak_class,
    "peak_verdict": peak_verdict
}
print("\n=== JSON OUTPUT ===")
print(json.dumps(output, indent=2))
