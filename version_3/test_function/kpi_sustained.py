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

# --- Affected site baseline ---
hist09 = get_kpi_history("USID_09")
by_sec_hist = defaultdict(list)
for r in hist09:
    by_sec_hist[r['sector_id']].append(r['throughput_dl_mbps'])
# S0 and S2 are failed
S0_hist = sum(by_sec_hist['USID_09_S0'])/len(by_sec_hist['USID_09_S0'])
S2_hist = sum(by_sec_hist['USID_09_S2'])/len(by_sec_hist['USID_09_S2'])
lost_traffic = S0_hist + S2_hist
lost_traffic_1_2 = lost_traffic * 1.2

# --- Neighbor historical averages ---
neighbor_hist_avg = {}
for n in neighbors:
    hist = get_kpi_history(n)
    by_sec = defaultdict(list)
    for r in hist:
        by_sec[r['sector_id']].append(r['throughput_dl_mbps'])
    neighbor_hist_avg[n] = sum(sum(v)/len(v) for v in by_sec.values() if v)

# --- Neighbor timeseries during outage ---
neighbor_ts = {}
for n in neighbors:
    ts = get_kpi_timeseries(n, START, END)
    df = pd.DataFrame(ts)
    df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])
    neighbor_ts[n] = df

# --- Hourly segments ---
start_dt = pd.Timestamp("2026-04-17T10:00:00Z")
hourly_results = []

for h in range(11):  # hours 10, 11, 12, ..., 20
    hour_start = start_dt + pd.Timedelta(hours=h)
    hour_end   = hour_start + pd.Timedelta(hours=1)
    # Only include actual outage window
    effective_start = max(hour_start, pd.Timestamp("2026-04-17T10:31:15Z"))
    effective_end   = min(hour_end,   pd.Timestamp("2026-04-17T20:58:56Z"))
    if effective_start >= effective_end:
        continue

    hour_label = hour_start.strftime("%H:00")

    # For each neighbor, compute load during this hour
    total_remaining = 0
    neighbor_count = 0
    neighbor_statuses = []
    for n in neighbors:
        df = neighbor_ts[n]
        mask = (df['timestamp_utc'] >= effective_start) & (df['timestamp_utc'] < effective_end)
        subset = df[mask]
        if subset.empty:
            # Use average from full window as fallback
            curr = neighbor_ts[n]['throughput_dl_mbps'].sum() / max(1, len(neighbor_ts[n]))
            # group by sector
            by_sec = subset.groupby('sector_id')['throughput_dl_mbps'].mean()
            curr_load = by_sec.sum() if not by_sec.empty else 0
        else:
            by_sec = subset.groupby('sector_id')['throughput_dl_mbps'].mean()
            curr_load = by_sec.sum()

        remaining = neighbor_hist_avg[n] - curr_load
        if remaining > lost_traffic_1_2:
            status = "sufficient"
        elif remaining >= 0:
            status = "marginal"
        else:
            status = "insufficient"
        neighbor_statuses.append(status)
        total_remaining += remaining
        neighbor_count += 1

    # Classify hour
    if any(s == "sufficient" for s in neighbor_statuses):
        hour_class = "stable"
    elif any(s == "marginal" for s in neighbor_statuses):
        hour_class = "stressed"
    else:
        hour_class = "overloaded"

    hourly_results.append({
        "hour": hour_label,
        "class": hour_class,
        "avg_neighbor_remaining_mbps": round(total_remaining / neighbor_count, 2),
        "statuses": neighbor_statuses
    })

print("=== Hourly classification ===")
for r in hourly_results:
    print(r)

stable   = sum(1 for r in hourly_results if r['class'] == 'stable')
stressed = sum(1 for r in hourly_results if r['class'] == 'stressed')
overloaded = sum(1 for r in hourly_results if r['class'] == 'overloaded')
print(f"\nstable={stable}, stressed={stressed}, overloaded={overloaded}")
print(f"lost_traffic_mbps={lost_traffic:.4f}, lost_x1.2={lost_traffic_1_2:.4f}")

# Trend: check if proportion of overloaded/stressed increases over time
n = len(hourly_results)
first_half  = hourly_results[:n//2]
second_half = hourly_results[n//2:]
bad_first  = sum(1 for r in first_half  if r['class'] in ('stressed','overloaded'))
bad_second = sum(1 for r in second_half if r['class'] in ('stressed','overloaded'))
print(f"bad_first_half={bad_first}/{len(first_half)}, bad_second_half={bad_second}/{len(second_half)}")
