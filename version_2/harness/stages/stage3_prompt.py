STAGE3_PROMPT = """
You are analysing a cellular base station outage impact assessment.

TARGET USID: {target_usid}

YOUR TASK — Stage 3: Geographic Correlation

Divide {target_usid}'s dominant area into 2–5 geographic zones.
For each zone determine:

1. Signal condition — from backup RSRP values (cite exact values from preprocessing)
2. SINR regime — apply the THREE-SIGNAL classification:
   - Step 1: RSRP gap → replaceability (hard >= 20dB / partial 8-20dB / easy < 8dB)
   - Step 2: Dominant RSRP → environment (good > -90 / marginal -100 to -90 / poor < -100)
   - Step 3: High SINR fraction → interference context
   - Apply rules R1–R7 in order, state which fires first and why others were skipped
3. Land use — from the real map image (required)
4. Critical infrastructure — explicit map evidence required
5. Impact severity — apply severity rule table from hot tier

MANDATORY SCRATCHPAD FORMAT:
For EVERY zone and EVERY classification decision:

DECISION: [field name] for [zone_name]
  Observation:  [exact value + source field path]
  Standard:     [exact threshold from hot tier]
  Rule applied: [rule ID and text]
  Rules skipped:[rules checked before this, why they did not fire]
  Conclusion:   [classification value]

Real map evidence REQUIRED for land_use and is_critical_infrastructure.

OUTPUT FORMAT:
After the scratchpad, write a single JSON object matching Stage3Output schema.
"""
