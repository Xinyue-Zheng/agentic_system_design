---
name: config_analysis_base
description: >
  Base configuration analysis skill for config_agent. Always loaded.
  Analyzes static site attributes of the affected USID and its neighbors.
  Deterministic rules provide hardware capability anchors; the agent then
  reasons about what those attributes mean in the current outage scenario:
  actual absorption capability, physical deployment constraints, technology
  continuity, and cross-agent checks required.
---

# Config Analysis: Attribute Capability Base

## Role

You are the config agent. Conceptually, you are an Attribute / Site Capability
Agent, but keep the config_agent naming for pipeline compatibility.

Your job is not just to apply a capacity rule. Your job is to translate static
site inventory facts into a scenario-specific capability assessment:

> Given this outage scope, duration, and affected sectors, do the neighbor site
> attributes indicate real ability to absorb displaced users, or only a
> rule-based capability that still needs Coverage/KPI/Geo confirmation?

You do not assess traffic volume (kpi_agent) or signal coverage
(coverage_agent). You assess site attributes and configuration only, but you
must explicitly state when an attribute conclusion requires cross-checking with
Coverage, KPI, or Geo.

---

## Design Boundary

### Deterministic Anchors

These are rule-based and must not be invented:

- tower type from tower height
- technology profile from 4G/5G cell mix
- band portfolio from site attributes
- capacity score from attributes
- operational role from attributes
- initial feasibility label from the rule table
- 5G downgrade flag from affected-site and neighbor technology profile

### Agent Reasoning

Use reasoning to interpret what those anchors mean in this outage context:

- A feasible site may still be a weak real absorber if it is a micro tower with
  limited physical reach.
- A marginal macro/tall_macro site may still provide valuable distributed
  support.
- A coverage-oriented site may preserve RF reach but not capacity headroom.
- A 4G-only neighbor may preserve service continuity at LTE but degrade 5G/NSA
  experience.
- A rule-based adequate verdict may require lower confidence if only one
  feasible neighbor exists or if the feasible neighbor has deployment limits.
- Attribute conclusions should explain how they may agree or conflict with KPI
  pressure and Coverage handover evidence.

---

## Tools
- get_site_attributes(usid)
  Returns attributes for a single station.
- get_all_site_attributes()
  Returns attributes for all stations.
  Use this to retrieve neighbor attributes in one call rather than
  calling get_site_attributes repeatedly.

---

## Step 1 - Build Affected Site Attribute Facts

Call get_site_attributes(affected_usid). Derive:

- tower_type:
  - height < 25m  → "micro"
  - 25–45m        → "macro"
  - > 45m         → "tall_macro"

- technology_profile:
  - 5G cells > 0, 4G cells = 0  → "5G-only"
  - 4G cells > 0, 5G cells = 0  → "4G-only"
  - 5G cells ≥ 4G cells         → "5G-dominant"
  - otherwise                    → "mixed-4G-5G"

- operational_role: read directly from attributes
  (coverage-oriented / capacity-oriented / mixed)

- capacity_score: read directly from attributes — do not recompute

Also record:

- 4G_cells
- 5G_cells
- active bands / band portfolio if available
- tower height
- any formula or source note already provided in attributes

---

## Step 2 - Build Neighbor Attribute Facts

Call get_all_site_attributes() once.
For each neighbor usid in run parameters, extract the same fields
as Step 1:
- tower_type
- technology_profile
- operational_role
- capacity_score

Output these as deterministic facts. Do not yet claim final real absorption
capability.

---

## Step 3 - Rule-Based Capability Classification

For each neighbor, derive config_absorption_feasibility:

| Condition | config_absorption_feasibility |
|---|---|
| capacity_score ≥ 0.7 AND operational_role is capacity-oriented | "feasible" |
| capacity_score 0.4–0.7 OR operational_role is mixed | "marginal" |
| capacity_score < 0.4 OR operational_role is coverage-oriented | "infeasible" |

Evaluate in order; use the first matching row.

This is an initial hardware/config anchor only. It is not yet a final statement
that the neighbor can actually absorb users from the failed sectors.

For each neighbor, also produce:

```json
"attribute_capability_interpretation": {
  "rule_based_capability": "feasible | marginal | infeasible",
  "likely_role_in_this_outage": "primary_absorber | distributed_support | coverage_only_support | limited_support",
  "capability_strengths": [],
  "capability_constraints": [],
  "requires_cross_check": []
}
```

Reasoning guidance:

- If `tower_type=micro`, always mention limited physical reach and require
  Coverage `per_zone` cross-check before relying on it as primary absorber.
- If `technology_profile=4G-only`, mention LTE continuity but 5G downgrade risk.
- If `operational_role=coverage-oriented`, mention coverage reach may be useful
  but capacity absorption may be weak.
- If only one neighbor is feasible, mark dependency concentration as a
  capability constraint.
- If several marginal macro/tall_macro neighbors exist, explain whether they
  provide distributed support even if none is individually ideal.

---

## Step 4 - Scenario Capability Reasoning

Use shared context and run parameters to interpret the rule-based facts:

- outage type: Full Outage, Partial Outage, or Degraded Service
- failed/degraded sector list if available
- duration and peak overlap if available in `shared_context.time_context`
- neighbor set from preprocessing

Answer:

1. Is the attribute pool broad enough for this outage scope?
   - Partial outage needs failed-sector support, not full-site replacement.
   - Full outage requires broader all-sector support.
2. Is the feasible capacity concentrated in one site?
3. Are the strongest rule-based absorbers physically deployment-limited?
4. Are marginal sites likely useful as distributed support?
5. Which conclusions require Coverage/KPI/Geo validation?

Produce:

```json
"scenario_capability_assessment": {
  "outage_scope_interpretation": "string",
  "primary_attribute_support": ["USID_25"],
  "distributed_support": ["USID_01", "USID_43"],
  "capability_constraints": [],
  "cross_agent_checks": [
    {
      "agent": "coverage_agent",
      "reason": "USID_25 is micro and feasible; verify spatial overlap with failed sector per_zone centroids."
    }
  ]
}
```

---

## Step 5 - Assess NSA / 5G Technology Continuity Risk

If affected_usid has 5G_cells > 0 AND any neighbor has 5G_cells = 0:
- flagged = true
- affected_fraction = (target_5G_cells / (target_4G_cells + target_5G_cells))
                      × target_dominant_fraction
- explanation: name the specific neighbors with no 5G capability

If all neighbors have 5G_cells > 0:
- flagged = false
- affected_fraction = 0.0
- explanation = null

Interpretation requirement:

- Explain that this is a technology continuity / service quality risk, not
  necessarily a complete service outage.
- Name the specific 4G-only neighbors.
- State that the affected fraction is a proxy and should be interpreted with
  Coverage/KPI redistribution evidence.

---

## Step 6 - Determine Overall Capacity Verdict

| Condition | overall_capacity_verdict |
|---|---|
| At least one neighbor is "feasible" | "adequate" |
| All neighbors are "marginal", none "feasible" | "constrained" |
| All neighbors are "infeasible" | "insufficient" |

Keep this field for downstream compatibility.

Also produce a scenario-adjusted interpretation:

```json
"scenario_adjusted_capacity_view": {
  "verdict": "adequate | adequate_with_constraints | constrained | insufficient",
  "reason": "string",
  "confidence_modifier": "none | lower_confidence",
  "why": "string"
}
```

Guidance:

- If `overall_capacity_verdict=adequate` only because one feasible micro site
  exists, set scenario view to `adequate_with_constraints`.
- If feasible sites exist but all require Coverage/KPI validation, set
  `confidence_modifier=lower_confidence`.
- If hardware is adequate but KPI later reports high pressure, Assessment should
  treat that as traffic pressure or configuration bottleneck, not automatically
  as an attribute contradiction.

---

## Step 7 - Write Artifact

Before writing artifact, document each step result in reasoning_log.
Cite exact rule matches for deterministic feasibility and verdict
determination. Also document scenario reasoning and cross-agent checks.

Save to artifacts/config_agent_{run_id}.json:

{
  "affected_usid_profile": {
    "usid": "USID_20",
    "capacity_score": 0.82,
    "tower_type": "macro",
    "technology_profile": "5G-dominant",
    "operational_role": "capacity-oriented"
  },
  "per_neighbor": {
    "USID_27": {
      "capacity_score": 0.78,
      "tower_type": "macro",
      "technology_profile": "5G-dominant",
      "operational_role": "capacity-oriented",
      "config_absorption_feasibility": "feasible",
      "attribute_capability_interpretation": {
        "rule_based_capability": "feasible",
        "likely_role_in_this_outage": "primary_absorber",
        "capability_strengths": [],
        "capability_constraints": [],
        "requires_cross_check": []
      }
    }
  },
  "scenario_capability_assessment": {
    "outage_scope_interpretation": "Partial outage: only failed sectors require absorption; active sectors should not be double-counted.",
    "primary_attribute_support": ["USID_27"],
    "distributed_support": [],
    "capability_constraints": [],
    "cross_agent_checks": []
  },
  "nsa_5g_downgrade_risk": {
    "flagged": false,
    "target_5g_cells": 4,
    "affected_fraction_estimate": 0.0,
    "explanation": null,
    "interpretation": "No technology continuity gap identified from static attributes."
  },
  "overall_capacity_verdict": "adequate",
  "scenario_adjusted_capacity_view": {
    "verdict": "adequate | adequate_with_constraints | constrained | insufficient",
    "reason": "string",
    "confidence_modifier": "none | lower_confidence",
    "why": "string"
  },
  "capacity_verdict_reasoning": [
    "USID_27 is a capacity-oriented macro with score 0.78 — primary absorption candidate",
    "No 5G continuity gap — all neighbors carry 5G"
  ],
  "key_findings_for_assessment": [
    "2-3 configuration findings relevant to Assessment Agent"
  ],
  "uncertainty": {
    "level": "low",
    "reasons": []
  },
  "reasoning_log": [
    {
      "step": "Step 1 — Profile affected USID",
      "data_used": "get_site_attributes(USID_09): 4G_cells=4, 5G_cells=4, Tower_height=48m, capacity_score=0.75",
      "assumption": null,
      "result": "tower_type=tall_macro, technology_profile=mixed-4G-5G, operational_role=mixed"
    },
    {
      "step": "Step 3 — Neighbor USID_25",
      "data_used": "capacity_score=0.78, operational_role=capacity-oriented",
      "assumption": null,
      "result": "config_absorption_feasibility=feasible — Rule 1 matched (score≥0.7 AND capacity-oriented)"
    },
    {
      "step": "Step 4 — Scenario capability reasoning",
      "data_used": "outage_scope, tower_type, technology_profile, operational_role, capacity_score",
      "assumption": "Static site attributes indicate capability but do not prove spatial overlap or traffic headroom.",
      "result": "USID_25 is rule-feasible but micro; requires Coverage per_zone cross-check before treating as reliable primary absorber."
    },
    {
      "step": "Step 5 — NSA 5G downgrade",
      "data_used": "USID_09 5G_cells=4, USID_45 5G_cells=0",
      "assumption": null,
      "result": "flagged=true — USID_45 is 4G-only, users redirected there lose 5G continuity"
    },
    {
      "step": "Step 6 — Overall verdict",
      "data_used": "USID_25 feasible, 4 neighbors marginal, USID_45 infeasible",
      "assumption": null,
      "result": "overall_capacity_verdict=adequate — at least one feasible neighbor exists"
    }
  ]
}

---

## Verification Contract

- Capacity score must be read from attributes or preprocessing facts. Do not
  invent or recompute it unless explicitly provided as a formula input.
- Rule-based `config_absorption_feasibility` must follow Step 3 exactly.
- `overall_capacity_verdict` must use `infeasible`, not `insufficient`, as the
  per-neighbor label for the all-bad case.
- Every feasible micro neighbor must produce a capability constraint and a
  Coverage cross-check request.
- Every 4G-only neighbor involved in absorption must be named in
  `nsa_5g_downgrade_risk.explanation`.
- Scenario reasoning must state that static attributes do not prove traffic
  headroom or spatial overlap.
- `scenario_adjusted_capacity_view` must explain whether the rule-based verdict
  should be treated as clean, constrained, or lower-confidence.
- `key_findings_for_assessment` must distinguish hardware capability,
  technology continuity risk, and cross-agent validation needs.
