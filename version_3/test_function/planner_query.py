import sys, os
os.environ['DATA_DIR'] = '/workspace/version_3/data'
sys.path.insert(0, '/workspace/version_3/mcp_server')
import pandas as pd
import json

kpi_df = pd.read_csv('/workspace/version_3/data/KPI_data.csv')
kpi_df['timestamp_utc'] = pd.to_datetime(kpi_df['timestamp_utc'], utc=True)

df = kpi_df[kpi_df['usid'] == 'USID_09'].copy()
print(f'Total rows for USID_09: {len(df)}')
print(f'Sectors: {df["sector_id"].unique().tolist()}')
print(f'Date range: {df["timestamp_utc"].min()} to {df["timestamp_utc"].max()}')

df['hour'] = df['timestamp_utc'].dt.hour
hourly = df.groupby('hour')['throughput_dl_mbps'].mean().sort_values(ascending=False)
print('\nAll hours by mean throughput_dl_mbps (sorted):')
print(hourly.to_string())

sector_avgs = df.groupby('sector_id')['throughput_dl_mbps'].mean()
print('\nSector 60-day averages:')
print(sector_avgs.to_string())
