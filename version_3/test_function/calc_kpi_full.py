import pandas as pd
import numpy as np
import json

df = pd.read_csv('/workspace/version_3/data/kpi_sector_timeseries.csv')
df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])

hist_end = pd.Timestamp('2026-04-17T00:00:00Z')
hist_start = df['timestamp_utc'].min()
n_days = (hist_end - hist_start).days

outage_start = pd.Timestamp('2026-04-17T10:31:15Z')
outage_end   = pd.Timestamp('2026-04-17T20:58:56Z')
duration_hours = (outage_end - outage_start).total_seconds() / 3600

u09_by_sector = {}
u09_hist = df[(df['usid'] == 'USID_09') & (df['timestamp_utc'] >= hist_start) & (df['timestamp_utc'] < hist_end)]
for sec in ['USID_09_S0', 'USID_09_S1', 'USID_09_S2']:
    s = u09_hist[u09_hist['sector_id'] == sec]
    u09_by_sector[sec] = {
        'avg_mbps': s['throughput_dl_mbps'].mean(),
        'avg_vol_gb_per_day': s['volume_dl_gb'].sum() / n_days
    }

failed_sectors = ['USID_09_S0', 'USID_09_S2']
lost_mbps = sum(u09_by_sector[s]['avg_mbps'] for s in failed_sectors)
lost_vol_gb = sum(u09_by_sector[s]['avg_vol_gb_per_day'] for s in failed_sectors)
total_station_mbps = sum(u09_by_sector[s]['avg_mbps'] for s in u09_by_sector)
loss_ratio = lost_mbps / total_station_mbps

absorption_fractions = {
    'USID_01': 0.5714,
    'USID_25': 0.5000,
    'USID_43': 0.4286,
    'USID_29': 0.1429,
    'USID_45': 0.1190,
    'USID_10': 0.0952,
}

neighbor_usids = list(absorption_fractions.keys())
per_neighbor = {}
hourly_data = {}

for nb in neighbor_usids:
    nb_hist = df[(df['usid'] == nb) & (df['timestamp_utc'] >= hist_start) & (df['timestamp_utc'] < hist_end)].copy()
    nb_baseline_mbps = nb_hist['throughput_dl_mbps'].mean()
    nb_baseline_vol = nb_hist['volume_dl_gb'].sum() / n_days
    nb_p90 = nb_hist['throughput_dl_mbps'].quantile(0.90)

    frac = absorption_fractions[nb]
    extra_tp = lost_mbps * frac
    extra_vol = lost_vol_gb * frac
    new_total = nb_baseline_mbps + extra_tp

    thresh85 = nb_p90 * 0.85
    thresh100 = nb_p90
    if new_total <= thresh85:
        feasibility = 'sufficient'
    elif new_total <= thresh100:
        feasibility = 'marginal'
    else:
        feasibility = 'insufficient'

    per_neighbor[nb] = {
        'absorption_fraction': frac,
        'extra_throughput_mbps': round(extra_tp, 2),
        'extra_volume_gb': round(extra_vol, 6),
        'neighbor_baseline_mbps': round(nb_baseline_mbps, 2),
        'neighbor_p90_mbps': round(nb_p90, 2),
        'new_total_throughput_mbps': round(new_total, 2),
        'absorption_feasibility': feasibility,
    }

    # Hourly breakdown
    nb_hist['hour'] = nb_hist['timestamp_utc'].dt.hour
    hourly_baseline = nb_hist.groupby('hour')['throughput_dl_mbps'].mean()
    hourly_data[nb] = {'hourly_baseline': hourly_baseline, 'p90': nb_p90}

# overload_verdict
feasibilities = [v['absorption_feasibility'] for v in per_neighbor.values()]
if 'sufficient' in feasibilities:
    overload_verdict = 'no_overload'
elif all(f == 'insufficient' for f in feasibilities):
    overload_verdict = 'overload'
else:
    overload_verdict = 'marginal_risk'

# Sustained pressure hourly
outage_hours = list(range(10, 21))
sustained_log = []
stable_total = stressed_total = overloaded_total = 0

for h in outage_hours:
    for nb in neighbor_usids:
        frac = absorption_fractions[nb]
        h_base = hourly_data[nb]['hourly_baseline'].get(h, hourly_data[nb]['hourly_baseline'].mean())
        p90 = hourly_data[nb]['p90']
        extra = lost_mbps * frac
        new_total_h = h_base + extra
        if new_total_h <= p90 * 0.85:
            cls = 'stable'
            stable_total += 1
        elif new_total_h <= p90:
            cls = 'stressed'
            stressed_total += 1
        else:
            cls = 'overloaded'
            overloaded_total += 1
        sustained_log.append({
            'hour': f'{h:02d}:00',
            f'neighbor_{nb}_hour_baseline_mbps': round(h_base, 2),
            'hour_new_total_mbps': round(new_total_h, 2),
            'classification': cls,
            'neighbor': nb
        })

print(f"Sustained: stable={stable_total}, stressed={stressed_total}, overloaded={overloaded_total}")
total_slots = len(outage_hours) * len(neighbor_usids)
print(f"Total slots: {total_slots}")

# Check if worsening trend: compare early hours vs late hours overload rate
early_hours = [10, 11, 12]
late_hours = [17, 18, 19, 20]
early_overloaded = sum(1 for entry in sustained_log if int(entry['hour'][:2]) in early_hours and entry['classification'] == 'overloaded')
late_overloaded  = sum(1 for entry in sustained_log if int(entry['hour'][:2]) in late_hours  and entry['classification'] == 'overloaded')
early_slots = len(early_hours) * len(neighbor_usids)
late_slots  = len(late_hours)  * len(neighbor_usids)
print(f"Early overload rate: {early_overloaded}/{early_slots} = {early_overloaded/early_slots:.2f}")
print(f"Late overload rate:  {late_overloaded}/{late_slots} = {late_overloaded/late_slots:.2f}")

# sustained_pressure_verdict
overloaded_fraction = overloaded_total / total_slots
stressed_fraction = stressed_total / total_slots
if overloaded_fraction > 0.5:
    sustained_verdict = 'unsustainable'
elif late_overloaded / late_slots > early_overloaded / early_slots + 0.1:
    sustained_verdict = 'degrading'
else:
    sustained_verdict = 'sustainable'
print(f"overloaded_fraction={overloaded_fraction:.2f}, sustained_verdict={sustained_verdict}")

# Per-neighbor hourly counts
for nb in neighbor_usids:
    nb_entries = [e for e in sustained_log if e['neighbor'] == nb]
    s = sum(1 for e in nb_entries if e['classification'] == 'stable')
    st = sum(1 for e in nb_entries if e['classification'] == 'stressed')
    ov = sum(1 for e in nb_entries if e['classification'] == 'overloaded')
    print(f"  {nb}: stable={s}, stressed={st}, overloaded={ov}")

# Per-hour per-neighbor structured log (for artifact)
hour_log_entries = []
for nb in neighbor_usids:
    for h in outage_hours:
        entries = [e for e in sustained_log if e['neighbor'] == nb and e['hour'] == f'{h:02d}:00']
        if entries:
            e = entries[0]
            key = f'neighbor_{nb}_hour_baseline_mbps'
            hour_log_entries.append({
                'hour': e['hour'],
                'neighbor': nb,
                f'neighbor_{nb}_hour_baseline_mbps': e[key],
                'hour_new_total_mbps': e['hour_new_total_mbps'],
                'classification': e['classification']
            })

# Output the aggregate stable/stressed/overloaded per neighbor
print("\n--- Summary per neighbor for artifact ---")
nb_summary = {}
for nb in neighbor_usids:
    nb_entries = [e for e in sustained_log if e['neighbor'] == nb]
    s = sum(1 for e in nb_entries if e['classification'] == 'stable')
    st = sum(1 for e in nb_entries if e['classification'] == 'stressed')
    ov = sum(1 for e in nb_entries if e['classification'] == 'overloaded')
    nb_summary[nb] = {'stable': s, 'stressed': st, 'overloaded': ov}
    print(f"  {nb}: {nb_summary[nb]}")

# Build the sustained_reasoning_log (one entry per hour for worst neighbor USID_01 + summary)
nb_01_log = [e for e in sustained_log if e['neighbor'] == 'USID_01']
print("\n--- USID_01 hourly log ---")
for e in nb_01_log:
    print(f"  {e['hour']}: baseline={e['neighbor_USID_01_hour_baseline_mbps']}, new_total={e['hour_new_total_mbps']} => {e['classification']}")

# Trend: compare early vs late
print(f"\nTrend assessment: early_rate={early_overloaded/early_slots:.2f}, late_rate={late_overloaded/late_slots:.2f}")
if late_overloaded / late_slots > early_overloaded / early_slots:
    trend = 'worsening'
elif late_overloaded / late_slots < early_overloaded / early_slots:
    trend = 'improving'
else:
    trend = 'stable'
print(f"trend = {trend}")

# Peak hour verdict based on peak hours only
peak_hours_list = [15, 16, 17, 18, 19, 20]
peak_feasibilities = {}
for nb in neighbor_usids:
    frac = absorption_fractions[nb]
    peak_data = df[(df['usid'] == nb) & (df['timestamp_utc'] >= hist_start) & (df['timestamp_utc'] < hist_end)].copy()
    peak_data['hour'] = peak_data['timestamp_utc'].dt.hour
    peak_subset = peak_data[peak_data['hour'].isin(peak_hours_list)]
    peak_baseline = peak_subset['throughput_dl_mbps'].mean()
    peak_p90 = peak_subset['throughput_dl_mbps'].quantile(0.90)
    extra = lost_mbps * frac
    new_total_peak = peak_baseline + extra
    if new_total_peak <= peak_p90 * 0.85:
        pf = 'sufficient'
    elif new_total_peak <= peak_p90:
        pf = 'marginal'
    else:
        pf = 'insufficient'
    peak_feasibilities[nb] = pf

print(f"\nPeak feasibilities: {peak_feasibilities}")
pf_vals = list(peak_feasibilities.values())
if 'sufficient' in pf_vals:
    peak_verdict = 'no_overload'
elif all(f == 'insufficient' for f in pf_vals):
    peak_verdict = 'overload'
else:
    peak_verdict = 'marginal_risk'
print(f"peak_hour_verdict = {peak_verdict}")
