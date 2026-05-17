import pandas as pd
import numpy as np

df = pd.read_csv('data/KPI_data.csv')
df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'])
df['hour'] = df['timestamp_utc'].dt.hour

outage_hours = list(range(10, 21))

absorption_fractions = {
    'USID_01': 0.5714,
    'USID_25': 0.50,
    'USID_43': 0.4286,
    'USID_29': 0.1429,
    'USID_45': 0.1190,
    'USID_10': 0.0952,
}

# From base (no adjustment factor since weekday+unknown=1.00)
lost_traffic_mbps = 136.4263
lost_volume_gb    = 0.033307

neighbors = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10']

# Per-hour, per-neighbor computation
print("=== Sustained hourly analysis ===")
hourly_summary = []

for h in outage_hours:
    worst_class = "stable"
    worst_class_num = 0
    worst_neighbor = None
    worst_new_total = None
    worst_baseline = None
    worst_p90 = None
    worst_baseline_vol = None
    worst_new_vol = None

    for n in neighbors:
        nd = df[(df['usid'] == n) & (df['hour'] == h)].copy()
        if nd.empty:
            continue
        site_per_ts = nd.groupby('timestamp_utc')['throughput_dl_mbps'].sum().reset_index()
        site_vol_per_ts = nd.groupby('timestamp_utc')['volume_dl_gb'].sum().reset_index()

        hour_baseline_mbps = site_per_ts['throughput_dl_mbps'].mean()
        hour_p90_mbps      = site_per_ts['throughput_dl_mbps'].quantile(0.90)
        hour_baseline_vol  = site_vol_per_ts['volume_dl_gb'].mean()

        af = absorption_fractions[n]
        extra_mbps = lost_traffic_mbps * af
        extra_vol  = lost_volume_gb    * af
        new_total  = hour_baseline_mbps + extra_mbps
        new_vol    = hour_baseline_vol  + extra_vol

        low_thresh = hour_p90_mbps * 0.85
        if new_total <= low_thresh:
            cls = "stable"
            cls_num = 0
        elif new_total <= hour_p90_mbps:
            cls = "stressed"
            cls_num = 1
        else:
            cls = "overloaded"
            cls_num = 2

        if cls_num > worst_class_num:
            worst_class_num = cls_num
            worst_class = cls
            worst_neighbor = n
            worst_new_total = new_total
            worst_baseline = hour_baseline_mbps
            worst_p90 = hour_p90_mbps
            worst_baseline_vol = hour_baseline_vol
            worst_new_vol = new_vol

    hourly_summary.append({
        'hour': h,
        'worst_neighbor': worst_neighbor,
        'worst_class': worst_class,
        'hour_baseline_mbps': worst_baseline,
        'hour_p90_mbps': worst_p90,
        'new_total_mbps': worst_new_total,
        'hour_baseline_vol_gb': worst_baseline_vol,
        'new_total_vol_gb': worst_new_vol,
    })
    print("Hour %02d: worst=%s class=%s baseline=%.4f p90=%.4f new_total=%.4f vol_base=%.6f new_vol=%.6f" % (
        h, worst_neighbor, worst_class, worst_baseline, worst_p90, worst_new_total,
        worst_baseline_vol, worst_new_vol))

# Counts
stable_count    = sum(1 for r in hourly_summary if r['worst_class'] == 'stable')
stressed_count  = sum(1 for r in hourly_summary if r['worst_class'] == 'stressed')
overloaded_count= sum(1 for r in hourly_summary if r['worst_class'] == 'overloaded')
print()
print("stable=%d stressed=%d overloaded=%d" % (stable_count, stressed_count, overloaded_count))

# Trend: first half vs second half
n_hours = len(hourly_summary)
mid = n_hours // 2
first_half_score = sum(2 if r['worst_class']=='overloaded' else (1 if r['worst_class']=='stressed' else 0) for r in hourly_summary[:mid])
second_half_score= sum(2 if r['worst_class']=='overloaded' else (1 if r['worst_class']=='stressed' else 0) for r in hourly_summary[mid:])
first_half_n  = mid
second_half_n = n_hours - mid
first_prop  = first_half_score  / (first_half_n  * 2)
second_prop = second_half_score / (second_half_n * 2)
diff = second_prop - first_prop
print("Trend: first_half_prop=%.2f second_half_prop=%.2f diff=%.2f" % (first_prop, second_prop, diff))
if diff < -0.10:
    trend = "improving"
elif diff > 0.10:
    trend = "worsening"
else:
    trend = "stable"
print("trend=%s" % trend)

# Peak hours
peak_hours_within_window = [17, 18, 19, 20]
print()
print("=== Peak hour classifications ===")
for r in hourly_summary:
    if r['hour'] in peak_hours_within_window:
        print("  %02d:00 -> %s" % (r['hour'], r['worst_class']))
