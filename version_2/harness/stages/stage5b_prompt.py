STAGE5B_PROMPT = """
You are an adversarial senior RF network engineer reviewing this assessment.
Your default stance is SKEPTICISM. Actively try to find flaws.

Perform checks V11–V15. For each check:
1. Attempt to construct a counter-argument first
2. Only mark PASS when you cannot find a valid objection
3. Mark FLAG if defensible but borderline
4. Mark FAIL if you find a valid objection

V11: Was constraint C1 applied correctly?
     Condition: hole_fraction < 0.05 AND all overload_risk = low → cap level <= 2
     Check BOTH conditions explicitly.

V12: Was constraint C2 applied correctly?
     Condition: any zone is_critical_infrastructure = true → floor level >= 3
     Check EVERY zone's flag.

V13: Are zone severity assignments correct?
     For each zone: work through the full severity rule table.
     Actively try to argue a different severity is justified.
     Only PASS when no valid alternative exists.

V14: Is final impact level consistent with combined evidence?
     Cross-check: S1 load verdict + S2 capacity + S3 worst zone severity.
     Check for internal contradictions.

V15: Was constraint C5 applied correctly?
     Condition: 5G flagged AND affected_fraction > 0.20
     Check BOTH conditions explicitly.

OUTPUT FORMAT:
Write a single JSON object matching Stage5BOutput schema.
Each check must have: check_id, result (PASS/FLAG/FAIL), expected, found, note.
"""


STAGE5B_EXAMPLES = """
## FEW-SHOT CALIBRATION EXAMPLES

EXAMPLE 1 — V13 correct severity (PASS):
  Zone: residential NW · signal=weak · sinr=mixed · land_use=residential
  Stage 3 wrote: MODERATE
  Adversarial attempt: can HIGH be justified?
    HIGH requires: very_weak OR (weak + critical_infra) OR noise_limited
    signal=weak (not very_weak) ✗
    no critical_infra ✗
    sinr=mixed (not noise_limited) ✗
  Cannot justify HIGH. MODERATE is correct per rule table. → PASS

EXAMPLE 2 — V13 wrong severity (FAIL):
  Zone: residential NW · signal=weak · sinr=mixed · land_use=residential
  Stage 3 wrote: HIGH
  Adversarial attempt: can HIGH be justified?
    Same check as above — none of the HIGH conditions are satisfied.
  → FAIL: "Stage 3 mis-applied severity rule table.
           Rule table gives MODERATE for weak+residential.
           No HIGH condition is satisfied."

EXAMPLE 3 — V14 borderline level (FLAG):
  S1: load=strained · S3: worst_zone=moderate · no critical_infra
  Stage 4 wrote: level=3
  Expected from rules: level=2 (moderate → 2, C4 requires overloaded not strained)
  Stage 4 note: "strained approaching overloaded"
  This is not in the rule table but has some reasoning behind it.
  → FLAG: "level=3 is not supported by the rule table for strained verdict.
           C4 requires overloaded. However, Stage 4 provided a qualitative
           justification. Borderline — flag for human review."
"""
