import sys, os
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
from mcp_server.server import get_kpi_history, get_kpi_timeseries
from collections import defaultdict
import pandas as pd
import json

START = "2026-04-17T10:31:15Z"
END   = "2026-04-17T20:58:56Z"
neighbors = ["USID_01", "USID_25", "USID_43", "USID_29", "USID_45", "USID_10"]

lost_traffic = 90.4748
lost_traffic_1_2 = lost_traffic * 1.2

# Neighbor historical averages
neighbor_hist_avg = {}
for n in neighbors:
    hist = get_kpi_history(n)
    by_sec = defaultdict(list)
    for r in hist:
        by_sec[r['sector_id']].append(r['throughput_dl_mbps'])
    neighbor_hist_avg[n] = sum(sum(v)/len(v) for v in by_sec.values() if v)

# Neighbor timeseries during outage
neighbor_ts = {}
for n in neighbors:
    ts = get_kpi_timeseries(n, START, END)
    df = pd.DataFrame(ts)
    df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])
    neighbor_ts[n] = df

# Hourly segments: 10:00 to 20:00 UTC
start_dt = pd.Timestamp("2026-04-17T10:00:00Z")
hourly_results = []

for h in range(11):
    hour_start = start_dt + pd.Timedelta(hours=h)
    hour_end   = hour_start + pd.Timedelta(hours=1)
    effective_start = max(hour_start, pd.Timestamp(START))
    effective_end   = min(hour_end,   pd.Timestamp(END))
    if effective_start >= effective_end:
        continue

    hour_label = hour_start.strftime("%H:00")
    neighbor_statuses = []

    for n in neighbors:
        df = neighbor_ts[n]
        mask = (df['timestamp_utc'] >= effective_start) & (df['timestamp_utc'] < effective_end)
        subset = df[mask]
        if subset.empty:
            by_sec = df.groupby('sector_id')['throughput_dl_mbps'].mean()
            curr_load = float(by_sec.sum())
        else:
            by_sec = subset.groupby('sector_id')['throughput_dl_mbps'].mean()
            curr_load = float(by_sec.sum())

        remaining = neighbor_hist_avg[n] - curr_load
        if remaining > lost_traffic_1_2:
            status = "sufficient"
        elif remaining >= 0:
            status = "marginal"
        else:
            status = "insufficient"
        neighbor_statuses.append(status)

    if any(s == "sufficient" for s in neighbor_statuses):
        hour_class = "stable"
    elif any(s == "marginal" for s in neighbor_statuses):
        hour_class = "stressed"
    else:
        hour_class = "overloaded"

    hourly_results.append({
        "hour": hour_label,
        "class": hour_class,
        "neighbor_statuses": neighbor_statuses
    })

stable    = sum(1 for r in hourly_results if r['class'] == 'stable')
stressed  = sum(1 for r in hourly_results if r['class'] == 'stressed')
overloaded = sum(1 for r in hourly_results if r['class'] == 'overloaded')

print("=== Hourly classification ===")
for r in hourly_results:
    print(r['hour'], r['class'], r['neighbor_statuses'])

print(f"\nstable={stable}, stressed={stressed}, overloaded={overloaded}")

# Trend: first half vs second half
n = len(hourly_results)
first_half  = hourly_results[:n//2]
second_half = hourly_results[n//2:]
bad_first  = sum(1 for r in first_half  if r['class'] in ('stressed','overloaded'))
bad_second = sum(1 for r in second_half if r['class'] in ('stressed','overloaded'))
print(f"bad_first_half={bad_first}/{len(first_half)}, bad_second_half={bad_second}/{len(second_half)}")

# Determine trend
if bad_second > bad_first:
    trend = "worsening"
elif bad_second < bad_first:
    trend = "improving"
else:
    trend = "stable"

# Sustained pressure verdict
if stable >= n * 0.6:
    spv = "sustainable"
elif trend == "worsening":
    spv = "degrading"
elif overloaded > (n / 2):
    spv = "unsustainable"
else:
    spv = "degrading"

print(f"\ntrend={trend}, sustained_pressure_verdict={spv}")
print(f"total_hours={n}")
