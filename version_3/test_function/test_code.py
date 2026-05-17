import pandas as pd

KPI_data = pd.read_csv('version_3/data/kpi_sector_timeseries.csv')
KPI_data = KPI_data.drop(columns = ['connected_users','prb_utilization_pct','avg_rsrp_dbm','avg_sinr_db'])
KPI_data.to_csv('version_3/data/KPI_data.csv')
