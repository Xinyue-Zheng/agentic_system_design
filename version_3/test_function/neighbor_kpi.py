import sys, os, json
sys.path.insert(0, '.')
os.environ['DATA_DIR'] = 'data'
from mcp_server.server import get_kpi_history
from collections import defaultdict
from datetime import datetime, timezone, timedelta

OUTAGE_HOURS = list(range(10, 21))
PEAK_HOURS = [17, 18, 19, 20]
NEIGHBORS = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10']
outage_date = datetime(2026, 4, 17, tzinfo=timezone.utc)
cutoff_14d = outage_date - timedelta(days=14)

def parse_hour(ts_str):
    if 'T' in ts_str:
        return int(ts_str.split('T')[1].split(':')[0])
    return -1

def is_weekday(ts_str):
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.weekday() < 5
    except:
        return True

def is_recent_14d(ts_str):
    try:
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return ts >= cutoff_14d and ts < outage_date
    except:
        return False

def compute_stats(values):
    if not values:
        return None
    values = sorted(values)
    n = len(values)
    mean_val = sum(values) / n
    def pct(p):
        idx = (p / 100) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return values[lo] + (idx - lo) * (values[hi] - values[lo])
    return {
        'count': n,
        'mean': round(mean_val, 2),
        'p10': round(pct(10), 2),
        'p75': round(pct(75), 2),
        'p90': round(pct(90), 2),
    }

results = {}

for n in NEIGHBORS:
    hist = get_kpi_history(n)
    # Filter to outage hours
    window = [r for r in hist if parse_hour(r['timestamp_utc']) in OUTAGE_HOURS]

    # Group by timestamp (sum all sectors at each timestamp)
    by_ts = defaultdict(float)
    for r in window:
        by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
    all_values = list(by_ts.values())

    # Per-hour stats
    hour_data = {}
    for h in OUTAGE_HOURS:
        h_recs = [r for r in window if parse_hour(r['timestamp_utc']) == h]
        h_by_ts = defaultdict(float)
        for r in h_recs:
            h_by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
        h_vals = list(h_by_ts.values())
        s = compute_stats(h_vals)
        hour_data[h] = s

    # Overall outage-window stats
    overall = compute_stats(all_values)

    results[n] = {
        'overall': overall,
        'hour_stats': hour_data,
    }

    print(f"\n{n}:")
    print(f"  Overall outage-window: mean={overall['mean']}, p75={overall['p75']}, p90={overall['p90']}, n={overall['count']}")
    print(f"  Per-hour (mean | p75 | p90):")
    for h in OUTAGE_HOURS:
        s = hour_data[h]
        if s:
            print(f"    {h:02d}:00 mean={s['mean']:7.2f}, p75={s['p75']:7.2f}, p90={s['p90']:7.2f}  n={s['count']}")
        else:
            print(f"    {h:02d}:00 NO DATA")
