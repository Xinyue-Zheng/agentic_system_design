import pandas as pd
import numpy as np
import json

df = pd.read_csv('/workspace/version_3/data/kpi_sector_timeseries.csv')
df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])

hist_end = pd.Timestamp('2026-04-17T00:00:00Z')
hist_start = df['timestamp_utc'].min()
n_days = (hist_end - hist_start).days
print(f"History: {hist_start} to {hist_end}, {n_days} days")

outage_start = pd.Timestamp('2026-04-17T10:31:15Z')
outage_end   = pd.Timestamp('2026-04-17T20:58:56Z')
duration_hours = (outage_end - outage_start).total_seconds() / 3600
print(f"Outage duration: {duration_hours:.4f} hours")

# ---- USID_09 history ----
u09_hist = df[(df['usid'] == 'USID_09') & (df['timestamp_utc'] >= hist_start) & (df['timestamp_utc'] < hist_end)]
u09_by_sector = {}
for sec in ['USID_09_S0', 'USID_09_S1', 'USID_09_S2']:
    s = u09_hist[u09_hist['sector_id'] == sec]
    avg_tp = s['throughput_dl_mbps'].mean()
    avg_vol_per_day = s['volume_dl_gb'].sum() / n_days
    u09_by_sector[sec] = {'avg_mbps': avg_tp, 'avg_vol_gb_per_day': avg_vol_per_day}
    print(f"  {sec}: avg_mbps={avg_tp:.4f}, avg_vol_gb/day={avg_vol_per_day:.6f}, n_rows={len(s)}")

failed_sectors = ['USID_09_S0', 'USID_09_S2']
lost_mbps = sum(u09_by_sector[s]['avg_mbps'] for s in failed_sectors)
lost_vol_gb = sum(u09_by_sector[s]['avg_vol_gb_per_day'] for s in failed_sectors)
total_station_mbps = sum(u09_by_sector[s]['avg_mbps'] for s in u09_by_sector)
loss_ratio = lost_mbps / total_station_mbps

print(f"\n=== STEP 1 RESULTS ===")
print(f"lost_traffic_mbps = {lost_mbps:.4f}")
print(f"lost_volume_gb_per_day = {lost_vol_gb:.6f}")
print(f"total_station_baseline_mbps = {total_station_mbps:.4f}")
print(f"loss_ratio = {loss_ratio:.4f}")

# ---- STEP 2: Neighbor analysis ----
neighbor_usids = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10']

absorption_fractions = {
    'USID_01': 0.5714,
    'USID_25': 0.5000,
    'USID_43': 0.4286,
    'USID_29': 0.1429,
    'USID_45': 0.1190,
    'USID_10': 0.0952,
}

print(f"\n=== STEP 2: NEIGHBOR ANALYSIS ===")
per_neighbor = {}
for nb in neighbor_usids:
    nb_hist = df[(df['usid'] == nb) & (df['timestamp_utc'] >= hist_start) & (df['timestamp_utc'] < hist_end)]
    nb_baseline_mbps = nb_hist['throughput_dl_mbps'].mean()
    nb_baseline_vol = nb_hist['volume_dl_gb'].sum() / n_days
    nb_p90 = nb_hist['throughput_dl_mbps'].quantile(0.90)

    frac = absorption_fractions[nb]
    extra_tp = lost_mbps * frac
    extra_vol = lost_vol_gb * frac
    new_total = nb_baseline_mbps + extra_tp

    threshold_sufficient = nb_p90 * 0.85
    threshold_marginal = nb_p90 * 1.00
    if new_total <= threshold_sufficient:
        feasibility = 'sufficient'
    elif new_total <= threshold_marginal:
        feasibility = 'marginal'
    else:
        feasibility = 'insufficient'

    per_neighbor[nb] = {
        'absorption_fraction': frac,
        'extra_throughput_mbps': round(extra_tp, 4),
        'extra_volume_gb': round(extra_vol, 6),
        'neighbor_baseline_mbps': round(nb_baseline_mbps, 4),
        'neighbor_p90_mbps': round(nb_p90, 4),
        'new_total_throughput_mbps': round(new_total, 4),
        'absorption_feasibility': feasibility,
    }
    print(f"  {nb}: baseline={nb_baseline_mbps:.4f}, p90={nb_p90:.4f}, frac={frac}, extra={extra_tp:.4f}, new_total={new_total:.4f} => {feasibility}")

# ---- STEP 3: Overload verdict ----
feasibilities = [v['absorption_feasibility'] for v in per_neighbor.values()]
print(f"\nFeasibilities: {feasibilities}")
if 'sufficient' in feasibilities:
    overload_verdict = 'no_overload'
elif 'insufficient' in feasibilities and 'sufficient' not in feasibilities and 'marginal' not in feasibilities:
    overload_verdict = 'overload'
elif 'marginal' in feasibilities and 'sufficient' not in feasibilities:
    if all(f == 'insufficient' for f in feasibilities):
        overload_verdict = 'overload'
    else:
        overload_verdict = 'marginal_risk'
else:
    overload_verdict = 'no_overload'
print(f"overload_verdict = {overload_verdict}")

# ---- STEP 2: Peak-hour neighbor analysis ----
print(f"\n=== STEP 2b: PEAK HOUR ANALYSIS ===")
peak_hours = [15, 16, 17, 18, 19, 20]
for nb in neighbor_usids:
    nb_hist = df[(df['usid'] == nb) & (df['timestamp_utc'] >= hist_start) & (df['timestamp_utc'] < hist_end)].copy()
    nb_hist['hour'] = nb_hist['timestamp_utc'].dt.hour
    nb_peak = nb_hist[nb_hist['hour'].isin(peak_hours)]
    peak_baseline = nb_peak['throughput_dl_mbps'].mean()
    peak_p90 = nb_peak['throughput_dl_mbps'].quantile(0.90)
    frac = absorption_fractions[nb]
    extra_tp = lost_mbps * frac
    new_total = peak_baseline + extra_tp
    thresh = peak_p90 * 0.85
    if new_total <= thresh:
        feas = 'sufficient'
    elif new_total <= peak_p90:
        feas = 'marginal'
    else:
        feas = 'insufficient'
    print(f"  {nb}: peak_baseline={peak_baseline:.4f}, peak_p90={peak_p90:.4f}, new_total={new_total:.4f} => {feas}")

# ---- SUSTAINED PRESSURE: Hourly breakdown ----
print(f"\n=== SUSTAINED PRESSURE: HOURLY ===")
# Build hour-of-day baseline for each neighbor
hourly_results = {}
for nb in neighbor_usids:
    nb_hist = df[(df['usid'] == nb) & (df['timestamp_utc'] >= hist_start) & (df['timestamp_utc'] < hist_end)].copy()
    nb_hist['hour'] = nb_hist['timestamp_utc'].dt.hour
    hourly_baseline = nb_hist.groupby('hour')['throughput_dl_mbps'].mean()
    nb_p90 = nb_hist['throughput_dl_mbps'].quantile(0.90)
    hourly_results[nb] = {'hourly_baseline': hourly_baseline, 'p90': nb_p90}

# Outage hours (10:31 to 20:58 UTC = hours 10-20)
outage_hours = list(range(10, 21))  # 10, 11, ..., 20
print(f"Outage hours (UTC): {outage_hours}")

# For each hour in outage window, classify each neighbor
hour_classifications = {nb: {} for nb in neighbor_usids}
for h in outage_hours:
    for nb in neighbor_usids:
        frac = absorption_fractions[nb]
        hour_base = hourly_results[nb]['hourly_baseline'].get(h, hourly_results[nb]['hourly_baseline'].mean())
        nb_p90 = hourly_results[nb]['p90']
        extra = lost_mbps * frac
        new_total = hour_base + extra
        if new_total <= nb_p90 * 0.85:
            cls = 'stable'
        elif new_total <= nb_p90:
            cls = 'stressed'
        else:
            cls = 'overloaded'
        hour_classifications[nb][h] = {'hour_baseline': round(hour_base, 4), 'new_total': round(new_total, 4), 'cls': cls}

# Aggregate per neighbor
for nb in neighbor_usids:
    clss = [v['cls'] for v in hour_classifications[nb].values()]
    stable = clss.count('stable')
    stressed = clss.count('stressed')
    overloaded = clss.count('overloaded')
    print(f"  {nb}: stable={stable}, stressed={stressed}, overloaded={overloaded}")

# Overall trend across outage hours for WORST neighbor
# Find neighbor with most issues
worst_nb = None
worst_score = -1
for nb in neighbor_usids:
    clss = [v['cls'] for v in hour_classifications[nb].values()]
    score = clss.count('overloaded') * 2 + clss.count('stressed')
    if score > worst_score:
        worst_score = score
        worst_nb = nb

print(f"\nWorst neighbor: {worst_nb} (score={worst_score})")
if worst_nb:
    for h, v in sorted(hour_classifications[worst_nb].items()):
        print(f"  Hour {h:02d}:00 - baseline={v['hour_baseline']}, new_total={v['new_total']} => {v['cls']}")
