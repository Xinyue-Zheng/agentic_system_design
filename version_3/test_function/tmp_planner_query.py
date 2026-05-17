import pandas as pd
import os

DATA_DIR = 'data'
kpi_path = os.path.join(DATA_DIR, 'KPI_data.csv')
df = pd.read_csv(kpi_path)
df['timestamp_utc'] = pd.to_datetime(df['timestamp_utc'], utc=True)

usid_df = df[df['usid'] == 'USID_09'].copy()
print('Sectors:', usid_df['sector_id'].unique().tolist())
print('Total rows:', len(usid_df))

usid_df['hour'] = usid_df['timestamp_utc'].dt.hour
hourly = usid_df.groupby('hour')['throughput_dl_mbps'].mean().sort_values(ascending=False)
print()
print('Hourly mean throughput (all hours):')
print(hourly.to_string())
print()

hist_avg = usid_df.groupby('sector_id')['throughput_dl_mbps'].mean()
print('60-day avg per sector:')
print(hist_avg.to_string())
