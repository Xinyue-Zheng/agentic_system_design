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

lost_traffic_mbps = 136.4263
lost_volume_gb    = 0.033307

neighbors = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10']

print("=== Neighbor analysis ===")
for n in neighbors:
    nd = df[(df['usid'] == n) & (df['hour'].isin(outage_hours))].copy()
    site_per_ts = nd.groupby('timestamp_utc')['throughput_dl_mbps'].sum().reset_index()
    site_vol_per_ts = nd.groupby('timestamp_utc')['volume_dl_gb'].sum().reset_index()

    baseline_mbps = site_per_ts['throughput_dl_mbps'].mean()
    p90_mbps      = site_per_ts['throughput_dl_mbps'].quantile(0.90)
    baseline_vol  = site_vol_per_ts['volume_dl_gb'].mean()

    af = absorption_fractions[n]
    extra_mbps = lost_traffic_mbps * af
    extra_vol  = lost_volume_gb    * af
    new_total  = baseline_mbps + extra_mbps

    low_thresh      = p90_mbps * 0.85
    moderate_thresh = p90_mbps
    high_thresh     = p90_mbps * 1.20

    if new_total <= low_thresh:
        pressure = "low"
        note = "new_total=%.2f <= p90x0.85=%.2f -> low" % (new_total, low_thresh)
    elif new_total <= moderate_thresh:
        pressure = "moderate"
        note = "new_total=%.2f is %.1f%% of p90=%.2f (85-100%%) -> moderate" % (new_total, new_total/p90_mbps*100, p90_mbps)
    elif new_total <= high_thresh:
        pressure = "high"
        note = "new_total=%.2f > p90=%.2f, <= p90x1.20=%.2f -> high" % (new_total, p90_mbps, high_thresh)
    else:
        pressure = "critical"
        note = "new_total=%.2f > p90x1.20=%.2f -> critical" % (new_total, high_thresh)

    print("%s: baseline=%.4f p90=%.4f vol=%.6f af=%.4f extra=%.4f extra_vol=%.6f new_total=%.4f pressure=%s" % (
        n, baseline_mbps, p90_mbps, baseline_vol, af, extra_mbps, extra_vol, new_total, pressure))
    print("  NOTE: %s" % note)
    print()
