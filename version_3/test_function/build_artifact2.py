"""Build kpi_agent_artifact.json - clean version with no null issues."""
import json, os

OUTAGE_HOURS = list(range(10, 21))
PEAK_HOURS = [17, 18, 19, 20]

# ---- Affected USID_09 S0+S2 stats (from get_kpi_history filtered) ----
AFF_60D_MEAN  = 136.43
AFF_60D_P75   = 154.60
AFF_60D_P90   = 171.89
AFF_60D_P10   = 104.01
AFF_WDAY_MEAN = 144.68   # weekday same-hour mean
AFF_14D_MEAN  = 132.28
AFF_PEAK_MEAN = 155.71   # peak hours 17-20 only

# Window-level selection (base skill Step C)
BASE_CASE_MBPS   = 144.68  # same_daytype_same_hour_mean (weekday)
STRESS_CASE_MBPS = 171.89  # same_hour_60d_p90
LOST_TRAFFIC_MBPS = AFF_60D_MEAN
BAF = round(BASE_CASE_MBPS / LOST_TRAFFIC_MBPS, 2)  # 1.06
LOST_VOL_GB = 0.0333
ADJ_VOL_GB  = round(LOST_VOL_GB * BAF, 4)

# ---- Hourly lost traffic candidates (S0+S2 aggregate) ----
HOURLY_CANDS = {
    10: {"mean": 119.53, "p75": 130.68, "p90": 136.73, "wday": 127.38, "d14": 118.78},
    11: {"mean": 123.04, "p75": 135.57, "p90": 139.41, "wday": 130.26, "d14": 119.53},
    12: {"mean": 125.72, "p75": 139.52, "p90": 145.38, "wday": 133.52, "d14": 121.79},
    13: {"mean": 120.56, "p75": 134.71, "p90": 139.53, "wday": 128.23, "d14": 116.92},
    14: {"mean": 121.58, "p75": 134.09, "p90": 140.04, "wday": 128.60, "d14": 117.12},
    15: {"mean": 129.14, "p75": 142.69, "p90": 148.16, "wday": 136.80, "d14": 124.56},
    16: {"mean": 138.27, "p75": 152.47, "p90": 159.79, "wday": 146.45, "d14": 134.07},
    17: {"mean": 147.59, "p75": 162.77, "p90": 170.29, "wday": 156.47, "d14": 143.57},
    18: {"mean": 155.17, "p75": 170.45, "p90": 178.59, "wday": 164.20, "d14": 150.70},
    19: {"mean": 163.36, "p75": 179.83, "p90": 188.79, "wday": 173.38, "d14": 155.46},
    20: {"mean": 156.72, "p75": 174.71, "p90": 181.82, "wday": 166.13, "d14": 152.56},
}

# ---- Neighbor config (absorption fractions from preprocessing_stats) ----
NB = {
    "USID_01": {
        "af": 0.5714, "wm": 188.14, "wp75": 212.12, "wp90": 232.63, "wvol": 0.0459,
        "ph": {
            10: (162.31, 176.02, 181.47), 11: (169.24, 184.20, 189.48),
            12: (172.68, 187.25, 194.03), 13: (166.92, 180.21, 186.82),
            14: (168.10, 183.96, 190.30), 15: (179.98, 194.20, 203.66),
            16: (190.38, 206.31, 214.54), 17: (204.14, 221.96, 229.58),
            18: (213.72, 230.93, 239.90), 19: (226.54, 245.65, 254.66),
            20: (215.55, 236.97, 251.87),
        }
    },
    "USID_25": {
        "af": 0.5000, "wm": 169.28, "wp75": 189.62, "wp90": 210.33, "wvol": 0.0413,
        "ph": {
            10: (146.40, 158.51, 165.29), 11: (152.69, 164.67, 172.01),
            12: (155.39, 167.62, 174.77), 13: (150.48, 162.59, 170.95),
            14: (151.10, 163.92, 170.27), 15: (161.29, 175.69, 180.38),
            16: (172.26, 187.70, 193.70), 17: (182.55, 198.81, 204.69),
            18: (192.35, 209.11, 216.41), 19: (203.74, 221.27, 228.28),
            20: (193.82, 212.23, 224.07),
        }
    },
    "USID_43": {
        "af": 0.4286, "wm": 179.19, "wp75": 200.98, "wp90": 222.82, "wvol": 0.0437,
        "ph": {
            10: (155.13, 167.04, 173.52), 11: (161.44, 173.55, 180.38),
            12: (164.86, 179.06, 184.44), 13: (159.05, 172.15, 177.76),
            14: (159.59, 173.97, 178.37), 15: (171.33, 185.70, 192.64),
            16: (182.37, 198.07, 205.29), 17: (192.30, 208.73, 214.82),
            18: (203.90, 220.37, 228.62), 19: (215.84, 234.47, 240.82),
            20: (205.33, 225.96, 240.95),
        }
    },
    "USID_29": {
        "af": 0.1429, "wm": 232.83, "wp75": 261.85, "wp90": 288.61, "wvol": 0.0568,
        "ph": {
            10: (201.95, 218.60, 226.98), 11: (210.72, 229.38, 237.01),
            12: (214.03, 231.75, 238.99), 13: (206.19, 224.41, 230.59),
            14: (207.07, 223.51, 234.47), 15: (221.99, 240.55, 246.88),
            16: (236.56, 255.64, 266.11), 17: (250.61, 271.86, 278.92),
            18: (264.78, 287.99, 297.16), 19: (279.17, 303.12, 311.64),
            20: (268.06, 295.06, 309.89),
        }
    },
    "USID_45": {
        "af": 0.1190, "wm": 174.85, "wp75": 195.39, "wp90": 217.10, "wvol": 0.0427,
        "ph": {
            10: (151.04, 163.72, 170.13), 11: (158.45, 172.07, 177.82),
            12: (160.28, 172.86, 179.58), 13: (155.10, 168.86, 174.08),
            14: (156.01, 169.26, 173.87), 15: (167.16, 180.77, 188.02),
            16: (176.79, 190.63, 198.47), 17: (188.59, 205.26, 212.63),
            18: (198.81, 215.85, 222.48), 19: (210.66, 229.09, 234.96),
            20: (200.49, 222.05, 229.96),
        }
    },
    "USID_10": {
        "af": 0.0952, "wm": 259.28, "wp75": 290.73, "wp90": 322.43, "wvol": 0.0633,
        "ph": {
            10: (223.57, 241.43, 249.15), 11: (234.89, 254.48, 263.62),
            12: (238.21, 257.68, 267.96), 13: (230.70, 250.60, 258.21),
            14: (230.14, 248.44, 257.58), 15: (246.80, 268.03, 278.95),
            16: (264.14, 285.89, 298.00), 17: (277.50, 302.64, 312.21),
            18: (295.73, 320.59, 331.19), 19: (312.50, 338.33, 350.45),
            20: (297.89, 329.65, 344.03),
        }
    },
}


def cls4(v, p90):
    if v <= p90 * 0.85: return "low"
    elif v <= p90: return "moderate"
    elif v <= p90 * 1.20: return "high"
    else: return "critical"


def cls3(v, p90):
    if v <= p90 * 0.85: return "stable"
    elif v <= p90: return "stressed"
    else: return "overloaded"


TIER4 = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
TIER3 = {"stable": 0, "stressed": 1, "overloaded": 2}
RT4 = {v: k for k, v in TIER4.items()}

# ---- Window-level hourly lost traffic forecasts ----
def hfc(h):
    c = HOURLY_CANDS[h]
    if h in PEAK_HOURS:
        return {"base_case_source": "same_daytype_hour_mean_mbps",
                "base_case_mbps": c["wday"],
                "stress_case_source": "same_hour_60d_p90_mbps",
                "stress_case_mbps": c["p90"],
                "selection_reason": "Peak hour: weekday same-hour mean as base (day-type context), 60d p90 as stress.",
                "uncertainty": "medium"}
    else:
        return {"base_case_source": "same_hour_60d_mean_mbps",
                "base_case_mbps": c["mean"],
                "stress_case_source": "same_hour_60d_p75_mbps",
                "stress_case_mbps": c["p75"],
                "selection_reason": "Off-peak weekday: 60d same-hour mean is the most stable anchor; p75 as stress.",
                "uncertainty": "low"}


hourly_lost_forecast = {f"{h:02d}:00": hfc(h) for h in OUTAGE_HOURS}

# ---- Per-neighbor base (window-level) ----
per_neighbor = {}
for nb, cfg in NB.items():
    af, bl, p75, p90 = cfg["af"], cfg["wm"], cfg["wp75"], cfg["wp90"]
    eb = round(BASE_CASE_MBPS * af, 2)
    es = round(STRESS_CASE_MBPS * af, 2)
    ev = round(ADJ_VOL_GB * af, 4)
    ntb = round(bl + eb, 2)
    nts = round(bl + es, 2)
    pb = cls4(ntb, p90)
    ps = cls4(nts, p90)
    per_neighbor[nb] = {
        "absorption_fraction": af,
        "extra_throughput_mbps": eb,
        "extra_base_mbps": eb,
        "extra_stress_mbps": es,
        "extra_volume_gb": ev,
        "neighbor_baseline_mbps": bl,
        "neighbor_p75_mbps": p75,
        "neighbor_p90_mbps": p90,
        "new_total_mbps": ntb,
        "new_total_base_mbps": ntb,
        "new_total_stress_mbps": nts,
        "capacity_pressure": pb,
        "pressure_base": pb,
        "pressure_stress": ps,
        "pressure_note": (f"base: {ntb} vs p90={p90} (p90x0.85={round(p90*0.85,2)}, p90x1.20={round(p90*1.20,2)}) -> {pb}; stress: {nts} -> {ps}"),
        "forecast_note": (f"base={BASE_CASE_MBPS}*{af}={eb}; stress={STRESS_CASE_MBPS}*{af}={es}")
    }

worst_b = max(TIER4[per_neighbor[nb]["pressure_base"]] for nb in per_neighbor)
worst_s = max(TIER4[per_neighbor[nb]["pressure_stress"]] for nb in per_neighbor)
orb = RT4[worst_b]
ors = RT4[worst_s]
# primary absorber USID_01 at critical stress -> critical
overload_risk = "critical" if worst_b >= TIER4["high"] and worst_s >= TIER4["critical"] else RT4[worst_b]

# ---- Hourly neighbor forecast ----
hourly_nb = {}
for nb, cfg in NB.items():
    af, wm, wvol = cfg["af"], cfg["wm"], cfg["wvol"]
    hourly_nb[nb] = {}
    for h in OUTAGE_HOURS:
        hk = f"{h:02d}:00"
        m, p75, p90 = cfg["ph"][h]
        hf = hourly_lost_forecast[hk]
        bl_h = hf["base_case_mbps"]
        sl_h = hf["stress_case_mbps"]
        vol_h = round(wvol * m / wm, 4)
        eb_h = round(bl_h * af, 2)
        es_h = round(sl_h * af, 2)
        ntb_h = round(m + eb_h, 2)
        nts_h = round(m + es_h, 2)
        hourly_nb[nb][hk] = {
            "neighbor_hour_baseline_mbps": m,
            "neighbor_hour_p75_mbps": p75,
            "neighbor_hour_p90_mbps": p90,
            "neighbor_hour_baseline_vol_gb": vol_h,
            "extra_base_h_mbps": eb_h,
            "extra_stress_h_mbps": es_h,
            "new_total_base_H_mbps": ntb_h,
            "new_total_stress_H_mbps": nts_h,
            "classification_base": cls3(ntb_h, p90),
            "classification_stress": cls3(nts_h, p90)
        }

# ---- Hourly distribution (worst across neighbors each hour) ----
bc = {"stable": 0, "stressed": 0, "overloaded": 0}
sc = {"stable": 0, "stressed": 0, "overloaded": 0}
for h in OUTAGE_HOURS:
    hk = f"{h:02d}:00"
    wb = max(TIER3[hourly_nb[nb][hk]["classification_base"]] for nb in hourly_nb)
    ws = max(TIER3[hourly_nb[nb][hk]["classification_stress"]] for nb in hourly_nb)
    bcls = [k for k, v in TIER3.items() if v == wb][0]
    scls = [k for k, v in TIER3.items() if v == ws][0]
    bc[bcls] += 1
    sc[scls] += 1

# ---- Sustained verdict ----
if bc["overloaded"] > 5:
    spv = "unsustainable"
    spr = f"Base case: {bc['overloaded']}/11 hours overloaded; stress case: {sc['overloaded']}/11 hours overloaded. USID_01 (af=0.5714) drives overload at every hour from H10 through H20."
else:
    spv = "degrading"
    spr = "Majority of hours show stressed or overloaded conditions."

# ---- Peak derivation ----
pkb, pks = {}, {}
for h in PEAK_HOURS:
    hk = f"{h:02d}:00"
    wb = max(TIER3[hourly_nb[nb][hk]["classification_base"]] for nb in hourly_nb)
    ws = max(TIER3[hourly_nb[nb][hk]["classification_stress"]] for nb in hourly_nb)
    pkb[hk] = [k for k, v in TIER3.items() if v == wb][0]
    pks[hk] = [k for k, v in TIER3.items() if v == ws][0]

phv = "critical" if any(v == "overloaded" for v in pkb.values()) else "elevated_risk"

# ---- Sustained reasoning log ----
srl = []
for h in OUTAGE_HOURS:
    hk = f"{h:02d}:00"
    hf = hourly_lost_forecast[hk]
    # worst neighbor by base total
    wnb = max(hourly_nb.keys(), key=lambda nb: hourly_nb[nb][hk]["new_total_base_H_mbps"])
    nh = hourly_nb[wnb][hk]
    vol_new = round(nh["neighbor_hour_baseline_vol_gb"] * nh["new_total_base_H_mbps"] / nh["neighbor_hour_baseline_mbps"], 4) if nh["neighbor_hour_baseline_mbps"] > 0 else 0.0
    srl.append({
        "hour": hk,
        "hour_type": "peak" if h in PEAK_HOURS else "off-peak",
        "lost_traffic_base_mbps": hf["base_case_mbps"],
        "lost_traffic_stress_mbps": hf["stress_case_mbps"],
        "lost_traffic_base_source": hf["base_case_source"],
        "worst_neighbor": wnb,
        "worst_neighbor_hour_baseline_mbps": nh["neighbor_hour_baseline_mbps"],
        "worst_neighbor_hour_p90_mbps": nh["neighbor_hour_p90_mbps"],
        "worst_neighbor_new_total_base_mbps": nh["new_total_base_H_mbps"],
        "worst_neighbor_new_total_stress_mbps": nh["new_total_stress_H_mbps"],
        "worst_neighbor_classification_base": nh["classification_base"],
        "worst_neighbor_classification_stress": nh["classification_stress"],
        "worst_neighbor_baseline_vol_gb": nh["neighbor_hour_baseline_vol_gb"],
        "worst_neighbor_new_total_base_vol_gb": vol_new
    })

# ---- Reasoning log ----
rl = [
    {
        "step": "Step A - Forecast Framing",
        "data_used": "Partial outage USID_09: S0 and S2 failed, S1 active. Window 10:00-20:00 UTC (11h). peak_overlap=true; peak_hours=[17,18,19,20]. day_type=weekday. area_profile dominant_landuse=unknown. Neighbors: USID_01, USID_25, USID_43, USID_29, USID_45, USID_10.",
        "assumption": "no proxy needed at this step",
        "result": "Scenario: partial_outage_weekday_peak_overlap_sustained. Contamination policy: do not use actual neighbor outage-window KPI as ground truth."
    },
    {
        "step": "Step B - Lost Traffic Candidates",
        "data_used": "get_kpi_history(USID_09) sectors=[S0,S2] hours=[10-20] n=2640 timestamps. 60d mean=136.43, p75=154.60, p90=171.89, p10=104.01; weekday mean=144.68 (n=1936); recent 14d mean=132.28 (n=924); peak-hour mean=155.71 (h17-20 only, n=960).",
        "assumption": "Aggregate S0+S2 throughput per 15-min timestamp. S1 excluded (still active).",
        "result": "Weekday mean 144.68 is +6% above 60d mean 136.43, confirming weekday uplift. Recent 14d mean 132.28 is below 60d mean, indicating no recent demand surge."
    },
    {
        "step": "Step C - Base and Stress Selection",
        "data_used": "peak_overlap=true, day_type=weekday. Candidates: 60d_mean=136.43, weekday_mean=144.68, 60d_p90=171.89. Selected base=weekday_mean=144.68; selected stress=60d_p90=171.89.",
        "assumption": "Weekday same-hour mean captures day-of-week traffic pattern better than all-days 60d mean for a peak-overlap weekday scenario.",
        "result": "base_case=144.68, stress_case=171.89, BAF=1.06 vs 60d mean. Both values are within historical p10-p90 range [104.01, 171.89]. Fixed factor alone is insufficient: per-hour swing of 37% (H10 mean 119.53 vs H19 mean 163.36 Mbps) means a single multiplier misallocates burden across the 11-hour window."
    },
    {
        "step": "Step D - Neighbor Counterfactual Load",
        "data_used": "absorption_fractions from preprocessing_stats per_backup: USID_01=0.5714 (24px), USID_25=0.50 (21px), USID_43=0.4286 (18px), USID_29=0.1429 (6px), USID_45=0.1190 (5px), USID_10=0.0952 (4px). Neighbor 60d aggregate means/p90: USID_01 188.14/232.63; USID_25 169.28/210.33; USID_43 179.19/222.82; USID_29 232.83/288.61; USID_45 174.85/217.10; USID_10 259.28/322.43.",
        "assumption": "absorption_fraction is a coverage-pixel spatial proxy. Each pixel's displaced traffic redistributes to the strongest available backup cell.",
        "result": "USID_01: extra_base=82.70, new_total_base=270.84>p90=232.63->high; extra_stress=98.24, new_total_stress=286.37>p90x1.20=279.16->critical. USID_25: 241.62->high, 255.23->critical. USID_43: 241.21->high, 252.87->high. USID_29: 253.50->moderate, 257.39->moderate. USID_45: 192.07->moderate, 195.31->moderate. USID_10: 273.05->low (borderline: <274.07 threshold), 275.64->moderate."
    },
    {
        "step": "Step E - KPI Risk Determination",
        "data_used": "worst_pressure_base=high (USID_01,25,43); worst_pressure_stress=critical (USID_01,25). Primary absorber from preprocessing_stats=USID_01. Rule: base=high + stress=critical + primary absorber at critical -> critical.",
        "assumption": "no proxy",
        "result": "overload_risk_base=high, overload_risk_stress=critical, overload_risk=critical."
    },
    {
        "step": "Step F - Forecast Uncertainty",
        "data_used": "area_profile dominant_landuse=unknown. absorption_fractions are pixel-based spatial proxies. USID_01 and USID_25 diverge by 2 tiers (high vs critical). Weekday candidate well-supported (n=1936).",
        "assumption": "Spatial proxy is the only available redistribution mechanism.",
        "result": "forecast_uncertainty.level=medium. All selected values anchored in historical distributions from get_kpi_history filtered to outage_window_hours. base_case=144.68 and stress_case=171.89 both within [p10=104.01, p90=171.89]."
    }
]

# ---- Assemble full artifact ----
artifact = {
    "run_id": "TKT-2026-04-17-0002_20260507T091321Z",
    "ticket_id": "TKT-2026-04-17-0002",
    "affected_usid": "USID_09",
    "affected_sectors": ["USID_09_S0", "USID_09_S2"],
    "outage_window_hours": OUTAGE_HOURS,
    "duration_hours": 10.46,

    "forecast_framing": {
        "forecast_type": "counterfactual_neighbor_load",
        "scenario": "partial_outage_weekday_peak_overlap_sustained",
        "forecast_horizon_hours": OUTAGE_HOURS,
        "contamination_policy": "do_not_use_actual_neighbor_outage_window_kpi",
        "reason": "Forecast estimates load neighbors would face if failed sectors traffic redistributes; actual neighbor outage-window KPI not used as ground truth."
    },

    "lost_traffic_candidates": {
        "same_hour_60d_mean_mbps": AFF_60D_MEAN,
        "same_hour_60d_p75_mbps": AFF_60D_P75,
        "same_hour_60d_p90_mbps": AFF_60D_P90,
        "same_daytype_same_hour_mean_mbps": AFF_WDAY_MEAN,
        "recent_14d_same_hour_mean_mbps": AFF_14D_MEAN,
        "peak_hour_mean_mbps": AFF_PEAK_MEAN,
        "candidate_notes": [
            "60d stats from get_kpi_history(USID_09) S0+S2 sectors, hours 10-20 aggregated per 15-min timestamp (n=2640)",
            "weekday mean filtered to weekday records only (n=1936)",
            "recent 14d covers 2026-04-03 to 2026-04-16 (n=924)",
            "peak-hour mean covers hours 17-20 only (n=960)"
        ]
    },

    "lost_traffic_forecast": {
        "base_case_mbps": BASE_CASE_MBPS,
        "stress_case_mbps": STRESS_CASE_MBPS,
        "selected_base_source": "same_daytype_same_hour_mean_mbps",
        "selected_stress_source": "same_hour_60d_p90_mbps",
        "directional_adjustment": "upward",
        "reason": "peak_overlap=true on weekday. Weekday same-hour mean (144.68) is +6% above 60d mean (136.43), capturing weekday traffic uplift. Friday with peak hours 17-20 in window warrants day-type context over all-day average.",
        "why_not_fixed_factor_only": "The 11-hour window has a 37% intra-day swing (H10 mean 119.53 vs H19 mean 163.36 Mbps). A single multiplicative factor applied to the 60d window average misallocates burden: it would underestimate peak-hour displaced traffic (H19: actual 163.36 vs window mean 136.43) and overestimate off-peak hours (H10: actual 119.53 vs window mean 136.43). Hourly per-hour forecasts capture this variation explicitly.",
        "candidate_summary": {
            "60d_mean": AFF_60D_MEAN, "60d_p75": AFF_60D_P75, "60d_p90": AFF_60D_P90,
            "weekday_mean": AFF_WDAY_MEAN, "recent_14d_mean": AFF_14D_MEAN, "peak_hour_mean": AFF_PEAK_MEAN
        }
    },

    # Legacy fields
    "lost_traffic_mbps": LOST_TRAFFIC_MBPS,
    "adjusted_lost_traffic_mbps": BASE_CASE_MBPS,
    "lost_volume_gb": LOST_VOL_GB,
    "adjusted_lost_volume_gb": ADJ_VOL_GB,
    "loss_ratio": 0.68,
    "baseline_mbps": 199.43,
    "baseline_adjustment_factor": BAF,
    "time_background_applied": True,

    "per_neighbor": per_neighbor,

    "overload_risk": overload_risk,
    "overload_risk_base": orb,
    "overload_risk_stress": ors,
    "overload_risk_note": (
        "USID_01 (af=0.5714): base=high [270.84>p90=232.63], stress=critical [286.37>p90x1.20=279.16]. "
        "USID_25 (af=0.50): base=high [241.62>210.33], stress=critical [255.23>252.40]. "
        "USID_43 (af=0.4286): base=high [241.21>222.82], stress=high [252.87<267.38]. "
        "USID_29: moderate both. USID_45: moderate both. USID_10: low base [273.05 vs thresh 274.07], moderate stress. "
        "Primary absorber USID_01 at critical stress -> final=critical."
    ),

    "forecast_uncertainty": {
        "level": "medium",
        "drivers": [
            "area_profile_unknown: dominant_landuse=unknown; no land-use demand calibration possible",
            "absorption_fraction_spatial_proxy: pixel-count-based redistribution, not traffic-proportional",
            "base_stress_tier_divergence: USID_01 and USID_25 differ by 2 tiers (high vs critical)"
        ],
        "guardrails": [
            "All selected forecast values anchored to historical distributions from get_kpi_history filtered to outage_window_hours",
            "base_case_mbps=144.68 is within historical p10-p90 range [104.01, 171.89]",
            "stress_case_mbps=171.89 equals historical p90 and does not exceed observed range",
            "No absorption fraction was estimated; all read from preprocessing_stats per_backup",
            "Hourly candidates all derived from get_kpi_history records filtered to exact hour-of-day"
        ]
    },

    "uncertainty": {
        "level": "medium",
        "reasons": [
            "area_profile unknown",
            "absorption_fraction is spatial-coverage proxy",
            "base/stress diverge by up to 2 tiers for primary absorbers USID_01 and USID_25"
        ]
    },

    "reasoning_log": rl,

    # ---- Sustained pressure extension ----
    "sustained_pressure_verdict": spv,
    "sustained_pressure_reason": spr,
    "hourly_lost_traffic_candidates": {
        f"{h:02d}:00": {
            "same_hour_mean_mbps": HOURLY_CANDS[h]["mean"],
            "same_hour_p75_mbps": HOURLY_CANDS[h]["p75"],
            "same_hour_p90_mbps": HOURLY_CANDS[h]["p90"],
            "same_daytype_hour_mean_mbps": HOURLY_CANDS[h]["wday"],
            "recent_14d_hour_mean_mbps": HOURLY_CANDS[h]["d14"],
            "candidate_notes": ["peak hour: weekday mean as base, p90 as stress"] if h in PEAK_HOURS else []
        }
        for h in OUTAGE_HOURS
    },
    "hourly_lost_traffic_forecast": hourly_lost_forecast,
    "hourly_neighbor_forecast": hourly_nb,
    "hourly_distribution": {
        "base": {"stable_hours": bc["stable"], "stressed_hours": bc["stressed"], "overloaded_hours": bc["overloaded"]},
        "stress": {"stable_hours": sc["stable"], "stressed_hours": sc["stressed"], "overloaded_hours": sc["overloaded"]}
    },
    "hourly_distribution_legacy": {
        "stable_hours": bc["stable"], "stressed_hours": bc["stressed"], "overloaded_hours": bc["overloaded"]
    },
    "trend": "worsening",
    "trend_detail": {
        "label": "worsening_then_persistent",
        "reason": (
            "USID_01 is overloaded at every hour H10-H20 in both base and stress cases. "
            "Absolute base load escalates from 230.61 Mbps (H10) to 325.63 Mbps (H19), a 41% rise. "
            "Pressure accelerates at H17 (+23 Mbps vs H16 USID_01 load) entering peak. "
            "H19 is the worst hour (lost traffic 173.38 Mbps base). H20 remains elevated at 310.50 Mbps."
        )
    },
    "peak_hour_verdict": phv,
    "peak_derivation": {
        "peak_hours": [f"{h:02d}:00" for h in PEAK_HOURS],
        "base_case_peak_classifications": pkb,
        "stress_case_peak_classifications": pks,
        "derived_peak_hour_verdict": phv,
        "peak_verdict_rule": "Base overloaded in all 4 peak hours (H17-H20, worst neighbor USID_01) -> critical"
    },
    "sustained_reasoning_log": srl
}

out_dir = "artifacts/TKT-2026-04-17-0002_20260507T091321Z"
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, "kpi_agent_artifact.json")
with open(out_path, "w") as f:
    json.dump(artifact, f, indent=2)

print(f"Wrote: {out_path}")
print(f"overload_risk={overload_risk} (base={orb}, stress={ors})")
print(f"peak_hour_verdict={phv}")
print(f"sustained_pressure_verdict={spv}")
print(f"base_dist=stable:{bc['stable']} stressed:{bc['stressed']} overloaded:{bc['overloaded']}")
print(f"stress_dist=stable:{sc['stable']} stressed:{sc['stressed']} overloaded:{sc['overloaded']}")
