---
name: scratchpad_format
description: >
  Output discipline for all analysis agents. Defines the required scratchpad
  section that must precede the final JSON artifact. Ensures reasoning is
  traceable before any Write tool call is made.
---

# Scratchpad Format

## Required: Write scratchpad before artifact

Before calling the Write tool, output a scratchpad block in this format:

```
=== SCRATCHPAD ===

[Step N — <step name>]
<calculations, data readings, or observations>
<cite exact values from tool results or preprocessing_stats>

[Step N+1 — <step name>]
<next reasoning block>

[Verdict]
<state the verdict with the specific rule that matched>
<cite the input values that triggered the rule>

=== END SCRATCHPAD ===
```

## Rules

- One `[Step N]` block per skill step
- Every number cited must appear in a tool result or preprocessing_stats.json
- Verdict block must name the rule matched (e.g. "OVERLOADED — coverage_hole_fraction 0.28 > 0.20")
- Do not skip steps; write "no data — using default" if a step has no relevant input
- Scratchpad is not saved. Only the JSON artifact is saved via Write tool.

## Example

```
=== SCRATCHPAD ===

[Step 1 — Profile USIDs]
USID_20: dom_frac=0.31, rsrp_p50=-83 dBm → role=dominant-anchor, confidence=high
USID_27: dom_frac=0.18, rsrp_p50=-88 dBm → role=strong-supporting, confidence=high

[Step 2 — Load redistribution]
USID_27: absorption=0.41, handover=good, post_load=0.91, overload_risk=medium
USID_14: absorption=0.22, handover=partial, post_load=0.78, overload_risk=low
coverage_hole_fraction=0.07

[Verdict]
STRAINED — coverage_hole_fraction 0.07 is in range 0.05–0.20

=== END SCRATCHPAD ===
```
