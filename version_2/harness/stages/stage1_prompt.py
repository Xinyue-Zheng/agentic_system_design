STAGE1_PROMPT = """
You are analysing a cellular base station outage impact assessment.

TARGET USID: {target_usid}

YOUR TASK — Stage 1: Coverage and Load Redistribution Analysis

Analyse the coverage and load redistribution impact when {target_usid} shuts down.
You must produce:

1. For each USID in the data:
   - Dominance role classification (use thresholds from AGENTS.md hot tier)
   - Role confidence level
   - Dominant pixel fraction and RSRP p50

2. For each backup USID:
   - Absorption fraction of target area
   - Handover quality assessment
   - Post-outage load factor and overload risk
   - SINR regime impact note

3. Overall load redistribution verdict: adequate / strained / overloaded

4. Coverage hole fraction and assessment

MANDATORY SCRATCHPAD FORMAT:
Before writing any JSON, write a scratchpad for EVERY classification decision:

DECISION: [field name]
  Observation:  [exact value + field path from preprocessing data]
  Standard:     [exact threshold from AGENTS.md hot tier]
  Rule applied: [which rule fires, why]
  Rules skipped:[rules checked before this, why they did not match]
  Conclusion:   [the classification value]

OUTPUT FORMAT:
After the scratchpad, write a single JSON object matching the Stage1Output schema.
Field names must match exactly. Use hyphens not underscores in role enum values.
"""
