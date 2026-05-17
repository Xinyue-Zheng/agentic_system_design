import sys, os, json
sys.path.insert(0, '.')
os.environ['DATA_DIR'] = 'data'
from mcp_server.server import get_kpi_history
import statistics

# Outage window hours (UTC local): 10-20 (10:31 to 20:58)
OUTAGE_HOURS = list(range(10, 21))
PEAK_HOURS = [17, 18, 19, 20]
AFFECTED_SECTORS = ['USID_09_S0', 'USID_09_S2']
NEIGHBORS = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10']
DAY_TYPE = 'weekday'

def parse_hour(ts_str):
    # ts format: 2026-02-16T12:15:00+00:00 or similar
    # Extract hour
    if 'T' in ts_str:
        time_part = ts_str.split('T')[1]
        hour = int(time_part.split(':')[0])
        return hour
    return -1

def parse_date(ts_str):
    if 'T' in ts_str:
        return ts_str.split('T')[0]
    return ''

def is_weekday(ts_str):
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.weekday() < 5  # 0-4 = Mon-Fri
    except:
        return True

def compute_stats(values):
    if not values:
        return None
    values = sorted(values)
    n = len(values)
    mean_val = sum(values) / n
    def percentile(pct):
        idx = (pct / 100) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        frac = idx - lo
        return values[lo] + frac * (values[hi] - values[lo])
    return {
        'count': n,
        'mean': round(mean_val, 2),
        'p10': round(percentile(10), 2),
        'p75': round(percentile(75), 2),
        'p90': round(percentile(90), 2),
        'p25': round(percentile(25), 2),
        'min': round(values[0], 2),
        'max': round(values[-1], 2),
    }

# ---- USID_09 affected sectors analysis ----
print("=" * 60)
print("USID_09 AFFECTED SECTORS ANALYSIS")
print("=" * 60)

hist_09 = get_kpi_history('USID_09')
print(f"Total USID_09 records: {len(hist_09)}")
sectors_09 = set(r['sector_id'] for r in hist_09)
print(f"Sectors: {sorted(sectors_09)}")

# Filter to affected sectors and outage hours
affected_window = [r for r in hist_09 if r['sector_id'] in AFFECTED_SECTORS and parse_hour(r['timestamp_utc']) in OUTAGE_HOURS]
print(f"Affected sectors, outage hours records: {len(affected_window)}")

# Get all throughput for affected sectors combined (sum by timestamp grouping, since they're separate sectors)
# Actually, we need total throughput across both sectors at same time window
# Group by timestamp to sum sectors at each time point
from collections import defaultdict
by_ts = defaultdict(float)
by_ts_sectors = defaultdict(list)
for r in affected_window:
    by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
    by_ts_sectors[r['timestamp_utc']].append(r['sector_id'])

combined_values = list(by_ts.values())
print(f"\nCombined affected sectors throughput (outage hours, all 60 days):")
stats = compute_stats(combined_values)
print(f"  Stats: {stats}")

# Same-hour 60-day stats (aggregated across both sectors per timestamp)
print(f"\nPer-hour stats for affected sectors (combined):")
hour_stats = {}
for h in OUTAGE_HOURS:
    h_records = [r for r in affected_window if parse_hour(r['timestamp_utc']) == h]
    # Group by timestamp to combine sectors
    h_by_ts = defaultdict(float)
    for r in h_records:
        h_by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
    h_values = list(h_by_ts.values())
    s = compute_stats(h_values)
    hour_stats[h] = s
    if s:
        print(f"  Hour {h:02d}: n={s['count']}, mean={s['mean']}, p75={s['p75']}, p90={s['p90']}")
    else:
        print(f"  Hour {h:02d}: NO DATA")

# Same-daytype (weekday) same-hour
print(f"\nWeekday-filtered per-hour stats for affected sectors (combined):")
for h in OUTAGE_HOURS:
    h_records = [r for r in affected_window if parse_hour(r['timestamp_utc']) == h and is_weekday(r['timestamp_utc'])]
    h_by_ts = defaultdict(float)
    for r in h_records:
        h_by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
    h_values = list(h_by_ts.values())
    s = compute_stats(h_values)
    if s:
        print(f"  Hour {h:02d} [weekday]: n={s['count']}, mean={s['mean']}, p75={s['p75']}, p90={s['p90']}")
    else:
        print(f"  Hour {h:02d} [weekday]: NO DATA")

# Recent 14 days - outage date is 2026-04-17, 14 days back = 2026-04-03
print(f"\nRecent 14-day per-hour stats for affected sectors:")
from datetime import datetime, timezone, timedelta
outage_date = datetime(2026, 4, 17, tzinfo=timezone.utc)
cutoff_14d = outage_date - timedelta(days=14)

for h in OUTAGE_HOURS:
    h_records = [r for r in affected_window if parse_hour(r['timestamp_utc']) == h]
    h_recent = []
    for r in h_records:
        try:
            ts = datetime.fromisoformat(r['timestamp_utc'].replace('Z', '+00:00'))
            if ts >= cutoff_14d and ts < outage_date:
                h_recent.append(r)
        except:
            pass
    h_by_ts = defaultdict(float)
    for r in h_recent:
        h_by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
    h_values = list(h_by_ts.values())
    s = compute_stats(h_values)
    if s:
        print(f"  Hour {h:02d} [14d]: n={s['count']}, mean={s['mean']}, p75={s['p75']}, p90={s['p90']}")
    else:
        print(f"  Hour {h:02d} [14d]: NO DATA")

# Peak hour mean (hours 17-20)
print(f"\nPeak hours (17-20) combined affected sectors stats:")
peak_records = [r for r in affected_window if parse_hour(r['timestamp_utc']) in PEAK_HOURS]
peak_by_ts = defaultdict(float)
for r in peak_records:
    peak_by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
peak_values = list(peak_by_ts.values())
peak_stats = compute_stats(peak_values)
print(f"  Stats: {peak_stats}")

print("\n" + "=" * 60)
print("OVERALL AFFECTED SECTORS OUTAGE-WINDOW STATS")
print("=" * 60)
all_s = compute_stats(combined_values)
print(f"60d same-hour mean: {all_s['mean']}, p75: {all_s['p75']}, p90: {all_s['p90']}")
