"""Build kpi_agent_artifact.json for run TKT-2026-04-17-0002_20260507T091321Z"""
import json, os, datetime

OUTAGE_HOURS = list(range(10, 21))
PEAK_HOURS = [17, 18, 19, 20]

# ---- AFFECTED USID_09 S0+S2 data (from get_kpi_history, filtered) ----
aff = {
    "same_hour_60d_mean_mbps": 136.43,
    "same_hour_60d_p75_mbps": 154.60,
    "same_hour_60d_p90_mbps": 171.89,
    "same_hour_60d_p10_mbps": 104.01,
    "same_daytype_same_hour_mean_mbps": 144.68,  # weekday
    "recent_14d_same_hour_mean_mbps": 132.28,
    "peak_hour_mean_mbps": 155.71,  # hours 17-20 only
}

# Hourly candidates (S0+S2 aggregate, from get_kpi_history filtered per hour)
hourly_cands = {
    10: {"mean": 119.53, "p75": 130.68, "p90": 136.73, "p10": None, "wday": 127.38, "d14": 118.78},
    11: {"mean": 123.04, "p75": 135.57, "p90": 139.41, "p10": None, "wday": 130.26, "d14": 119.53},
    12: {"mean": 125.72, "p75": 139.52, "p90": 145.38, "p10": None, "wday": 133.52, "d14": 121.79},
    13: {"mean": 120.56, "p75": 134.71, "p90": 139.53, "p10": None, "wday": 128.23, "d14": 116.92},
    14: {"mean": 121.58, "p75": 134.09, "p90": 140.04, "p10": None, "wday": 128.60, "d14": 117.12},
    15: {"mean": 129.14, "p75": 142.69, "p90": 148.16, "p10": None, "wday": 136.80, "d14": 124.56},
    16: {"mean": 138.27, "p75": 152.47, "p90": 159.79, "p10": None, "wday": 146.45, "d14": 134.07},
    17: {"mean": 147.59, "p75": 162.77, "p90": 170.29, "p10": None, "wday": 156.47, "d14": 143.57},
    18: {"mean": 155.17, "p75": 170.45, "p90": 178.59, "p10": None, "wday": 164.20, "d14": 150.70},
    19: {"mean": 163.36, "p75": 179.83, "p90": 188.79, "p10": None, "wday": 173.38, "d14": 155.46},
    20: {"mean": 156.72, "p75": 174.71, "p90": 181.82, "p10": None, "wday": 166.13, "d14": 152.56},
}

# Hourly lost traffic forecast selection:
# Off-peak (10-16): base=mean, stress=p75
# Peak (17-20): base=wday, stress=p90
def hour_forecast(h):
    c = hourly_cands[h]
    if h in PEAK_HOURS:
        return {
            "base_case_source": "same_daytype_hour_mean_mbps",
            "base_case_mbps": c["wday"],
            "stress_case_source": "same_hour_60d_p90_mbps",
            "stress_case_mbps": c["p90"],
            "selection_reason": "Peak hour; weekday same-hour mean used as base (day-type context), 60d p90 as stress.",
            "uncertainty": "medium"
        }
    else:
        return {
            "base_case_source": "same_hour_60d_mean_mbps",
            "base_case_mbps": c["mean"],
            "stress_case_source": "same_hour_60d_p75_mbps",
            "stress_case_mbps": c["p75"],
            "selection_reason": "Off-peak weekday; 60d same-hour mean is the most stable anchor; p75 for stress.",
            "uncertainty": "low"
        }

hourly_lost_forecast = {f"{h:02d}:00": hour_forecast(h) for h in OUTAGE_HOURS}

# ---- NEIGHBOR DATA (from get_kpi_history, filtered to outage_window_hours) ----
# absorption fractions from preprocessing_stats per_backup
NB_CONFIG = {
    "USID_01": {
        "absorption_fraction": 0.5714,
        "window_mean": 188.14, "window_p75": 212.12, "window_p90": 232.63,
        "window_vol_mean": 0.0459,
        "per_hour": {
            10: {"mean": 162.31, "p75": 176.02, "p90": 181.47},
            11: {"mean": 169.24, "p75": 184.20, "p90": 189.48},
            12: {"mean": 172.68, "p75": 187.25, "p90": 194.03},
            13: {"mean": 166.92, "p75": 180.21, "p90": 186.82},
            14: {"mean": 168.10, "p75": 183.96, "p90": 190.30},
            15: {"mean": 179.98, "p75": 194.20, "p90": 203.66},
            16: {"mean": 190.38, "p75": 206.31, "p90": 214.54},
            17: {"mean": 204.14, "p75": 221.96, "p90": 229.58},
            18: {"mean": 213.72, "p75": 230.93, "p90": 239.90},
            19: {"mean": 226.54, "p75": 245.65, "p90": 254.66},
            20: {"mean": 215.55, "p75": 236.97, "p90": 251.87},
        }
    },
    "USID_25": {
        "absorption_fraction": 0.5000,
        "window_mean": 169.28, "window_p75": 189.62, "window_p90": 210.33,
        "window_vol_mean": 0.0413,
        "per_hour": {
            10: {"mean": 146.40, "p75": 158.51, "p90": 165.29},
            11: {"mean": 152.69, "p75": 164.67, "p90": 172.01},
            12: {"mean": 155.39, "p75": 167.62, "p90": 174.77},
            13: {"mean": 150.48, "p75": 162.59, "p90": 170.95},
            14: {"mean": 151.10, "p75": 163.92, "p90": 170.27},
            15: {"mean": 161.29, "p75": 175.69, "p90": 180.38},
            16: {"mean": 172.26, "p75": 187.70, "p90": 193.70},
            17: {"mean": 182.55, "p75": 198.81, "p90": 204.69},
            18: {"mean": 192.35, "p75": 209.11, "p90": 216.41},
            19: {"mean": 203.74, "p75": 221.27, "p90": 228.28},
            20: {"mean": 193.82, "p75": 212.23, "p90": 224.07},
        }
    },
    "USID_43": {
        "absorption_fraction": 0.4286,
        "window_mean": 179.19, "window_p75": 200.98, "window_p90": 222.82,
        "window_vol_mean": 0.0437,
        "per_hour": {
            10: {"mean": 155.13, "p75": 167.04, "p90": 173.52},
            11: {"mean": 161.44, "p75": 173.55, "p90": 180.38},
            12: {"mean": 164.86, "p75": 179.06, "p90": 184.44},
            13: {"mean": 159.05, "p75": 172.15, "p90": 177.76},
            14: {"mean": 159.59, "p75": 173.97, "p90": 178.37},
            15: {"mean": 171.33, "p75": 185.70, "p90": 192.64},
            16: {"mean": 182.37, "p75": 198.07, "p90": 205.29},
            17: {"mean": 192.30, "p75": 208.73, "p90": 214.82},
            18: {"mean": 203.90, "p75": 220.37, "p90": 228.62},
            19: {"mean": 215.84, "p75": 234.47, "p90": 240.82},
            20: {"mean": 205.33, "p75": 225.96, "p90": 240.95},
        }
    },
    "USID_29": {
        "absorption_fraction": 0.1429,
        "window_mean": 232.83, "window_p75": 261.85, "window_p90": 288.61,
        "window_vol_mean": 0.0568,
        "per_hour": {
            10: {"mean": 201.95, "p75": 218.60, "p90": 226.98},
            11: {"mean": 210.72, "p75": 229.38, "p90": 237.01},
            12: {"mean": 214.03, "p75": 231.75, "p90": 238.99},
            13: {"mean": 206.19, "p75": 224.41, "p90": 230.59},
            14: {"mean": 207.07, "p75": 223.51, "p90": 234.47},
            15: {"mean": 221.99, "p75": 240.55, "p90": 246.88},
            16: {"mean": 236.56, "p75": 255.64, "p90": 266.11},
            17: {"mean": 250.61, "p75": 271.86, "p90": 278.92},
            18: {"mean": 264.78, "p75": 287.99, "p90": 297.16},
            19: {"mean": 279.17, "p75": 303.12, "p90": 311.64},
            20: {"mean": 268.06, "p75": 295.06, "p90": 309.89},
        }
    },
    "USID_45": {
        "absorption_fraction": 0.1190,
        "window_mean": 174.85, "window_p75": 195.39, "window_p90": 217.10,
        "window_vol_mean": 0.0427,
        "per_hour": {
            10: {"mean": 151.04, "p75": 163.72, "p90": 170.13},
            11: {"mean": 158.45, "p75": 172.07, "p90": 177.82},
            12: {"mean": 160.28, "p75": 172.86, "p90": 179.58},
            13: {"mean": 155.10, "p75": 168.86, "p90": 174.08},
            14: {"mean": 156.01, "p75": 169.26, "p90": 173.87},
            15: {"mean": 167.16, "p75": 180.77, "p90": 188.02},
            16: {"mean": 176.79, "p75": 190.63, "p90": 198.47},
            17: {"mean": 188.59, "p75": 205.26, "p90": 212.63},
            18: {"mean": 198.81, "p75": 215.85, "p90": 222.48},
            19: {"mean": 210.66, "p75": 229.09, "p90": 234.96},
            20: {"mean": 200.49, "p75": 222.05, "p90": 229.96},
        }
    },
    "USID_10": {
        "absorption_fraction": 0.0952,
        "window_mean": 259.28, "window_p75": 290.73, "window_p90": 322.43,
        "window_vol_mean": 0.0633,
        "per_hour": {
            10: {"mean": 223.57, "p75": 241.43, "p90": 249.15},
            11: {"mean": 234.89, "p75": 254.48, "p90": 263.62},
            12: {"mean": 238.21, "p75": 257.68, "p90": 267.96},
            13: {"mean": 230.70, "p75": 250.60, "p90": 258.21},
            14: {"mean": 230.14, "p75": 248.44, "p90": 257.58},
            15: {"mean": 246.80, "p75": 268.03, "p90": 278.95},
            16: {"mean": 264.14, "p75": 285.89, "p90": 298.00},
            17: {"mean": 277.50, "p75": 302.64, "p90": 312.21},
            18: {"mean": 295.73, "p75": 320.59, "p90": 331.19},
            19: {"mean": 312.50, "p75": 338.33, "p90": 350.45},
            20: {"mean": 297.89, "p75": 329.65, "p90": 344.03},
        }
    },
}

base_case_mbps = aff["same_daytype_same_hour_mean_mbps"]  # 144.68
stress_case_mbps = aff["same_hour_60d_p90_mbps"]          # 171.89
lost_traffic_mbps = aff["same_hour_60d_mean_mbps"]         # 136.43
baseline_adjustment_factor = round(base_case_mbps / lost_traffic_mbps, 2)  # 1.06
lost_volume_gb = 0.0333
adjusted_lost_volume_gb = round(lost_volume_gb * baseline_adjustment_factor, 4)


def classify_4tier(new_total, p90):
    """Base skill 4-tier classifier."""
    if new_total <= p90 * 0.85:
        return "low"
    elif new_total <= p90:
        return "moderate"
    elif new_total <= p90 * 1.20:
        return "high"
    else:
        return "critical"


def classify_3tier(new_total, p90):
    """Sustained skill 3-tier classifier."""
    if new_total <= p90 * 0.85:
        return "stable"
    elif new_total <= p90:
        return "stressed"
    else:
        return "overloaded"


# ---- Build per_neighbor (base skill) ----
per_neighbor = {}
for nb, cfg in NB_CONFIG.items():
    af = cfg["absorption_fraction"]
    bl = cfg["window_mean"]
    p75 = cfg["window_p75"]
    p90 = cfg["window_p90"]
    extra_base = round(base_case_mbps * af, 2)
    extra_stress = round(stress_case_mbps * af, 2)
    extra_vol_base = round(lost_volume_gb * baseline_adjustment_factor * af, 4)
    new_base = round(bl + extra_base, 2)
    new_stress = round(bl + extra_stress, 2)
    pb = classify_4tier(new_base, p90)
    ps = classify_4tier(new_stress, p90)
    per_neighbor[nb] = {
        "absorption_fraction": af,
        "extra_throughput_mbps": extra_base,       # legacy = extra_base
        "extra_base_mbps": extra_base,
        "extra_stress_mbps": extra_stress,
        "extra_volume_gb": extra_vol_base,
        "neighbor_baseline_mbps": bl,
        "neighbor_p75_mbps": p75,
        "neighbor_p90_mbps": p90,
        "new_total_mbps": new_base,                 # legacy = new_total_base
        "new_total_base_mbps": new_base,
        "new_total_stress_mbps": new_stress,
        "capacity_pressure": pb,                    # legacy = pressure_base
        "pressure_base": pb,
        "pressure_stress": ps,
        "pressure_note": (
            f"base: new_total={new_base} Mbps vs p90={p90} Mbps (p90x0.85={round(p90*0.85,2)}, p90x1.20={round(p90*1.20,2)}) -> {pb}; "
            f"stress: new_total={new_stress} -> {ps}"
        ),
        "forecast_note": (
            f"base=weekday_same_hour_mean({base_case_mbps})*af({af})={extra_base}; "
            f"stress=60d_p90({stress_case_mbps})*af({af})={extra_stress}"
        )
    }

# Determine overload risk
TIERS = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
RTIERS = {v: k for k, v in TIERS.items()}

worst_base = max(TIERS[per_neighbor[nb]["pressure_base"]] for nb in per_neighbor)
worst_stress = max(TIERS[per_neighbor[nb]["pressure_stress"]] for nb in per_neighbor)
overload_risk_base = RTIERS[worst_base]
overload_risk_stress = RTIERS[worst_stress]

# Primary absorber is USID_01, stress = critical -> final = critical
if worst_base >= TIERS["high"] and worst_stress >= TIERS["critical"]:
    overload_risk = "critical"
elif worst_base >= TIERS["high"]:
    overload_risk = "high"
elif worst_base >= TIERS["moderate"] and worst_stress >= TIERS["critical"]:
    overload_risk = "high"
else:
    overload_risk = RTIERS[worst_base]

# ---- Build hourly_lost_traffic_candidates ----
hourly_lost_candidates = {}
for h in OUTAGE_HOURS:
    c = hourly_cands[h]
    hk = f"{h:02d}:00"
    hourly_lost_candidates[hk] = {
        "same_hour_mean_mbps": c["mean"],
        "same_hour_p75_mbps": c["p75"],
        "same_hour_p90_mbps": c["p90"],
        "same_daytype_hour_mean_mbps": c["wday"],
        "recent_14d_hour_mean_mbps": c["d14"],
        "candidate_notes": [] if h not in PEAK_HOURS else ["peak hour: weekday mean preferred as base"]
    }

# ---- Build hourly_lost_traffic_forecast ----
hourly_lost_forecast_out = {}
for h in OUTAGE_HOURS:
    hk = f"{h:02d}:00"
    hourly_lost_forecast_out[hk] = hourly_lost_forecast[hk]

# ---- Build hourly_neighbor_forecast ----
def build_hourly_nb_forecast():
    result = {}
    for nb, cfg in NB_CONFIG.items():
        af = cfg["absorption_fraction"]
        result[nb] = {}
        for h in OUTAGE_HOURS:
            hk = f"{h:02d}:00"
            hf = hourly_lost_forecast[hk]
            base_lost = hf["base_case_mbps"]
            stress_lost = hf["stress_case_mbps"]
            ph = cfg["per_hour"][h]
            nb_bl = ph["mean"]
            nb_p75 = ph["p75"]
            nb_p90 = ph["p90"]
            # estimate volume proportional to throughput
            nb_vol_bl = round(cfg["window_vol_mean"] * nb_bl / cfg["window_mean"], 4)
            extra_base_h = round(base_lost * af, 2)
            extra_stress_h = round(stress_lost * af, 2)
            new_base_h = round(nb_bl + extra_base_h, 2)
            new_stress_h = round(nb_bl + extra_stress_h, 2)
            cls_base = classify_3tier(new_base_h, nb_p90)
            cls_stress = classify_3tier(new_stress_h, nb_p90)
            result[nb][hk] = {
                "neighbor_hour_baseline_mbps": nb_bl,
                "neighbor_hour_p75_mbps": nb_p75,
                "neighbor_hour_p90_mbps": nb_p90,
                "neighbor_hour_baseline_vol_gb": nb_vol_bl,
                "extra_base_h_mbps": extra_base_h,
                "extra_stress_h_mbps": extra_stress_h,
                "new_total_base_H_mbps": new_base_h,
                "new_total_stress_H_mbps": new_stress_h,
                "classification_base": cls_base,
                "classification_stress": cls_stress
            }
    return result

hourly_nb_forecast = build_hourly_nb_forecast()

# ---- Hourly distribution ----
TIERS3 = {"stable": 0, "stressed": 1, "overloaded": 2}
base_counts = {"stable": 0, "stressed": 0, "overloaded": 0}
stress_counts = {"stable": 0, "stressed": 0, "overloaded": 0}

for h in OUTAGE_HOURS:
    hk = f"{h:02d}:00"
    # Find worst across neighbors for this hour
    worst_base_h = max(TIERS3[hourly_nb_forecast[nb][hk]["classification_base"]] for nb in hourly_nb_forecast)
    worst_stress_h = max(TIERS3[hourly_nb_forecast[nb][hk]["classification_stress"]] for nb in hourly_nb_forecast)
    worst_base_cls = [k for k,v in TIERS3.items() if v == worst_base_h][0]
    worst_stress_cls = [k for k,v in TIERS3.items() if v == worst_stress_h][0]
    base_counts[worst_base_cls] += 1
    stress_counts[worst_stress_cls] += 1

# ---- Sustained reasoning log ----
sustained_reasoning_log = []
for h in OUTAGE_HOURS:
    hk = f"{h:02d}:00"
    hf = hourly_lost_forecast[hk]
    # Worst neighbor this hour
    worst_nb_h = max(hourly_nb_forecast.keys(), key=lambda nb: hourly_nb_forecast[nb][hk]["new_total_base_H_mbps"])
    nb_h = hourly_nb_forecast[worst_nb_h][hk]
    hour_type = "peak" if h in PEAK_HOURS else "off-peak"
    sustained_reasoning_log.append({
        "hour": hk,
        "hour_type": hour_type,
        "lost_traffic_base_mbps": hf["base_case_mbps"],
        "lost_traffic_stress_mbps": hf["stress_case_mbps"],
        "lost_traffic_base_source": hf["base_case_source"],
        "worst_neighbor": worst_nb_h,
        "worst_neighbor_hour_baseline_mbps": nb_h["neighbor_hour_baseline_mbps"],
        "worst_neighbor_hour_p90_mbps": nb_h["neighbor_hour_p90_mbps"],
        "worst_neighbor_new_total_base_mbps": nb_h["new_total_base_H_mbps"],
        "worst_neighbor_new_total_stress_mbps": nb_h["new_total_stress_H_mbps"],
        "worst_neighbor_classification_base": nb_h["classification_base"],
        "worst_neighbor_classification_stress": nb_h["classification_stress"],
        "worst_neighbor_baseline_vol_gb": nb_h["neighbor_hour_baseline_vol_gb"],
        "worst_neighbor_new_total_base_vol_gb": round(nb_h["neighbor_hour_baseline_vol_gb"] * nb_h["new_total_base_H_mbps"] / nb_h["neighbor_hour_baseline_mbps"], 4)
    })

# ---- Peak derivation ----
peak_base_cls = {}
peak_stress_cls = {}
for h in PEAK_HOURS:
    hk = f"{h:02d}:00"
    worst_b = max(TIERS3[hourly_nb_forecast[nb][hk]["classification_base"]] for nb in hourly_nb_forecast)
    worst_s = max(TIERS3[hourly_nb_forecast[nb][hk]["classification_stress"]] for nb in hourly_nb_forecast)
    peak_base_cls[hk] = [k for k,v in TIERS3.items() if v == worst_b][0]
    peak_stress_cls[hk] = [k for k,v in TIERS3.items() if v == worst_s][0]

# Peak verdict: base overloaded in any material hour -> critical
if any(v == "overloaded" for v in peak_base_cls.values()):
    peak_hour_verdict = "critical"
elif any(v == "overloaded" for v in peak_stress_cls.values()):
    peak_hour_verdict = "elevated_risk"
else:
    peak_hour_verdict = "manageable"

# ---- Sustained pressure verdict ----
if base_counts["overloaded"] > 5:
    sustained_pressure_verdict = "unsustainable"
    sustained_pressure_reason = f"Base case shows {base_counts['overloaded']}/11 hours overloaded; stress shows {stress_counts['overloaded']}/11 overloaded. Primary absorber USID_01 drives overload throughout the window."
elif base_counts["stressed"] + base_counts["overloaded"] > 6:
    sustained_pressure_verdict = "degrading"
    sustained_pressure_reason = "Majority of hours show stressed or overloaded conditions."
else:
    sustained_pressure_verdict = "sustainable"
    sustained_pressure_reason = "Neighbor capacity holds under base-case displaced traffic."

# ---- Reasoning log (base skill) ----
reasoning_log = [
    {
        "step": "Step A - Forecast Framing",
        "data_used": "Partial outage: USID_09 S0 and S2 failed, S1 active. Outage window 10:00-20:00 UTC (11 hours). Peak overlap=true; peak_hours=[17,18,19,20]. Day_type=weekday. Area_profile=unknown (dominant_landuse=unknown, source=openstreetmap). Neighbors: USID_01, USID_25, USID_43, USID_29, USID_45, USID_10.",
        "assumption": null,
        "result": "Forecast type: counterfactual_neighbor_load. Scenario: partial_outage_weekday_peak_overlap_sustained. Actual neighbor outage-window KPI is not used as ground truth."
    },
    {
        "step": "Step B - Lost Traffic Candidates",
        "data_used": "get_kpi_history(USID_09) filtered to sectors S0, S2 and hours 10-20 (2640 records). 60d mean=136.43 Mbps, p75=154.60, p90=171.89, p10=104.01; weekday same-hour mean=144.68; recent 14d mean=132.28; peak-hour mean (H17-20)=155.71.",
        "assumption": "Aggregate across S0+S2 per 15-min timestamp. S1 remains active and is excluded.",
        "result": "Candidate set built. Weekday mean (144.68) is 6% above 60d mean (136.43), confirming weekday uplift. Recent 14d (132.28) is below 60d mean, suggesting no recent surge."
    },
    {
        "step": "Step C - Base and Stress Selection",
        "data_used": "Peak overlap=true; weekday context. Candidates: 60d mean=136.43, weekday mean=144.68, 60d p90=171.89. Selected base: same_daytype_same_hour_mean_mbps=144.68. Selected stress: same_hour_60d_p90_mbps=171.89.",
        "assumption": "Weekday mean is preferred over 60d mean for peak-overlap weekday outage; captures day-of-week traffic pattern.",
        "result": "base_case_mbps=144.68, stress_case_mbps=171.89, adjustment=+6% vs raw 60d mean. A fixed factor alone is insufficient: the 11-hour window spans a 37% throughput swing (H10 mean 119.53 vs H19 mean 163.36 Mbps); applying one static multiplier would underestimate peak hours and overestimate off-peak hours."
    },
    {
        "step": "Step D - Neighbor Counterfactual Load",
        "data_used": "absorption_fractions from preprocessing_stats per_backup: USID_01=0.5714, USID_25=0.50, USID_43=0.4286, USID_29=0.1429, USID_45=0.1190, USID_10=0.0952. Neighbor baselines (60d outage-window aggregate): USID_01=188.14, USID_25=169.28, USID_43=179.19, USID_29=232.83, USID_45=174.85, USID_10=259.28 Mbps.",
        "assumption": "absorption_fraction is a coverage-pixel spatial proxy for traffic redistribution, not a direct traffic measurement. Post-outage traffic split follows pre-outage backup coverage distribution.",
        "result": "USID_01: base=270.84 Mbps > p90=232.63 -> high; stress=286.37 > p90*1.20=279.16 -> critical. USID_25: base=241.62 > p90=210.33 -> high; stress=255.23 > p90*1.20=252.40 -> critical. USID_43: base=241.21 > p90=222.82 -> high; stress=252.87 < p90*1.20=267.38 -> high. USID_29/45/10: moderate or low under base."
    },
    {
        "step": "Step E - KPI Risk",
        "data_used": "Worst pressure_base: high (USID_01, 25, 43). Worst pressure_stress: critical (USID_01, 25). Primary absorber from preprocessing_stats: USID_01.",
        "assumption": null,
        "result": "overload_risk_base=high, overload_risk_stress=critical. Rule: base=high + stress=critical + primary absorber critical -> overload_risk=critical."
    },
    {
        "step": "Step F - Forecast Uncertainty",
        "data_used": "area_profile dominant_landuse=unknown. absorption_fraction=spatial proxy. base/stress diverge by 1-2 tiers for USID_01 and USID_25. Weekday candidates well-supported (n=1936 window-level records).",
        "assumption": "Spatial proxy is the only available redistribution mechanism.",
        "result": "forecast_uncertainty.level=medium. Drivers: area_profile_unknown, absorption_as_spatial_proxy, base/stress tier divergence for primary absorbers. Guardrails: all values anchored to historical distributions from get_kpi_history filtered to outage_window_hours."
    }
]

# ---- Full artifact ----
artifact = {
    "run_id": "TKT-2026-04-17-0002_20260507T091321Z",
    "ticket_id": "TKT-2026-04-17-0002",
    "affected_usid": "USID_09",
    "affected_sectors": ["USID_09_S0", "USID_09_S2"],
    "outage_window_hours": OUTAGE_HOURS,
    "duration_hours": 10.46,

    # ---- Forecast framing ----
    "forecast_framing": {
        "forecast_type": "counterfactual_neighbor_load",
        "scenario": "partial_outage_weekday_peak_overlap_sustained",
        "forecast_horizon_hours": OUTAGE_HOURS,
        "contamination_policy": "do_not_use_actual_neighbor_outage_window_kpi",
        "reason": "Forecast estimates what load neighbors would face if failed sectors' traffic redistributes; actual neighbor measurements during outage window are not used as the answer."
    },

    # ---- Lost traffic candidates ----
    "lost_traffic_candidates": {
        "same_hour_60d_mean_mbps": aff["same_hour_60d_mean_mbps"],
        "same_hour_60d_p75_mbps": aff["same_hour_60d_p75_mbps"],
        "same_hour_60d_p90_mbps": aff["same_hour_60d_p90_mbps"],
        "same_daytype_same_hour_mean_mbps": aff["same_daytype_same_hour_mean_mbps"],
        "recent_14d_same_hour_mean_mbps": aff["recent_14d_same_hour_mean_mbps"],
        "peak_hour_mean_mbps": aff["peak_hour_mean_mbps"],
        "candidate_notes": [
            "60d stats from get_kpi_history(USID_09) filtered to S0+S2 sectors, hours 10-20",
            "weekday same-hour mean uses weekday filter on same record set (n=1936 timestamps)",
            "recent 14d covers 2026-04-03 to 2026-04-16",
            "peak-hour mean filtered to hours 17-20 only (n=960 timestamps)"
        ]
    },

    # ---- Lost traffic forecast ----
    "lost_traffic_forecast": {
        "base_case_mbps": base_case_mbps,
        "stress_case_mbps": stress_case_mbps,
        "selected_base_source": "same_daytype_same_hour_mean_mbps",
        "selected_stress_source": "same_hour_60d_p90_mbps",
        "directional_adjustment": "upward",
        "reason": "Peak overlap=true on a weekday. Weekday same-hour mean (144.68) is +6% above 60d mean (136.43), capturing the weekday traffic uplift. This is the most appropriate analog because the outage falls on a Friday with peak overlap at 17:00-20:00.",
        "why_not_fixed_factor_only": "The 11-hour window spans a 37% intra-day swing (H10 mean=119.53 Mbps vs H19 mean=163.36 Mbps). A single multiplicative factor applied to the 60d window average would underestimate peak-hour displaced traffic and overestimate off-peak hours. Hourly forecasts use separate base/stress anchors per hour to capture this variation.",
        "candidate_summary": {
            "60d_mean": 136.43,
            "60d_p75": 154.60,
            "60d_p90": 171.89,
            "weekday_mean": 144.68,
            "recent_14d_mean": 132.28,
            "peak_hour_mean": 155.71
        }
    },

    # ---- Legacy base fields ----
    "lost_traffic_mbps": lost_traffic_mbps,
    "adjusted_lost_traffic_mbps": base_case_mbps,
    "lost_volume_gb": lost_volume_gb,
    "adjusted_lost_volume_gb": adjusted_lost_volume_gb,
    "loss_ratio": 0.68,
    "baseline_mbps": 199.43,
    "baseline_adjustment_factor": baseline_adjustment_factor,
    "time_background_applied": True,

    # ---- Per-neighbor ----
    "per_neighbor": per_neighbor,

    # ---- KPI risk ----
    "overload_risk": overload_risk,
    "overload_risk_base": overload_risk_base,
    "overload_risk_stress": overload_risk_stress,
    "overload_risk_note": (
        "USID_01 (af=0.5714) base=high, stress=critical. "
        "USID_25 (af=0.50) base=high, stress=critical. "
        "USID_43 (af=0.4286) base=high, stress=high. "
        "USID_29/45 moderate both cases; USID_10 low base/moderate stress. "
        "Primary absorber USID_01 at critical stress triggers critical final risk."
    ),

    # ---- Forecast uncertainty ----
    "forecast_uncertainty": {
        "level": "medium",
        "drivers": [
            "area_profile_unknown: dominant_landuse=unknown; cannot apply land-use-specific demand uplift",
            "absorption_fraction_is_spatial_proxy: pixel-based coverage redistribution, not traffic-proportional redistribution",
            "base_stress_divergence: USID_01 and USID_25 differ by two pressure tiers (high vs critical) between base and stress"
        ],
        "guardrails": [
            "All selected base and stress forecast values are anchored to historical distributions from get_kpi_history filtered to outage_window_hours (10-20)",
            "base_case_mbps=144.68 is within the historical p10-p90 range [104.01, 171.89]",
            "stress_case_mbps=171.89 equals the historical p90 and does not exceed observed range",
            "No absorption fraction was estimated; all come from preprocessing_stats per_backup"
        ]
    },

    # ---- Legacy uncertainty ----
    "uncertainty": {
        "level": "medium",
        "reasons": [
            "area_profile unknown: cannot apply land-use demand calibration",
            "absorption_fraction is a spatial-coverage proxy for traffic redistribution",
            "base and stress cases diverge by up to 2 tiers for USID_01 and USID_25"
        ]
    },

    # ---- Reasoning log ----
    "reasoning_log": reasoning_log,

    # ============================================================
    # SUSTAINED PRESSURE EXTENSION (kpi_sustained_pressure skill)
    # ============================================================
    "sustained_pressure_verdict": sustained_pressure_verdict,
    "sustained_pressure_reason": sustained_pressure_reason,

    "hourly_lost_traffic_candidates": hourly_lost_candidates,
    "hourly_lost_traffic_forecast": hourly_lost_forecast_out,
    "hourly_neighbor_forecast": hourly_nb_forecast,

    "hourly_distribution": {
        "base": {
            "stable_hours": base_counts["stable"],
            "stressed_hours": base_counts["stressed"],
            "overloaded_hours": base_counts["overloaded"]
        },
        "stress": {
            "stable_hours": stress_counts["stable"],
            "stressed_hours": stress_counts["stressed"],
            "overloaded_hours": stress_counts["overloaded"]
        }
    },
    "hourly_distribution_legacy": {
        "stable_hours": base_counts["stable"],
        "stressed_hours": base_counts["stressed"],
        "overloaded_hours": base_counts["overloaded"]
    },

    "trend": "worsening",
    "trend_detail": {
        "label": "worsening_then_persistent",
        "reason": (
            "USID_01 (primary absorber) is overloaded throughout all 11 hours. "
            "Absolute load escalates from 230.61 Mbps (H10) to 325.63 Mbps (H19) in the base case, "
            "a 41% increase within the window. Pressure worsens materially entering peak hours "
            "(H17: +63 Mbps vs H16 neighbor load) and remains elevated through H20 (310.50 Mbps)."
        )
    },

    "peak_hour_verdict": peak_hour_verdict,
    "peak_derivation": {
        "peak_hours": [f"{h:02d}:00" for h in PEAK_HOURS],
        "base_case_peak_classifications": {k: peak_base_cls[k] for k in sorted(peak_base_cls)},
        "stress_case_peak_classifications": {k: peak_stress_cls[k] for k in sorted(peak_stress_cls)},
        "derived_peak_hour_verdict": peak_hour_verdict,
        "peak_verdict_rule": "Base overloaded in all 4 peak hours (worst neighbor USID_01) -> critical"
    },

    "sustained_reasoning_log": sustained_reasoning_log
}

# ---- Write artifact ----
out_dir = "artifacts/TKT-2026-04-17-0002_20260507T091321Z"
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "kpi_agent_artifact.json")
with open(out_path, "w") as f:
    json.dump(artifact, f, indent=2)

print(f"Wrote artifact to {out_path}")
print(f"overload_risk={overload_risk}")
print(f"overload_risk_base={overload_risk_base}, overload_risk_stress={overload_risk_stress}")
print(f"peak_hour_verdict={peak_hour_verdict}")
print(f"sustained_pressure_verdict={sustained_pressure_verdict}")
print(f"base_dist={base_counts}, stress_dist={stress_counts}")
print(f"trend=worsening_then_persistent")
