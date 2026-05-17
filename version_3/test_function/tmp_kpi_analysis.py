import pandas as pd
import numpy as np

df = pd.read_csv("data/KPI_data.csv")
df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
df["hour"] = df["timestamp_utc"].dt.hour

OUTAGE_HOURS = set(range(24))
PEAK_HOURS   = {18, 19, 20}

lost_mbps        = 139.6971
lost_vol_gb      = 0.0340
peak_lost_mbps   = 245.4776
peak_lost_vol_gb = 0.0599

absorption = {
    "USID_05": 0.7027,
    "USID_06": 0.1351,
    "USID_27": 0.0541,
    "USID_30": 0.4595,
    "USID_36": 0.2432,
    "USID_44": 0.1622,
}

print("=== STEP 3: Neighbor analysis ===\n")
results = {}

for nbr, frac in sorted(absorption.items()):
    sub = df[df["usid"] == nbr]

    base_filt = sub[sub["hour"].isin(OUTAGE_HOURS)]
    base_mean = base_filt["throughput_dl_mbps"].mean()
    base_p90  = base_filt["throughput_dl_mbps"].quantile(0.90)
    base_vol  = base_filt["volume_dl_gb"].mean()

    extra_mbps   = lost_mbps * frac
    extra_vol_gb = lost_vol_gb * frac
    new_total    = base_mean + extra_mbps
    threshold    = base_p90 * 0.85

    if new_total <= base_p90 * 0.85:
        feasibility = "sufficient"
    elif new_total <= base_p90:
        feasibility = "marginal"
    else:
        feasibility = "insufficient"

    peak_filt      = sub[sub["hour"].isin(PEAK_HOURS)]
    peak_mean      = peak_filt["throughput_dl_mbps"].mean()
    peak_p90       = peak_filt["throughput_dl_mbps"].quantile(0.90)
    peak_vol       = peak_filt["volume_dl_gb"].mean()

    peak_extra     = peak_lost_mbps * frac
    new_peak_total = peak_mean + peak_extra

    if new_peak_total <= peak_p90 * 0.85:
        peak_feas = "sufficient"
    elif new_peak_total <= peak_p90:
        peak_feas = "marginal"
    else:
        peak_feas = "insufficient"

    results[nbr] = dict(
        frac=frac,
        base_mean=round(base_mean, 4),
        base_p90=round(base_p90, 4),
        base_vol=round(base_vol, 4),
        extra_mbps=round(extra_mbps, 4),
        extra_vol_gb=round(extra_vol_gb, 4),
        new_total=round(new_total, 4),
        threshold85=round(threshold, 4),
        feasibility=feasibility,
        peak_mean=round(peak_mean, 4),
        peak_p90=round(peak_p90, 4),
        peak_vol=round(peak_vol, 4),
        peak_extra=round(peak_extra, 4),
        new_peak_total=round(new_peak_total, 4),
        peak_threshold85=round(peak_p90*0.85, 4),
        peak_feas=peak_feas,
    )

    print(f"--- {nbr} (absorption={frac}) ---")
    print(f"  BASE: baseline={base_mean:.4f} p90={base_p90:.4f} extra={extra_mbps:.4f} new_total={new_total:.4f} 85pct_p90={threshold:.4f} -> {feasibility}")
    print(f"  PEAK: baseline={peak_mean:.4f} p90={peak_p90:.4f} extra={peak_extra:.4f} new_total={new_peak_total:.4f} 85pct_p90={peak_p90*0.85:.4f} -> {peak_feas}")
    print()

base_feas_list = [v["feasibility"] for v in results.values()]
peak_feas_list = [v["peak_feas"] for v in results.values()]

if "sufficient" in base_feas_list:
    overload_verdict = "no_overload"
elif "marginal" in base_feas_list:
    overload_verdict = "marginal_risk"
else:
    overload_verdict = "overload"

if "sufficient" in peak_feas_list:
    peak_verdict = "manageable"
elif "marginal" in peak_feas_list:
    peak_verdict = "elevated_risk"
else:
    peak_verdict = "critical"

print("=== VERDICTS ===")
print(f"Base feasibilities: {base_feas_list}")
print(f"overload_verdict  : {overload_verdict}")
print(f"Peak feasibilities: {peak_feas_list}")
print(f"peak_hour_verdict : {peak_verdict}")
print()
print("=== RAW RESULTS FOR ARTIFACT ===")
import json
print(json.dumps(results, indent=2))
