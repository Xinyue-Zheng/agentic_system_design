import sys, os, json
os.environ['DATA_DIR'] = '/workspace/version_3/data'
import pandas as pd
from collections import Counter

kpi_df = pd.read_csv('/workspace/version_3/data/KPI_data.csv')
kpi_df['timestamp_utc'] = pd.to_datetime(kpi_df['timestamp_utc'], utc=True)

usid = 'USID_09'
df = kpi_df[kpi_df['usid'] == usid].copy()
df['hour'] = df['timestamp_utc'].dt.hour
hourly = df.groupby('hour')['throughput_dl_mbps'].mean().sort_values(ascending=False)
print('=== KPI HISTORY: USID_09 ===')
print(f'Total rows: {len(df)}')
print(f'Sectors: {df["sector_id"].unique().tolist()}')
print('\nHourly mean throughput_dl_mbps (all sectors, sorted desc):')
for hour, val in hourly.items():
    print(f'  {hour:02d}:00  {val:.2f}')

outage_start = 10 + 31/60
outage_end = 20 + 58/60
peak_hours_in_window = [h for h, v in hourly.items() if outage_start <= h <= outage_end]
peak_hours_in_window.sort()
print(f'\nOutage window: 10:31 - 20:58 UTC')
print(f'Peak hours in window: {[f"{h:02d}:00" for h in peak_hours_in_window]}')

sector_avgs = df.groupby('sector_id')['throughput_dl_mbps'].mean()
print('\nSector 60-day averages:')
print(sector_avgs.to_string())
