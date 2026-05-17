import sys, os
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')

import json
import datetime
from mcp_server.server import get_kpi_history

OUTAGE_HOURS = list(range(10, 21))
PEAK_HOURS   = [17, 18, 19, 20]
AFFECTED_SECTORS = ["USID_09_S0", "USID_09_S2"]
OUTAGE_DATE  = datetime.date(2026, 4, 17)


def compute_stats(records, sectors=None, hours=None):
    filtered = []
    for r in records:
        sid = r['sector_id']
        if sectors and sid not in sectors:
            continue
        ts = r['timestamp_utc']
        hour = int(ts[11:13])
        if hours and hour not in hours:
            continue
        filtered.append(r['throughput_dl_mbps'])

    if not filtered:
        return None
    arr = sorted(filtered)
    n = len(arr)
    mean = sum(arr)/n
    p75  = arr[int(0.75*n)]
    p90  = arr[int(0.90*n)]
    p10  = arr[int(0.10*n)]
    return {"mean": round(mean,2), "p75": round(p75,2), "p90": round(p90,2),
            "p10": round(p10,2), "n": n}


def compute_daytype_stats(records, sectors=None, hours=None, day_of_week="weekday"):
    filtered = []
    for r in records:
        sid = r['sector_id']
        if sectors and sid not in sectors:
            continue
        ts = r['timestamp_utc']
        hour = int(ts[11:13])
        if hours and hour not in hours:
            continue
        date_str = ts[:10]
        dt = datetime.date.fromisoformat(date_str)
        dow = dt.weekday()
        if day_of_week == "weekday" and dow >= 5:
            continue
        if day_of_week == "weekend" and dow < 5:
            continue
        filtered.append(r['throughput_dl_mbps'])

    if not filtered:
        return None
    arr = sorted(filtered)
    n = len(arr)
    mean = sum(arr)/n
    p75  = arr[int(0.75*n)]
    p90  = arr[int(0.90*n)]
    p10  = arr[int(0.10*n)]
    return {"mean": round(mean,2), "p75": round(p75,2), "p90": round(p90,2),
            "p10": round(p10,2), "n": n}


def compute_recent14_stats(records, sectors=None, hours=None):
    cutoff = OUTAGE_DATE - datetime.timedelta(days=14)
    filtered = []
    for r in records:
        sid = r['sector_id']
        if sectors and sid not in sectors:
            continue
        ts = r['timestamp_utc']
        hour = int(ts[11:13])
        if hours and hour not in hours:
            continue
        date_str = ts[:10]
        dt = datetime.date.fromisoformat(date_str)
        if dt < cutoff:
            continue
        filtered.append(r['throughput_dl_mbps'])

    if not filtered:
        return None
    arr = sorted(filtered)
    n = len(arr)
    mean = sum(arr)/n
    p75  = arr[int(0.75*n)]
    p90  = arr[int(0.90*n)]
    return {"mean": round(mean,2), "p75": round(p75,2), "p90": round(p90,2), "n": n}


# ---- AFFECTED USID_09 ----
print("=== USID_09 affected sectors (S0+S2) ===")
hist09 = get_kpi_history("USID_09")
print(f"Total records: {len(hist09)}")
sectors_09 = set(r['sector_id'] for r in hist09)
print(f"Sectors: {sorted(sectors_09)}")

s_all  = compute_stats(hist09, sectors=AFFECTED_SECTORS, hours=OUTAGE_HOURS)
s_wday = compute_daytype_stats(hist09, sectors=AFFECTED_SECTORS, hours=OUTAGE_HOURS, day_of_week="weekday")
s_14   = compute_recent14_stats(hist09, sectors=AFFECTED_SECTORS, hours=OUTAGE_HOURS)
s_peak = compute_stats(hist09, sectors=AFFECTED_SECTORS, hours=PEAK_HOURS)
print(f"60d outage-window: {s_all}")
print(f"Weekday same-hour: {s_wday}")
print(f"Recent 14d:        {s_14}")
print(f"Peak-hour only:    {s_peak}")

print("\nPer-hour for S0+S2:")
hour_data = {}
for h in OUTAGE_HOURS:
    s  = compute_stats(hist09, sectors=AFFECTED_SECTORS, hours=[h])
    sd = compute_daytype_stats(hist09, sectors=AFFECTED_SECTORS, hours=[h], day_of_week="weekday")
    s4 = compute_recent14_stats(hist09, sectors=AFFECTED_SECTORS, hours=[h])
    hour_data[h] = {"60d": s, "weekday": sd, "14d": s4}
    wm = sd['mean'] if sd else None
    fm = s4['mean'] if s4 else None
    sp75 = s['p75'] if s else None
    sp90 = s['p90'] if s else None
    print(f"  H{h:02d}: 60d_mean={s['mean'] if s else None}, p75={sp75}, p90={sp90}, n={s['n'] if s else 0} | wday={wm} | 14d={fm}")

# ---- NEIGHBORS ----
NEIGHBORS = ["USID_01", "USID_25", "USID_43", "USID_29", "USID_45", "USID_10"]
neighbor_hour_data = {}

print("\n=== NEIGHBOR STATS ===")
for nb in NEIGHBORS:
    hist = get_kpi_history(nb)
    nb_sectors = set(r['sector_id'] for r in hist)
    s_all_nb   = compute_stats(hist, hours=OUTAGE_HOURS)
    s_wday_nb  = compute_daytype_stats(hist, hours=OUTAGE_HOURS, day_of_week="weekday")
    s_14_nb    = compute_recent14_stats(hist, hours=OUTAGE_HOURS)
    print(f"\n{nb} (sectors: {sorted(nb_sectors)})")
    print(f"  60d outage-window: mean={s_all_nb['mean'] if s_all_nb else None}, p75={s_all_nb['p75'] if s_all_nb else None}, p90={s_all_nb['p90'] if s_all_nb else None}, n={s_all_nb['n'] if s_all_nb else 0}")

    per_hour = {}
    print(f"  Per-hour:")
    for h in OUTAGE_HOURS:
        sh = compute_stats(hist, hours=[h])
        per_hour[h] = sh
        if sh:
            print(f"    H{h:02d}: mean={sh['mean']}, p75={sh['p75']}, p90={sh['p90']}, n={sh['n']}")
    neighbor_hour_data[nb] = per_hour

print("\nDone.")
