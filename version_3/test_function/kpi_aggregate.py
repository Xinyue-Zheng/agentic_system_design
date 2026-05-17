import sys, os
os.environ['DATA_DIR'] = 'data'
sys.path.insert(0, '.')
import json, datetime
from collections import defaultdict
from mcp_server.server import get_kpi_history

OUTAGE_HOURS = list(range(10, 21))
PEAK_HOURS   = [17, 18, 19, 20]
OUTAGE_DATE  = datetime.date(2026, 4, 17)
AFFECTED_SECTORS = ["USID_09_S0", "USID_09_S2"]


def agg_by_ts(records, sectors=None, hours=None):
    """Sum throughput across sectors at each timestamp, filter by hours."""
    by_ts = defaultdict(float)
    for r in records:
        sid = r['sector_id']
        if sectors and sid not in sectors:
            continue
        ts = r['timestamp_utc']
        hour = int(ts[11:13])
        if hours and hour not in hours:
            continue
        by_ts[ts] += r['throughput_dl_mbps']
    return by_ts


def stats_from_values(values):
    if not values:
        return None
    arr = sorted(values)
    n = len(arr)
    mean = sum(arr) / n
    p10  = arr[int(0.10 * n)]
    p75  = arr[int(0.75 * n)]
    p90  = arr[int(0.90 * n)]
    return {"mean": round(mean, 2), "p75": round(p75, 2), "p90": round(p90, 2),
            "p10": round(p10, 2), "n": n}


def agg_stats(records, sectors=None, hours=None):
    by_ts = agg_by_ts(records, sectors, hours)
    return stats_from_values(list(by_ts.values()))


def agg_daytype_stats(records, sectors=None, hours=None, day_of_week="weekday"):
    by_ts = agg_by_ts(records, sectors, hours)
    filtered = []
    for ts, val in by_ts.items():
        dt = datetime.date.fromisoformat(ts[:10])
        dow = dt.weekday()
        if day_of_week == "weekday" and dow >= 5:
            continue
        if day_of_week == "weekend" and dow < 5:
            continue
        filtered.append(val)
    return stats_from_values(filtered)


def agg_recent14_stats(records, sectors=None, hours=None):
    cutoff = OUTAGE_DATE - datetime.timedelta(days=14)
    by_ts = agg_by_ts(records, sectors, hours)
    filtered = []
    for ts, val in by_ts.items():
        dt = datetime.date.fromisoformat(ts[:10])
        if dt >= cutoff:
            filtered.append(val)
    return stats_from_values(filtered)


def agg_stats_hour(records, sectors=None, hour=None):
    return agg_stats(records, sectors=sectors, hours=[hour] if hour is not None else None)


def agg_daytype_hour(records, sectors=None, hour=None):
    return agg_daytype_stats(records, sectors=sectors, hours=[hour] if hour is not None else None, day_of_week="weekday")


def agg_recent14_hour(records, sectors=None, hour=None):
    return agg_recent14_stats(records, sectors=sectors, hours=[hour] if hour is not None else None)


print("=" * 60)
print("USID_09 AFFECTED SECTORS (S0+S2) - AGGREGATE THROUGHPUT")
print("=" * 60)
hist09 = get_kpi_history("USID_09")

s_all  = agg_stats(hist09, sectors=AFFECTED_SECTORS, hours=OUTAGE_HOURS)
s_wday = agg_daytype_stats(hist09, sectors=AFFECTED_SECTORS, hours=OUTAGE_HOURS)
s_14   = agg_recent14_stats(hist09, sectors=AFFECTED_SECTORS, hours=OUTAGE_HOURS)
s_peak = agg_stats(hist09, sectors=AFFECTED_SECTORS, hours=PEAK_HOURS)

print(f"60d outage-window agg: {s_all}")
print(f"Weekday same-hour agg: {s_wday}")
print(f"Recent 14d agg:        {s_14}")
print(f"Peak-hour (17-20) agg: {s_peak}")

print("\nPer-hour (aggregate S0+S2):")
usid09_hour_data = {}
for h in OUTAGE_HOURS:
    s  = agg_stats_hour(hist09, sectors=AFFECTED_SECTORS, hour=h)
    sd = agg_daytype_hour(hist09, sectors=AFFECTED_SECTORS, hour=h)
    s4 = agg_recent14_hour(hist09, sectors=AFFECTED_SECTORS, hour=h)
    usid09_hour_data[h] = {"60d": s, "weekday": sd, "14d": s4}
    print(f"  H{h:02d}: mean={s['mean'] if s else None}, p75={s['p75'] if s else None}, "
          f"p90={s['p90'] if s else None}, n={s['n'] if s else 0} "
          f"| wday_mean={sd['mean'] if sd else None} "
          f"| 14d_mean={s4['mean'] if s4 else None}")

print("\n" + "=" * 60)
print("NEIGHBOR AGGREGATE STATS")
print("=" * 60)
NEIGHBORS = ["USID_01", "USID_25", "USID_43", "USID_29", "USID_45", "USID_10"]

neighbor_data = {}
for nb in NEIGHBORS:
    hist = get_kpi_history(nb)
    s_all_nb   = agg_stats(hist, hours=OUTAGE_HOURS)
    s_wday_nb  = agg_daytype_stats(hist, hours=OUTAGE_HOURS)
    s_14_nb    = agg_recent14_stats(hist, hours=OUTAGE_HOURS)
    print(f"\n{nb}:")
    print(f"  60d agg: mean={s_all_nb['mean'] if s_all_nb else None}, "
          f"p75={s_all_nb['p75'] if s_all_nb else None}, "
          f"p90={s_all_nb['p90'] if s_all_nb else None}, "
          f"n={s_all_nb['n'] if s_all_nb else 0}")

    per_hour = {}
    for h in OUTAGE_HOURS:
        sh = agg_stats_hour(hist, hour=h)
        sd_h = agg_daytype_hour(hist, hour=h)
        s4_h = agg_recent14_hour(hist, hour=h)
        per_hour[h] = {"60d": sh, "weekday": sd_h, "14d": s4_h}

    neighbor_data[nb] = {
        "window": s_all_nb,
        "weekday": s_wday_nb,
        "recent14": s_14_nb,
        "per_hour": per_hour
    }

    print(f"  Per-hour:")
    for h in OUTAGE_HOURS:
        ph = per_hour[h]
        sh = ph['60d']
        print(f"    H{h:02d}: mean={sh['mean'] if sh else None}, "
              f"p75={sh['p75'] if sh else None}, "
              f"p90={sh['p90'] if sh else None}, "
              f"n={sh['n'] if sh else 0}")

print("\nDone.")
