# Agent Reasoning Slide Notes

This document summarizes each agent in the outage impact assessment pipeline in
a slide-friendly format: what the agent does, what question it answers, what
evidence it uses, and where LLM reasoning adds value beyond hard-coded rules.

---

## 1. Context Planner

**Main role:** Convert a semi-structured outage ticket into a shared analysis
context and per-agent control flags for downstream agents.

**Question it answers:** What exactly is the outage scenario, and how should
each downstream agent specialize its analysis?

The Planner explicitly answers four planning questions:

- **Q1 - Sector state:** Which sectors are failed, degraded, active, or unknown?
  If the ticket explicitly names affected sectors, the Planner uses the ticket;
  otherwise it uses KPI history/timeseries to infer sector state.
- **Q2 - Peak overlap:** Does the outage overlap this site's recurring high
  demand hours? The Planner uses 60-day KPI history to identify station-specific
  peak hours.
- **Q3 - Geographic scope:** Is the geographic impact full-site, partial-sector,
  or minimal? This sets the geo scope for downstream spatial analysis.
- **Q4 - Time and area context:** Is this a weekday/weekend/holiday, what time
  of day is it, and what is the surrounding land-use profile if coordinates are
  available?

**How it answers:**

- Reads ticket fields such as outage type, affected USID, affected sectors,
  start/end time, and coordinates.
- Uses KPI history when needed to infer recurring peak hours.
- Uses sector state rules to decide whether sectors are failed, degraded, or
  active.
- Uses time and area context to set shared flags such as peak overlap, outage
  scope, and geographic focus.

**How flags control downstream agents:**

- `coverage_agent.flag` controls whether Coverage runs only base analysis or
  also loads directional sector analysis. `PARTIAL_SECTOR_FAILURE` and
  `FULL_SITE_FAILURE` trigger `coverage_directional_focus.md`.
- `kpi_agent.flag` controls which KPI time layer is loaded. Long duration
  outages trigger sustained hourly analysis; short peak-overlap outages trigger
  peak-hour analysis.
- `geo_agent.flag` tells Geo whether to focus on full-site coverage loss or
  partial affected zones. Geo then uses Coverage `per_zone` as the precise map
  target.
- `per_agent_context[*].priority_focus` and `constraint` tell each agent what to
  emphasize and what not to double-count, such as excluding active sectors in a
  partial outage.

**Reasoning value:** The Planner decides which data is needed and which data
should not be used. For example, if the ticket explicitly names affected
sectors, it should not over-query outage-window KPI just to rediscover them.
Its value is turning incomplete ticket context into both a consistent analysis
contract and a routing mechanism that controls which specialist skills are
loaded downstream.

---

## 2. Coverage Agent

**Main role:** Evaluate whether neighboring cells can provide usable RF signal
coverage for users affected by the outage.

**Question it answers:** If the affected USID or sectors go down, can users
still receive usable backup signal from neighbors?

**How it answers:**

- Reads preprocessing stats: RSRP percentiles, coverage hole fraction,
  absorption fraction, handover quality, SINR regime, and post-outage load
  factors.
- Reads RSRP/SINR images to describe spatial signal patterns.
- For partial outage, evaluates only failed/degraded sector directions, not
  active sectors.
- Produces `load_redistribution_verdict`: adequate, strained, or overloaded.
- Produces `key_findings_for_geo`: coverage holes, weak zones, and strong zones
  for Geo Agent.

**Reasoning value:** Numeric RF thresholds can be hard-coded, but the agent
adds spatial interpretation: whether weak signal is isolated or continuous,
where signal is strong/weak relative to the target boundary, and which RF
findings should be passed to Geo for real-world interpretation.

---

## 3. Coverage Directional Focus

**Main role:** Ground failed or degraded sectors into precise spatial zones.

**Question it answers:** Which sector directions are affected, and where are
those affected zones located on the map?

**How it answers:**

- Reads sector states from Planner context.
- Calls sector-level coverage pixel queries for failed/degraded sectors.
- Computes each affected sector's pixel count, bounding box, and centroid.
- Identifies primary backup USID, signal condition, SINR regime, and coverage
  hole presence per sector.
- Writes `per_zone`, keyed by sector ID.

**Reasoning value:** The important reasoning is sector-to-space grounding. The
agent converts abstract sector IDs like `USID_09_S2` into map-ready affected
footprints. This lets Geo analyze the actual user-impact area instead of a
generic tower-centered map.

---

## 4. KPI Agent

**Main role:** Forecast traffic-layer pressure on neighbors under a
counterfactual outage scenario.

**Question it answers:** From a throughput/KPI perspective, can neighbors carry
the traffic that the failed USID or sectors would have served?

**How it answers:**

- Uses only historical KPI data, not actual neighbor KPI during the outage
  window.
- Builds historical forecast candidates: same-hour mean, p75, p90,
  same-daytype mean, recent 14-day mean, and peak-hour mean when relevant.
- Selects a base-case and stress-case lost traffic forecast from those
  historical candidates.
- Applies coverage-derived absorption fractions to estimate each neighbor's
  counterfactual load.
- Compares base/stress new load to each neighbor's p90 reference to classify
  pressure.

**Reasoning value:** The agent does not invent throughput. Its reasoning is
anchored judgmental forecasting: choose the most appropriate historical analog,
explain why fixed factors are insufficient, produce base/stress cases, and
state forecast uncertainty.

---

## 5. KPI Peak-Hour Layer

**Main role:** Reassess short outages that overlap recurring peak demand hours.

**Question it answers:** If the outage is short but overlaps the highest-demand
hours, do neighbors fail specifically during the peak slice?

**How it answers:**

- Filters historical KPI to `peak_hours_within_window`.
- Builds peak-specific lost traffic candidates: peak mean, p75, p90,
  same-daytype peak mean, and recent peak mean.
- Selects peak base/stress forecasts.
- Computes neighbor peak loads and pressure classes.
- Produces `peak_hour_verdict`: manageable, elevated_risk, or critical.

**Reasoning value:** It prevents full-window averages from hiding short peak
pressure. The agent reasons about whether peak-specific analogs should replace
the broader base forecast for peak verdicts.

---

## 6. KPI Sustained Pressure Layer

**Main role:** Analyze long-duration outage pressure hour by hour.

**Question it answers:** Does neighbor absorption pressure persist, worsen, or
concentrate in peak hours over a long outage?

**How it answers:**

- Builds hourly lost traffic candidates for every outage hour.
- Selects hourly base/stress forecasts.
- Computes hourly neighbor load and worst-neighbor classification.
- Produces base and stress hourly distributions.
- Determines trend and `sustained_pressure_verdict`.
- Derives peak-hour verdict from hourly classifications when peak overlap is
  present.

**Reasoning value:** It changes the KPI question from one window-level forecast
to a time-trajectory assessment. The agent reasons about persistence, peak
concentration, and whether stress grows or remains stable.

---

## 7. Config / Attribute Agent

**Main role:** Translate static site attributes into scenario-specific
capability assessment.

**Question it answers:** Do neighbor hardware and technology attributes indicate
real ability to absorb displaced users in this outage scenario?

**How it answers:**

- Reads affected USID and neighbor attributes: tower height, 4G/5G cells, band
  portfolio, capacity score, and operational role.
- Builds deterministic anchors: tower type, technology profile, operational
  role, rule-based feasibility, and 5G downgrade flag.
- Interprets those anchors in context: partial/full outage, failed sectors,
  peak overlap, duration, and neighbor pool.
- Produces `attribute_capability_interpretation` per neighbor.
- Produces `scenario_capability_assessment` and downstream validation flags.

**Reasoning value:** The agent does not invent capacity. Its value is explaining
what static inventory means operationally. A feasible micro tower may need
Coverage verification; several marginal macro sites may still provide
distributed support; a 4G-only neighbor may preserve LTE service while causing
5G downgrade.

---

## 8. Geo Agent

**Main role:** Convert RF affected zones into real-world geographic and user
impact context.

**Question it answers:** What kind of place is affected, and how sensitive is
service continuity there?

**How it answers:**

- Reads Coverage `per_zone`, coverage holes, weak zones, and tower positions.
- Requests map imagery centered on affected sector centroids.
- Visually classifies land use: residential, commercial, hospital, school,
  forest, road, industrial, water, or uncertain.
- Derives user relevance and critical infrastructure flags from map evidence.
- Checks whether terrain features overlap RF holes or weak zones.
- Produces Geo self-flags: `terrain_attenuation_active` and
  `high_sensitivity_area`.

**Reasoning value:** This is image-plus-data reasoning. The agent links RF
affected zones to map evidence, identifies land-use/user sensitivity, and
determines whether geography should modify severity, confidence, or
recommended action.

---

## 9. Assessment Agent

**Main role:** Synthesize specialist outputs into final severity, confidence,
and recommended action.

**Question it answers:** Given RF coverage, KPI pressure, site attributes, and
geographic sensitivity, what is the final operational severity?

**How it answers:**

- Reads Coverage, KPI, Config/Attribute, and Geo artifacts.
- Applies P1/P2/P3 severity rules.
- Applies geo escalation override when high-sensitivity areas are present.
- Appends recommended-action modifiers such as 5G downgrade coordination,
  sustained pressure escalation, or terrain warnings.
- Writes an executive summary and confidence reasons.

**Reasoning value:** The agent reasons across conflicts. For example, Coverage
may be adequate while KPI reports high pressure. Assessment explains whether
that is a true contradiction, a layer difference, or an uncertainty source, then
sets severity and confidence accordingly.

---

## 10. Per-Agent Verifier

**Main role:** Audit each agent immediately after it runs.

**Question it answers:** Is this individual agent's artifact internally
consistent and grounded in the provided context?

**How it answers:**

- Runs Type A checks: schema, required fields, exact rule application.
- Runs Type B checks: assumption-context contradiction detection.
- Checks whether declared assumptions contradict shared context, time
  background, or area profile.
- Emits warnings and flags for Cross-Agent Verifier.

**Reasoning value:** The verifier is constrained. It does not re-analyze the
network or replace the agent's conclusion. Its LLM reasoning is limited to
detecting whether an explicit assumption conflicts with explicit scenario
facts.

---

## 11. Cross-Agent Verifier

**Main role:** Check consistency across all specialist agents and decide pass,
rerun, or HITL.

**Question it answers:** Do the agent outputs agree across layers, and if not,
is the disagreement acceptable, retryable, or requiring human review?

**How it answers:**

- Compares Coverage vs KPI for signal-capacity conflicts.
- Compares Coverage vs Geo for terrain or unexplained holes.
- Compares KPI vs Config for traffic pressure vs hardware capability.
- Checks Geo vs Assessment for missed escalation.
- Checks Assessment internal severity consistency.
- Decides `pass`, `rerun`, or `hitl`.

**Reasoning value:** It explicitly models cross-layer disagreements instead of
hiding them. A major contradiction after retry becomes HITL rather than a forced
automated answer.

---

## 12. Reflector

**Main role:** Convert each completed run into persistent memory.

**Question it answers:** What did this run teach us about recurring patterns,
confidence degradation, and prediction accuracy?

**How it answers:**

- Reads Cross-Agent Verifier output and existing memory store.
- Records discrepancies, HITL triggers, planner quality, and ground truth
  accuracy when available.
- Summarizes concrete lessons from the run.
- Updates memory summary across all runs.

**Reasoning value:** Reflector does not re-analyze the outage. Its value is
structured learning across runs: identifying stable minor discrepancies,
confirmed HITL patterns, and whether severity predictions match resolved
tickets.

---

## Slide Summary

The system separates deterministic anchors from LLM reasoning:

- Deterministic anchors: KPI statistics, RF thresholds, capacity scores,
  feasibility rules, severity rule checks.
- LLM reasoning: choosing forecast analogs, interpreting RF/image patterns,
  grounding sectors into geography, translating site attributes into scenario
  capability, explaining cross-agent conflicts, and propagating uncertainty.

The agents communicate through structured artifacts, not hidden intermediate
state. Cross-agent checks and validation flags are handoffs for Assessment and
Verifier, not real-time conversations between parallel agents.
