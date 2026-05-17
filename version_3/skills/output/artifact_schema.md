---
name: artifact_schema
description: >
  Cross-agent artifact conventions. Defines shared field enumerations,
  uncertainty schema, and Write tool usage rules that apply to all agent
  artifacts. Load alongside each agent's own skill file.
---

# Artifact Schema Conventions

## Shared enumerations

**uncertainty.level**
- `"low"` — all inputs present; values consistent with each other
- `"medium"` — one input missing or one mild inconsistency
- `"high"` — multiple inputs missing, tool error, or major inconsistency

**signal_condition**
- `"strong"`    — rsrp_p50 > −80 dBm
- `"moderate"`  — rsrp_p50 −90 to −80 dBm
- `"weak"`      — rsrp_p50 −100 to −90 dBm
- `"very_weak"` — rsrp_p50 < −100 dBm OR no backup signal

**user_relevance** (geo_agent only)
- `"critical"` — hospital, school
- `"high"`     — residential, commercial
- `"medium"`   — road (major highway or expressway)
- `"low"`      — industrial, forest, water, uncertain

## Write tool usage

- Call Write exactly once per agent run, at the very end
- File path must be `artifacts/{run_id}/{agent_name}_artifact.json`
  where `{run_id}` and `{agent_name}` come from Run Parameters
- Content must be valid JSON — no trailing commas, no comments
- Do not write partial artifacts; complete all steps before writing

## reasoning_log convention

All agents must include a reasoning_log array in their artifact.
Each entry must follow this schema:

{
  "step": "string — skill step name",
  "data_used": "string — exact values read from tools or preprocessing",
  "assumption": "string or null — any approximation made in this step",
  "result": "string — what was concluded from the data"
}

Rules:
- One entry per major skill step
- data_used must quote exact numeric values, not paraphrase
- assumption must be non-null whenever a proxy or approximation
  is used (e.g. absorption_fraction as traffic proxy)
- Per-Agent Verifier will check that result follows from data_used
  under the stated assumption

---

## Null handling

- Use JSON `null` (not `"null"` string, not `""`) for absent optional fields
- Fields that are always null in base and populated by an extension skill
  should be written as `null` in the base artifact

## Numeric precision

- Fractions: 2 decimal places (e.g. `0.23`)
- dBm values: 1 decimal place (e.g. `-87.4`)
- Lat/lon: 6 decimal places (e.g. `33.012345`)
- Load factors: 2 decimal places (e.g. `1.04`)

## Verification before Write

Before calling Write, confirm:
1. All verdict fields are populated with allowed enum values
2. `uncertainty.level` reflects actual data completeness
3. No field references data not present in tool results or preprocessing
4. `run_id` in file path matches Run Parameters exactly
