import sys, os, json
sys.path.insert(0, '.')
os.environ['DATA_DIR'] = 'data'
from mcp_server.server import get_kpi_history
from collections import defaultdict
from datetime import datetime, timezone, timedelta

OUTAGE_HOURS = list(range(10, 21))
PEAK_HOURS = [17, 18, 19, 20]
NEIGHBORS = ['USID_01', 'USID_25', 'USID_43', 'USID_29', 'USID_45', 'USID_10']
AFFECTED_SECTORS = ['USID_09_S0', 'USID_09_S2']
outage_date = datetime(2026, 4, 17, tzinfo=timezone.utc)
cutoff_14d = outage_date - timedelta(days=14)

ABSORPTION = {
    'USID_01': 0.5714,
    'USID_25': 0.5000,
    'USID_43': 0.4286,
    'USID_29': 0.1429,
    'USID_45': 0.1190,
    'USID_10': 0.0952,
}

def parse_hour(ts):
    return int(ts.split('T')[1].split(':')[0]) if 'T' in ts else -1

def is_weekday(ts):
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.weekday() < 5
    except:
        return True

def is_recent_14d(ts):
    try:
        t = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return t >= cutoff_14d and t < outage_date
    except:
        return False

def stats(vals):
    if not vals:
        return None
    v = sorted(vals); n = len(v)
    def p(pct):
        i = (pct/100)*(n-1); lo=int(i); hi=min(lo+1,n-1)
        return v[lo]+(i-lo)*(v[hi]-v[lo])
    return {
        'count': n, 'mean': round(sum(v)/n, 2),
        'p10': round(p(10), 2), 'p75': round(p(75), 2), 'p90': round(p(90), 2)
    }

def group_sum_by_ts(records, hour=None):
    by_ts = defaultdict(float)
    for r in records:
        if hour is None or parse_hour(r['timestamp_utc']) == hour:
            by_ts[r['timestamp_utc']] += r['throughput_dl_mbps']
    return list(by_ts.values())

# ------- AFFECTED SECTORS (USID_09 S0+S2) -------
hist09 = get_kpi_history('USID_09')
aff_recs = [r for r in hist09 if r['sector_id'] in AFFECTED_SECTORS and parse_hour(r['timestamp_utc']) in OUTAGE_HOURS]

# Overall
all_vals = group_sum_by_ts(aff_recs)
overall_s = stats(all_vals)

# Per-hour: 60d all-days, weekday, 14d
per_hour_60d = {}
per_hour_wd = {}
per_hour_14d = {}
for h in OUTAGE_HOURS:
    h_recs = [r for r in aff_recs if parse_hour(r['timestamp_utc']) == h]
    per_hour_60d[h] = stats(group_sum_by_ts(h_recs))
    per_hour_wd[h] = stats(group_sum_by_ts([r for r in h_recs if is_weekday(r['timestamp_utc'])]))
    per_hour_14d[h] = stats(group_sum_by_ts([r for r in h_recs if is_recent_14d(r['timestamp_utc'])]))

# Peak hours
peak_recs = [r for r in aff_recs if parse_hour(r['timestamp_utc']) in PEAK_HOURS]
peak_stats = stats(group_sum_by_ts(peak_recs))

# ------- OVERALL base/stress from Step C -------
# Weekday mean for full window = average of per_hour_wd[h]['mean']
wd_means = [per_hour_wd[h]['mean'] for h in OUTAGE_HOURS if per_hour_wd[h]]
base_overall = round(sum(wd_means)/len(wd_means), 2)
stress_overall = overall_s['p90']
print(f"Base overall (weekday mean across window): {base_overall}")
print(f"Stress overall (60d p90 across window): {stress_overall}")
print(f"60d mean (lost_traffic_mbps): {overall_s['mean']}")

# ------- NEIGHBORS -------
neighbor_hour = {}  # neighbor -> hour -> stats
for n in NEIGHBORS:
    hist = get_kpi_history(n)
    window = [r for r in hist if parse_hour(r['timestamp_utc']) in OUTAGE_HOURS]
    neighbor_hour[n] = {}
    for h in OUTAGE_HOURS:
        h_recs = [r for r in window if parse_hour(r['timestamp_utc']) == h]
        neighbor_hour[n][h] = stats(group_sum_by_ts(h_recs))

# Overall neighbor stats
neighbor_overall = {}
for n in NEIGHBORS:
    hist = get_kpi_history(n)
    window = [r for r in hist if parse_hour(r['timestamp_utc']) in OUTAGE_HOURS]
    neighbor_overall[n] = stats(group_sum_by_ts(window))

# ------- HOURLY BASE/STRESS SELECTION -------
def select_hourly(h):
    # Off-peak: base=same_daytype_hour_mean, stress=same_hour_p75
    # Peak: base=same_daytype_hour_mean, stress=same_hour_p90
    base_src = 'same_daytype_hour_mean'
    base_val = per_hour_wd[h]['mean']
    if h in PEAK_HOURS:
        stress_src = 'same_hour_60d_p90'
        stress_val = per_hour_60d[h]['p90']
        reason = f"Peak hour {h:02d}:00; weekday-daytype mean ({base_val}) as base, p90 ({stress_val}) as stress."
        unc = 'low'
    else:
        stress_src = 'same_hour_60d_p75'
        stress_val = per_hour_60d[h]['p75']
        reason = f"Off-peak weekday hour {h:02d}:00; weekday-daytype mean ({base_val}) as base, p75 ({stress_val}) as stress."
        unc = 'low'
    return {
        'base_case_source': base_src,
        'base_case_mbps': base_val,
        'stress_case_source': stress_src,
        'stress_case_mbps': stress_val,
        'selection_reason': reason,
        'uncertainty': unc,
    }

hourly_forecast = {h: select_hourly(h) for h in OUTAGE_HOURS}

# ------- 3-TIER CLASSIFIER -------
def classify3(new_total, p90):
    if new_total <= p90 * 0.85:
        return 'stable'
    elif new_total <= p90:
        return 'stressed'
    else:
        return 'overloaded'

# ------- 4-TIER CLASSIFIER (base layer) -------
def classify4(new_total, p90):
    if new_total <= p90 * 0.85:
        return 'low'
    elif new_total <= p90:
        return 'moderate'
    elif new_total <= p90 * 1.20:
        return 'high'
    else:
        return 'critical'

# ------- PER-NEIGHBOR OVERALL (Step D) -------
per_neighbor = {}
for n in NEIGHBORS:
    af = ABSORPTION[n]
    nb = neighbor_overall[n]
    extra_base = round(base_overall * af, 2)
    extra_stress = round(stress_overall * af, 2)
    new_base = round(nb['mean'] + extra_base, 2)
    new_stress = round(nb['mean'] + extra_stress, 2)
    pb = classify4(new_base, nb['p90'])
    ps = classify4(new_stress, nb['p90'])
    per_neighbor[n] = {
        'absorption_fraction': af,
        'extra_throughput_mbps': extra_base,
        'extra_base_mbps': extra_base,
        'extra_stress_mbps': extra_stress,
        'neighbor_baseline_mbps': nb['mean'],
        'neighbor_p75_mbps': nb['p75'],
        'neighbor_p90_mbps': nb['p90'],
        'new_total_mbps': new_base,
        'new_total_base_mbps': new_base,
        'new_total_stress_mbps': new_stress,
        'capacity_pressure': pb,
        'pressure_base': pb,
        'pressure_stress': ps,
        'pressure_note': f"base {new_base} vs p90 {nb['p90']} ({pb}); stress {new_stress} ({ps})",
        'forecast_note': f"Extra traffic: base={extra_base} Mbps, stress={extra_stress} Mbps at af={af}",
    }

print("\n=== PER-NEIGHBOR OVERALL ===")
for n, v in per_neighbor.items():
    print(f"{n}: pb={v['pressure_base']}, ps={v['pressure_stress']}, new_base={v['new_total_base_mbps']}, new_stress={v['new_total_stress_mbps']}, p90={v['neighbor_p90_mbps']}")

# ------- HOURLY NEIGHBOR FORECAST -------
hourly_neighbor_forecast = {}
for h in OUTAGE_HOURS:
    hfc = hourly_forecast[h]
    hourly_neighbor_forecast[f"{h:02d}:00"] = {}
    worst_base = 'stable'
    worst_stress = 'stable'
    worst_base_n = ''
    worst_stress_n = ''
    tier_order = ['stable', 'stressed', 'overloaded']

    for n in NEIGHBORS:
        af = ABSORPTION[n]
        nh = neighbor_hour[n][h]
        extra_b = round(hfc['base_case_mbps'] * af, 2)
        extra_s = round(hfc['stress_case_mbps'] * af, 2)
        new_b = round(nh['mean'] + extra_b, 2)
        new_s = round(nh['mean'] + extra_s, 2)
        cb = classify3(new_b, nh['p90'])
        cs = classify3(new_s, nh['p90'])
        hourly_neighbor_forecast[f"{h:02d}:00"][n] = {
            'neighbor_hour_baseline_mbps': nh['mean'],
            'neighbor_hour_p75_mbps': nh['p75'],
            'neighbor_hour_p90_mbps': nh['p90'],
            'extra_base_mbps': extra_b,
            'extra_stress_mbps': extra_s,
            'new_total_base_mbps': new_b,
            'new_total_stress_mbps': new_s,
            'classification_base': cb,
            'classification_stress': cs,
        }
        if tier_order.index(cb) > tier_order.index(worst_base):
            worst_base = cb; worst_base_n = n
        if tier_order.index(cs) > tier_order.index(worst_stress):
            worst_stress = cs; worst_stress_n = n
    hourly_neighbor_forecast[f"{h:02d}:00"]['_worst_base'] = worst_base
    hourly_neighbor_forecast[f"{h:02d}:00"]['_worst_stress'] = worst_stress
    hourly_neighbor_forecast[f"{h:02d}:00"]['_worst_base_usid'] = worst_base_n
    hourly_neighbor_forecast[f"{h:02d}:00"]['_worst_stress_usid'] = worst_stress_n

print("\n=== HOURLY WORST CLASSIFICATION ===")
base_dist = {'stable': 0, 'stressed': 0, 'overloaded': 0}
stress_dist = {'stable': 0, 'stressed': 0, 'overloaded': 0}
for h in OUTAGE_HOURS:
    hk = f"{h:02d}:00"
    wb = hourly_neighbor_forecast[hk]['_worst_base']
    ws = hourly_neighbor_forecast[hk]['_worst_stress']
    base_dist[wb] += 1
    stress_dist[ws] += 1
    print(f"  {hk}: worst_base={wb}, worst_stress={ws}")

print(f"\nBase distribution: {base_dist}")
print(f"Stress distribution: {stress_dist}")

# ------- OUTPUT DATA FOR ARTIFACT -------
print("\n=== HOURLY CANDIDATES + FORECASTS (for artifact) ===")
for h in OUTAGE_HOURS:
    hk = f"{h:02d}:00"
    s60 = per_hour_60d[h]
    swd = per_hour_wd[h]
    s14 = per_hour_14d[h]
    hf = hourly_forecast[h]
    print(f"{hk}: 60d_mean={s60['mean']}, 60d_p75={s60['p75']}, 60d_p90={s60['p90']}, wd_mean={swd['mean']}, 14d_mean={s14['mean'] if s14 else 'null'}")
    print(f"     selected: base={hf['base_case_mbps']} ({hf['base_case_source']}), stress={hf['stress_case_mbps']} ({hf['stress_case_source']})")
