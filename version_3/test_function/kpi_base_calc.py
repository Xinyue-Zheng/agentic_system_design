import os
os.environ['DATA_DIR'] = 'data'
import sys
sys.path.insert(0, '.')
from mcp_server.server import get_kpi_history, get_kpi_timeseries
from collections import defaultdict
import json

hist = get_kpi_history('USID_09')
by_sec = defaultdict(list)
for r in hist:
    by_sec[r['sector_id']].append(r['throughput_dl_mbps'])

sector_avgs = {}
for sec, vals in by_sec.items():
    sector_avgs[sec] = round(sum(vals)/len(vals), 4)

print('USID_09 Sector historical averages:')
for s, v in sorted(sector_avgs.items()):
    print(f'  {s}: {v:.4f} Mbps')
total_hist = sum(sector_avgs.values())
print(f'  Total baseline: {total_hist:.4f} Mbps')

S0_hist = sector_avgs.get('USID_09_S0', 0)
S2_hist = sector_avgs.get('USID_09_S2', 0)
S1_hist = sector_avgs.get('USID_09_S1', 0)
print(f'  S0 (failed): {S0_hist:.4f}, S2 (failed): {S2_hist:.4f}, S1 (active): {S1_hist:.4f}')

ts = get_kpi_timeseries('USID_09', '2026-04-17T10:31:15Z', '2026-04-17T20:58:56Z')
by_sec_ts = defaultdict(list)
for r in ts:
    by_sec_ts[r['sector_id']].append(r['throughput_dl_mbps'])

print()
print('USID_09 Actual (outage window):')
for s, vals in sorted(by_sec_ts.items()):
    print(f'  {s}: {sum(vals)/len(vals):.4f} Mbps ({len(vals)} records)')

lost = S0_hist + S2_hist
loss_ratio = round(lost / total_hist, 4)
print(f'\n  Lost traffic (S0+S2 hist avg): {lost:.4f} Mbps')
print(f'  Loss ratio: {loss_ratio:.4f}')
print(f'  Total baseline: {total_hist:.4f} Mbps')
