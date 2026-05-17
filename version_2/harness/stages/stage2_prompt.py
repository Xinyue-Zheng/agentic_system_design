STAGE2_PROMPT = """
You are analysing a cellular base station outage impact assessment.

TARGET USID: {target_usid}

YOUR TASK — Stage 2: Attribute and Configuration Analysis

Analyse the hardware and configuration profile of all USIDs involved.
You must produce:

1. For each USID:
   - Tower type (use height thresholds from hot tier)
   - Technology profile (lte_only / nsa_5g / sa_5g)
   - Capacity score (READ from preprocessing — do NOT recompute)
   - Active bands and cell counts

2. NSA 5G downgrade risk:
   - Is 5G flagged on target but absent on primary backup?
   - What fraction of users would downgrade?

3. Overall capacity verdict: adequate / marginal / insufficient

MANDATORY SCRATCHPAD FORMAT:
Before writing any JSON, write a scratchpad for EVERY classification:

DECISION: [field name]
  Observation:  [exact value + field path]
  Standard:     [exact threshold from hot tier]
  Rule applied: [which rule fires]
  Conclusion:   [the value]

OUTPUT FORMAT:
After the scratchpad, write a single JSON object matching the Stage2Output schema.
"""
