STAGE4_PROMPT = """
You are producing the final impact assessment for a cellular base station outage.

TARGET USID: {target_usid}
SHUTDOWN: {shutdown_start} to {shutdown_end}

YOUR TASK — Stage 4: Final Integrated Assessment

You have received a structured handoff artifact from Stages 1, 2, and 3.
This is a context reset — you start fresh with only this handoff and the hot tier.

PROCESS:
1. Read the worst zone severity from Stage 3
2. Check each constraint rule C1–C5 explicitly in order
3. Determine final user_impact_level 1–4
4. Account for shutdown duration
5. Write the final conclusion for a senior RF engineer

FOR EACH CONSTRAINT, show this scratchpad:
  C[N] condition: [exact values from handoff] → fires: yes/no → [effect]

OUTPUT FORMAT:
After the scratchpad, write a single JSON object matching Stage4Output schema.
"""
