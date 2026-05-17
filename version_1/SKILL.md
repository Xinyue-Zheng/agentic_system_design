# SKILL: USID Outage Impact Assessment Pipeline
## Version 2.1 | Claude Code Native Execution | Fully Automatic

---

## HOW TO USE

Prepare your input files, then just say:

```
run the pipeline for USID_00, shutdown 2024-03-15 08:00 to 2024-03-15 12:00
```

Claude Code handles everything automatically — preprocessing, all 5 stages,
verification, and final summary. No manual steps needed.

---

## INPUT FILES (prepare these before running)

```
/workspace/data/
    usid_coverage_pixels.json    REQUIRED  pixel-level coverage data
    usid_attributes.csv          REQUIRED  USID attribute table
    real_map.png                 OPTIONAL  geographic map image
```

To generate synthetic test data:
```bash
python /workspace/synthetic_data_generator.py \
    --n-usids 5 \
    --output-dir /workspace/data/
```

That produces `usid_coverage_pixels.json` and `usid_attributes.csv` ready to use.

---

## OUTPUT FILES (auto-generated in results folder)

```
/workspace/results/TARGET_USID/
    preprocessing_stats.json        Step 0 — coverage + capacity + load stats
    rsrp_USID_XX.png               Step 0 — RSRP image per USID
    dominance_map_full.png         Step 0 — dominance map
    sinr_map.png                   Step 0 — SINR map
    stage1_coverage_load.json      Stage 1 output
    stage2_attribute_config.json   Stage 2 output
    stage3_geographic.json         Stage 3 output
    stage4_final_USID_XX.json      Stage 4 final assessment
    stage5_verification.json       Stage 5 verification checks
```

---

## REFERENCE THRESHOLDS (use in every stage analysis)

```
3GPP TS 38.133 / 36.133
RSRP:       Excellent > -80 dBm  | Good -90 to -80  | Moderate -100 to -90  | Poor < -100
SINR:       Excellent > 20 dB    | Good 13 to 20    | Moderate 0 to 13      | Poor < 0
RSRQ:       Excellent > -10 dB   | Good -14 to -10  | Moderate -17 to -14   | Poor < -17
Throughput: High > 50 Mbps       | Medium 10 to 50  | Low < 10 Mbps
Dominance:  Dominant-anchor >= 30% pixels | Strong-supporting 10-30%
            Localized-supporting 3-10%    | Edge-limited < 3%

SINR Regime:
  Noise-limited     (SINR > 10 dB) -> backup much weaker after shutdown -> SEVERE impact
  Interference-limited (SINR < 5 dB) -> backup already strong -> MILD impact
  Mixed (5-10 dB)                    -> intermediate

Load Risk Thresholds:
  post_outage_load_factor > 0.8 -> HIGH
  post_outage_load_factor > 0.5 -> MEDIUM
  else                          -> LOW

Capacity Formula (pre-computed locally, never recompute):
  capacity_score = (4G_cells x 1.0 + 5G_cells x 2.0) x (1 + 0.15 x active_bands)
```

---

## FULL PIPELINE EXECUTION INSTRUCTIONS

When triggered, execute ALL steps below IN ORDER without stopping.
Do not ask for confirmation between steps — run the full pipeline automatically.
Only stop if a step produces an error.

---

### STEP 0A — VALIDATE INPUTS

Check all required files exist:

```bash
ls /workspace/data/usid_coverage_pixels.json
ls /workspace/data/usid_attributes.csv
```

If either is missing, stop and tell the user:
```
Missing input files. Please run:
python /workspace/synthetic_data_generator.py --n-usids 5 --output-dir /workspace/data/
```

Check for optional real map:
```bash
ls /workspace/data/real_map.png 2>/dev/null && echo "real map found" || echo "no real map - Stage 3 will use signal patterns only"
```

Create output directory:
```bash
mkdir -p /workspace/results/TARGET_USID/
```

Replace TARGET_USID with the actual target USID name throughout all steps.

---

### STEP 0B — RUN LOCAL PREPROCESSING

Run this bash command:

```bash
python /workspace/version_1/utils/local_preprocessing_1.py \
    --coverage-json /workspace/version_1/data/usid_coverage_pixels.json \
    --attr-csv      /workspace/version_1/data/usid_attributes.csv \
    --target-usid   USID_00 \
    --output-dir    /workspace/version_1/results/USID_00/
```

Wait for it to finish. You will see:
```
[PreProcess] Coverage summary...
[PreProcess] Capacity summary (all USIDs)...
[PreProcess] Neighbor identification...
[PreProcess] Load redistribution analysis...
[PreProcess] Generating images...
[PreProcess] Done -> /workspace/results/TARGET_USID/preprocessing_stats.json
```

Then read the stats and all images:

```bash
cat /workspace/results/TARGET_USID/preprocessing_stats.json
ls /workspace/results/TARGET_USID/*.png
```

Read every PNG image directly — you will need them for Stages 1 and 3.
Store the full preprocessing_stats.json in memory for all stages.

---

### COVERAGE AND LOAD REDISTRIBUTION ANALYSIS

**Your role:** Wireless network coverage and load redistribution analysis agent.

**Inputs from preprocessing:**
- coverage_summary.per_usid — per-USID RSRP stats and dominance fractions
- load_redistribution — backup absorption, RSRP gap replaceability, overload risk
- overlap_info — neighbor ranking by overlap fraction
- RSRP images for target USID and each neighbor
- SINR map image

**COVERAGE ROLES — analyze only the target USID and its neighbors:**
We already know which USID is shutting down. Only analyze:
  (a) The target USID — its role and spatial RSRP pattern
  (b) Each neighbor USID (from overlap_info where is_neighbor=true) —
      their role and how well they can serve the target's area

For each USID analyzed:
- Use inferred_role from preprocessing as primary classification
- Cite dominant_pixel_fraction and rsrp_p50_dbm for every role assignment
- Confidence = high if dom_frac >= 0.15 AND rsrp_p50 >= -90 dBm
- Confidence = low  if dom_frac <  0.05 OR  rsrp_p50 <  -100 dBm

**LOAD REDISTRIBUTION — from load_redistribution:**
- For each backup USID cite: absorption_fraction_of_target, handover_quality,
  rsrp_p50_in_zone_dbm, sinr_regime_impact_note (from RSRP gap), post_outage_load_factor, overload_risk
- Coverage holes: cite coverage_hole_fraction directly
- Overall verdict: adequate | strained | overloaded

**IMAGE SPATIAL ANALYSIS:**
- Describe RSRP weak zones using compass directions (NW, SE, center, etc.)
- Identify where RSRP drops below -100 dBm relative to the dominance boundary
- Every spatial claim must be consistent with the statistics

**VERIFICATION CONTRACT:**
- Every number you cite must come from preprocessing_stats.json
- Do not invent any statistic not in the data
- Spatial claims must not contradict statistics

**Output — write to /workspace/results/TARGET_USID/stage1_coverage_load.json:**
```json
{
  "usids": [
    {
      "usid": "string",
      "role": "dominant-anchor | strong-supporting | localized-supporting | edge-limited",
      "role_confidence": "low | medium | high",
      "dominant_pixel_fraction": 0.0,
      "rsrp_p50_dbm": 0.0,
      "rsrp_spatial_pattern": "compass-direction description from RSRP image — where strong, where weak relative to target boundary"
    }
  ],
  "target_load_analysis": {
    "target_usid": "string",
    "dominant_area_impact_regime": "mostly_severe | mixed | mostly_mild",
    "coverage_hole_fraction": 0.0,
    "coverage_hole_assessment": "string",
    "per_backup": [
      {
        "backup_usid": "string",
        "absorption_fraction_of_target": 0.0,
        "handover_quality": "good | partial | poor",
        "rsrp_p50_in_zone_dbm": 0.0,
        "sinr_regime_impact_note": "mostly_severe | mixed | mostly_mild",  // derived from RSRP gap — read from preprocessing per_backup
        "post_outage_load_factor": 0.0,
        "overload_risk": "low | medium | high",
        "assessment": "2-sentence grounded assessment citing the numbers above"
      }
    ],
    "load_redistribution_verdict": "adequate | strained | overloaded",
    "verdict_reasoning": ["reason 1 citing specific numbers", "reason 2"]
  },
  "key_findings_for_stage3": ["2-4 spatial findings about WHERE weak zones are"],
  "uncertainty": {"level": "low | medium | high", "reasons": ["..."]}
}
```

After writing the file confirm:
```bash
ls -la /workspace/results/TARGET_USID/stage1_coverage_load.json
```

---

### STAGE 2 — ATTRIBUTE AND CONFIGURATION ANALYSIS

**Your role:** Wireless network site-attribute and configuration analysis agent.

**Inputs:**
- preprocessing_stats.json section: capacity_summary (pre-computed for ALL USIDs)
- Attribute CSV:
```bash
cat /workspace/data/usid_attributes.csv
```

**NOTE: Stage 1 output is NOT used here. This stage is purely attribute-driven.**

**FOR EACH USID:**
- capacity_score: READ from capacity_summary — DO NOT recompute
- tower_type: height < 25m = micro | 25-45m = macro | > 45m = tall_macro
- technology_profile: 4G-only | 5G-only | 5G-dominant | mixed-4G-5G
- operational_role: read from capacity_summary.operational_role
- key_observations: what does the band/tower profile suggest operationally?

**NSA 5G DOWNGRADE RISK:**
If target has 5G_cells > 0 AND primary backup has 5G_cells = 0:
  - Flag it — 5G users forced to downgrade to 4G after shutdown
  - Estimate affected_fraction = (target_5G / (target_4G + target_5G))
                                 x target_dominant_fraction

**VERIFICATION CONTRACT:**
- Every capacity_score must match capacity_summary exactly
- Tower type must strictly follow height thresholds
- Do not invent coverage radii or user counts

**Output — write to /workspace/results/TARGET_USID/stage2_attribute_config.json:**
```json
{
  "usids": [
    {
      "usid": "string",
      "capacity_score": 0.0,
      "tower_type": "micro | macro | tall_macro",
      "active_band_count": 0,
      "technology_profile": "4G-only | 5G-only | 5G-dominant | mixed-4G-5G",
      "operational_role": "coverage-oriented | capacity-oriented | mixed",
      "role_confidence": "low | medium | high",
      "key_observations": ["observation grounded in attribute data"]
    }
  ],
  "nsa_5g_downgrade_risk": {
    "flagged": false,
    "target_5g_cells": 0,
    "primary_backup_5g_cells": 0,
    "affected_fraction_estimate": 0.0,
    "explanation": "string or null"
  },
  "overall_capacity_verdict": "adequate | constrained | insufficient",
  "capacity_verdict_reasoning": ["reason citing specific sites and scores"],
  "key_findings_for_stage4": ["2-3 configuration findings"],
  "uncertainty": {"level": "low | medium | high", "reasons": ["..."]}
}
```

After writing confirm:
```bash
ls -la /workspace/results/TARGET_USID/stage2_attribute_config.json
```

---

### STAGE 3 — GEOGRAPHIC CORRELATION ANALYSIS

**Your role:** Wireless network geographic correlation agent.

**Inputs:**
- preprocessing_stats.json: load_redistribution + overlap_info
- From Stage 1 ONLY: load_redistribution_verdict + per_backup overload_risk
- All RSRP images — read directly
- SINR map — read directly
- Dominance map overview + neighborhood — read directly
- Real map if available:
```bash
ls /workspace/data/real_map.png 2>/dev/null || echo "no real map"
```

**CORE TASK:**
Identify WHERE within the target's dominant area specific impact types will
occur, by correlating coverage/signal patterns with geographic features.
Every impact zone must be grounded in BOTH image evidence AND map evidence.

---

**STEP 1 — IDENTIFY IMPACT ZONES**

Scan the target's dominant area (inside red contour on RSRP image) and divide
it into zones based on visible signal variation. Typical zones: NW quadrant,
center core, SE edge, highway corridor, etc. 2-5 zones is normal.

For each zone, determine the four properties below IN ORDER before assigning
impact_severity.

---

**FIELD RULES**

**`signal_condition`** — from RSRP image + preprocessing stats

Read the backup USID's RSRP color in this zone from the RSRP image.
Cross-check against rsrp_in_zone_p50_dbm from preprocessing per_backup.
```
strong:    rsrp_in_zone_p50 > -80 dBm
moderate:  rsrp_in_zone_p50 -90 to -80 dBm
weak:      rsrp_in_zone_p50 -100 to -90 dBm
very_weak: rsrp_in_zone_p50 < -100 dBm
```

If the zone is a coverage hole (no backup at all) → always very_weak.
You MUST cite the specific dBm value from preprocessing in signal_evidence.

---

**`sinr_regime`** — three-signal classification (SINR + dominant RSRP + RSRP gap)

This is the most important classification. SINR alone is insufficient because
low SINR can mean either:
  (a) many strong competing USIDs → mild impact (interference-limited)
  (b) environment attenuation weakening ALL signals → severe impact

You must use all three signals together:
```
Signal 1 — RSRP gap (from preprocessing per_backup hard_gap_fraction /
                      easy_gap_fraction):
  gap > 15 dB  → replaceability = hard    (hard_gap_fraction high)
  gap 8-15 dB  → replaceability = partial
  gap < 8 dB   → replaceability = easy    (easy_gap_fraction high)

Signal 2 — Dominant RSRP (from preprocessing coverage_summary
           per_usid[target].rsrp_p50_dbm):
  > -90 dBm    → environment = good
  -100 to -90  → environment = marginal
  < -100 dBm   → environment = poor

Signal 3 — SINR (from preprocessing target_dom_high/low_sinr_fraction,
           confirmed visually from SINR map):
  target_dom_high_sinr_fraction > 0.30 → sinr = high (noise-limited)
  target_dom_low_sinr_fraction  > 0.30 → sinr = low  (interference-limited)
  else                                  → sinr = mixed
```

Combined classification rules (apply in order, take first match):
```
RULE 1 → noise_limited (severe):
  replaceability = hard
  AND environment = good
  AND sinr = high
  MEANING: USID_00 is strong, alone, backup much weaker
           → user completely depends on USID_00
           → shutdown causes large quality drop

RULE 2 → interference_limited (mild):
  replaceability = easy
  AND environment = good
  AND sinr = low
  MEANING: dense urban, many strong competitors, backup nearly dominant
           → backup takes over smoothly
           → SINR may even improve after shutdown

RULE 3 → mostly_mild (easy replacement regardless of SINR):
  replaceability = easy
  AND environment = good
  AND sinr = high OR mixed
  MEANING: backup nearly as strong as dominant
           → handover quality good even without interference context

RULE 4 → environment_attenuated (severe despite low SINR):
  environment = marginal OR poor
  AND replaceability = easy OR partial
  MEANING: both dominant and backup weak due to forest/building/terrain
           → NOT interference-limited, environment is the problem
           → low SINR here is NOT caused by strong competitors
           → severe impact because both signals are marginal

RULE 5 → coverage_hole_like (severe):
  environment = poor
  AND replaceability = hard
  MEANING: near coverage hole, backup barely reachable

RULE 6 → mixed:
  replaceability = hard
  AND environment = good
  AND sinr = low
  MEANING: USID_00 dominates despite interference, but backup is weak
           → moderate quality drop expected

RULE 7 → mixed (all other cases)
```

Map to sinr_regime output field:
```
noise_limited         → "noise_limited"
interference_limited  → "interference_limited"
mostly_mild           → "interference_limited"
environment_attenuated → "noise_limited"
coverage_hole_like    → "noise_limited"
mixed                 → "mixed"
```

MUST cite which preprocessing fractions support the classification.
---

**`land_use`** — from real map image only

Identify from visible map features:
```
hospital:    red cross symbol, hospital label, large medical building
commercial:  dense blocks, shopping centers, office parks, parking lots
residential: regular street grid, smaller buildings, suburban pattern
road:        major road/highway/expressway as thick colored line through zone
industrial:  large warehouse footprints, factory buildings, logistics parks
forest:      green shaded area, park label, tree symbols
water:       blue area, river, lake, creek
uncertain:   none of the above clearly identifiable
```

If no real map provided → always uncertain.
You MUST cite the specific visible map feature in geographic_evidence.
Do NOT infer land use from signal patterns — only from the map.

---

**`is_critical_infrastructure`** — derived from land_use
```
True:  land_use = hospital
True:  land_use = road AND it is a major highway or expressway
       (minor residential roads → False)
False: all other land_use values including uncertain
```

Never set True without explicit map evidence.

---

**`user_relevance`** — derived from land_use only, independent of signal
```
critical: hospital
high:     residential, commercial
medium:   road (highway/expressway only)
low:      industrial, forest, water, uncertain
```

---

**`impact_severity`** — combine all four properties above

Apply rules in priority order. Take the HIGHEST matching level.
```
CRITICAL — if ANY of:
  is_critical_infrastructure = True
  AND signal_condition IN [weak, very_weak]

HIGH — if ANY of:
  signal_condition = very_weak
  AND land_use IN [residential, commercial]

  signal_condition = weak
  AND is_critical_infrastructure = True

  sinr_regime = noise_limited
  AND land_use IN [residential, commercial]

  overload_risk = high
  AND signal_condition IN [weak, very_weak]

MODERATE — if ANY of:
  signal_condition = weak
  AND land_use IN [residential, commercial, road]

  signal_condition = very_weak
  AND land_use IN [industrial, forest]

  sinr_regime = noise_limited
  AND land_use IN [industrial, road]

  overload_risk = medium
  AND signal_condition = weak

LOW — if ANY of:
  signal_condition = moderate
  AND land_use IN [industrial, forest, water, uncertain]

  sinr_regime = interference_limited
  AND signal_condition != very_weak

NEGLIGIBLE — if ALL of:
  signal_condition = strong
  sinr_regime IN [interference_limited, mixed]
  is_critical_infrastructure = False
```

---

**`zone_name` and `location`** — descriptive, consistent format
```
zone_name: "[land_use] [compass direction]"
           e.g. "residential NW", "forest NE", "highway corridor center"

location:  "[compass direction], [relative position in target area]"
           e.g. "NW quadrant, outer edge of target boundary"
           e.g. "center, adjacent to target tower position"
```

---

**GEOGRAPHIC CORRELATION RULE**

Every spatial claim in evidence must reference BOTH:
  (1) a location in the coverage or SINR image
  (2) a visible feature in the real map

Example:
  signal_evidence:    "rsrp_in_zone_p50 = -96 dBm (from preprocessing per_backup)"
  sinr_evidence:      "SINR map shows cool blue in NW zone, consistent with
                       target_dom_low_sinr_fraction = 0.54"
  geographic_evidence: "open parkland visible in NW of real map"
  load_evidence:      "USID_31 overload_risk = medium (from Stage 1)"

If no real map → geographic_evidence = "no real map provided" for every zone.
Set uncertainty.level = "high" when no real map.

---

**COVERAGE HOLE ASSESSMENT**

hole_fraction: read directly from load_redistribution.coverage_hole_fraction
hole_location_description: identify WHERE the grey pixels are in the RSRP image
land_use_in_hole_area: identify land use under those grey pixels from real map
user_impact_of_holes: use same user_relevance rules as impact zones above

---

**VERIFICATION CONTRACT**
- signal_condition must match rsrp_in_zone_p50_dbm range exactly
- sinr_regime must cite supporting fraction from preprocessing
- geographic claims require real map feature — no inference from signal alone
- is_critical_infrastructure = True requires explicit map evidence
- impact_severity must follow priority rule table above exactly
- No real map → uncertainty.level = "high", all land_use = "uncertain"
- Do NOT make coverage claims (e.g. "full coverage") — only Stage 1 can do that
- Do NOT contradict Stage 1 coverage_hole_fraction

---

**Output — write to /workspace/results/TARGET_USID/stage3_geographic.json:**
```json
{
  "area_overview": {
    "geographic_character": "urban | suburban | rural | mixed",
    "map_explains_signal_patterns": true,
    "key_geographic_observations": ["..."]
  },
  "impact_zones": [
    {
      "zone_name": "[land_use] [compass direction]",
      "location": "[compass direction], [relative position]",
      "signal_condition": "strong | moderate | weak | very_weak",
      "sinr_regime": "noise_limited | interference_limited | mixed",
      "land_use": "hospital | commercial | residential | road | industrial | forest | water | uncertain",
      "is_critical_infrastructure": false,
      "impact_severity": "critical | high | moderate | low | negligible",
      "evidence": {
        "signal_evidence": "cite rsrp_in_zone_p50_dbm value from preprocessing",
        "sinr_evidence": "cite high/low_sinr_fraction from preprocessing",
        "geographic_evidence": "cite specific visible map feature or state uncertain",
        "load_evidence": "cite overload_risk from Stage 1 for this zone's backup"
      },
      "user_relevance": "low | medium | high | critical"
    }
  ],
  "coverage_hole_geographic_assessment": {
    "hole_fraction": 0.0,
    "hole_location_description": "compass direction of grey pixels in RSRP image",
    "land_use_in_hole_area": "land use under hole pixels from real map",
    "user_impact_of_holes": "low | medium | high | critical"
  },
  "load_geographic_context": {
    "primary_backup_area_character": "string",
    "backup_serves_same_critical_areas": true,
    "notes": "string"
  },
  "key_findings_for_stage4": ["2-5 findings each citing image + map + stat evidence"],
  "uncertainty": {"level": "low | medium | high", "reasons": ["..."]}
}
```

After writing confirm:
```bash
ls -la /workspace/results/TARGET_USID/stage3_geographic.json
```

---

### STAGE 4 — FINAL INTEGRATED ASSESSMENT

**Your role:** Final outage impact assessment agent.

Read all stage outputs:
```bash
cat /workspace/results/TARGET_USID/stage1_coverage_load.json
cat /workspace/results/TARGET_USID/stage2_attribute_config.json
cat /workspace/results/TARGET_USID/stage3_geographic.json
```

**USER IMPACT SCALE:**
- Level 1: Minimal    — holes < 5%, no critical infra, adequate backup, low load
- Level 2: Noticeable — holes 5-20% OR partial backup OR medium load risk
- Level 3: Significant — holes > 20% OR critical infrastructure OR high load risk
- Level 4: Severe     — multiple: large holes + critical infra + overloaded backups

**HARD CONSTRAINTS — apply ALL that are triggered:**
- C1: hole_fraction < 0.05 AND all overload_risk = low -> level <= 2
- C2: any is_critical_infrastructure = true            -> level >= 3
- C3: dominant_area_impact_regime = mostly_mild        -> reduce severity one level
- C4: load_redistribution_verdict = overloaded         -> increase severity one level
- C5: nsa_5g flagged AND affected_fraction > 0.2       -> add to impact_breakdown

**SHUTDOWN DURATION REASONING:**
Compute duration = hours between shutdown_start and shutdown_end
- < 1 hour:  transient — most users unaffected unless in active session
- 1-4 hours: sustained — affects all users during that period
- > 4 hours: full-day impact — hits multiple traffic peaks

**Output — write to /workspace/results/TARGET_USID/stage4_final_TARGET_USID.json:**
```json
{
  "target_usid": "string",
  "shutdown_start": "string",
  "shutdown_end": "string",
  "shutdown_duration_hours": 0.0,
  "overall_rating": {
    "impact_severity": "low | moderate | high | critical",
    "user_impact_level": 1,
    "summary_label": "short phrase",
    "confidence": "low | medium | high"
  },
  "impact_breakdown": {
    "radio_degradation_risk":   "low | moderate | high | critical",
    "service_degradation_risk": "low | moderate | high | critical",
    "user_facing_impact_risk":  "low | moderate | high | critical",
    "load_redistribution_risk": "low | moderate | high | critical",
    "5g_downgrade_risk":        "none | low | moderate | high"
  },
  "constraint_check": {
    "C1_applied": false,
    "C2_applied": false,
    "C3_applied": false,
    "C4_applied": false,
    "C5_applied": false
  },
  "most_affected_zones": [
    {
      "zone_name": "string",
      "location": "string",
      "impact_severity": "critical | high | moderate | low",
      "primary_cause": ["coverage_loss | load_overload | 5g_downgrade | quality_degradation"],
      "user_relevance": "low | medium | high | critical"
    }
  ],
  "main_reasons": ["2-5 grounded reasons citing stage outputs"],
  "mitigating_factors": ["grounded factors reducing impact"],
  "final_conclusion": "3-5 sentence summary for senior network engineer",
  "confidence": {"level": "low | medium | high", "reasons": ["..."]}
}
```

After writing confirm:
```bash
ls -la /workspace/results/TARGET_USID/stage4_final_TARGET_USID.json
```

---

### STAGE 5 — INDEPENDENT VERIFICATION

**Your role:** Independent verification agent. Be strict — FAIL means the result
cannot be trusted without human review.

Read ground truth and all stage outputs:
```bash
cat /workspace/results/TARGET_USID/preprocessing_stats.json
cat /workspace/results/TARGET_USID/stage1_coverage_load.json
cat /workspace/results/TARGET_USID/stage2_attribute_config.json
cat /workspace/results/TARGET_USID/stage3_geographic.json
cat /workspace/results/TARGET_USID/stage4_final_TARGET_USID.json
```

**Run ALL 15 checks:**
```
V1:  Every USID role label matches preprocessing inferred_role
V2:  Every cited dominant_pixel_fraction within +/-0.01 of pre-computed
V3:  Every cited rsrp_p50_dbm within +/-2 dBm of pre-computed
V4:  coverage_hole_fraction within +/-0.01 of pre-computed
V5:  Each post_outage_load_factor within +/-0.05 of pre-computed
V6:  Each absorption_fraction_of_target within +/-0.02 of pre-computed
V7:  overload_risk labels match thresholds (>0.8=high, >0.5=medium, else low)
V8:  sinr_regime_impact_note matches preprocessing per_backup[usid].sinr_regime_impact_note (derived from RSRP gap)
V9:  Stage 2 capacity_scores match pre-computed within +/-0.5
V10: Tower types match height rules (<25m=micro, 25-45m=macro, >45m=tall_macro)
V11: If C1 triggered: level <= 2
V12: If C2 triggered: level >= 3
V13: If C3 triggered: severity adjusted down
V14: If C4 triggered: severity adjusted up
V15: Stage 4 level consistent with Stage 1 + Stage 3 combined evidence
```

**Output — write to /workspace/results/TARGET_USID/stage5_verification.json:**
```json
{
  "verification_summary": {
    "total_checks": 15,
    "passed": 0,
    "failed": 0,
    "flagged": 0,
    "overall_result": "PASS | FAIL | NEEDS_REVIEW"
  },
  "checks": [
    {
      "check_id": "V1",
      "description": "string",
      "result": "PASS | FAIL | FLAG",
      "expected": "string",
      "found": "string",
      "note": "string"
    }
  ],
  "critical_failures": ["V-check IDs that invalidate the result"],
  "recommendations": ["actions for engineer if checks FAIL or FLAG"],
  "verified_final_rating": {
    "user_impact_level": 0,
    "impact_severity": "string",
    "is_verified": true
  }
}
```

After writing confirm:
```bash
ls -la /workspace/results/TARGET_USID/stage5_verification.json
```

---

### FINAL SUMMARY — print this after all stages complete

```
╔══════════════════════════════════════════════════════╗
║       USID OUTAGE IMPACT ASSESSMENT COMPLETE         ║
╠══════════════════════════════════════════════════════╣
║  Target USID  : [TARGET_USID]                        ║
║  Shutdown     : [START] -> [END]  ([DURATION]h)      ║
║  Severity     : [impact_severity]                    ║
║  User Level   : [user_impact_level] / 4              ║
║  Summary      : [summary_label]                      ║
║  Confidence   : [confidence]                         ║
║  Verification : [PASS/FAIL] ([X]/15 checks passed)   ║
╚══════════════════════════════════════════════════════╝

Most affected zones:
  [zone_name] — [impact_severity] — [user_relevance]
  ...

Conclusion:
  [final_conclusion text]

All output files saved to: /workspace/results/[TARGET_USID]/
```

---

## PARTIAL RE-RUNS (for prompt refinement)

After editing any stage section above, re-run just that stage:

**Re-run single stage (reuses all previous outputs):**
```
re-run stage 3 for USID_00
```

**Re-run from a stage onwards:**
```
re-run from stage 2 for USID_00, shutdown 2024-03-15 08:00 to 2024-03-15 12:00
```

**Re-run only preprocessing:**
```
re-run preprocessing for USID_00
```

**Re-run full pipeline:**
```
run the pipeline for USID_00, shutdown 2024-03-15 08:00 to 2024-03-15 12:00
```

When re-running a single stage, skip Step 0 entirely and read the existing
preprocessing_stats.json directly.

---

## TROUBLESHOOTING

**Input files missing:**
```bash
python /workspace/synthetic_data_generator.py --n-usids 5 --output-dir /workspace/data/
```

**Preprocessing failed:**
```bash
python /workspace/utils/local_preprocessing.py --help
```

**Package missing:**
```bash
pip install package_name
```

**Want to add a real map:**
```bash
cp /path/to/your/map.png /workspace/data/real_map.png
# Then re-run stage 3
```

**Want to change a threshold:**
Edit the REFERENCE THRESHOLDS section above, then re-run the affected stages.