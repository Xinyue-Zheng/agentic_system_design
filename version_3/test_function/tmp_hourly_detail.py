import sys, os
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
from mcp_server.server import get_kpi_history, get_kpi_timeseries
from collections import defaultdict
import pandas as pd

START = "2026-04-17T10:31:15Z"
END   = "2026-04-17T20:58:56Z"
neighbors = ["USID_01", "USID_25", "USID_43", "USID_29", "USID_45", "USID_10"]

neighbor_hist_avg = {}
for n in neighbors:
    hist = get_kpi_history(n)
    by_sec = defaultdict(list)
    for r in hist:
        by_sec[r['sector_id']].append(r['throughput_dl_mbps'])
    neighbor_hist_avg[n] = sum(sum(v)/len(v) for v in by_sec.values() if v)

neighbor_ts = {}
for n in neighbors:
    ts = get_kpi_timeseries(n, START, END)
    df = pd.DataFrame(ts)
    df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])
    neighbor_ts[n] = df

start_dt = pd.Timestamp("2026-04-17T10:00:00Z")

print("Hour  | Avg remaining (all neighbors) | Max remaining (best neighbor)")
for h in range(11):
    hour_start = start_dt + pd.Timedelta(hours=h)
    hour_end   = hour_start + pd.Timedelta(hours=1)
    eff_start = max(hour_start, pd.Timestamp(START))
    eff_end   = min(hour_end,   pd.Timestamp(END))
    if eff_start >= eff_end:
        continue

    remainings = []
    for n in neighbors:
        df = neighbor_ts[n]
        mask = (df['timestamp_utc'] >= eff_start) & (df['timestamp_utc'] < eff_end)
        subset = df[mask]
        if subset.empty:
            by_sec = df.groupby('sector_id')['throughput_dl_mbps'].mean()
            curr_load = float(by_sec.sum())
        else:
            by_sec = subset.groupby('sector_id')['throughput_dl_mbps'].mean()
            curr_load = float(by_sec.sum())
        remaining = neighbor_hist_avg[n] - curr_load
        remainings.append(remaining)

    label = hour_start.strftime("%H:00")
    print(f"  {label}  | avg={sum(remainings)/len(remainings):.2f}  | max={max(remainings):.2f}")
