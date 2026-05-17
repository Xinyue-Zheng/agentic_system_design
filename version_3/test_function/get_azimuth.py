import pandas as pd

df = pd.read_csv('data/KPI_data.csv')
rows = df[df['usid'] == 'USID_09'][['sector_id', 'azimuth_deg']].drop_duplicates()
print(rows.to_string(index=False))
