"""
pipeline.py — the harness orchestrator

The harness provides:
  - Process scheduler     (asyncio.gather for parallel stages)
  - Memory protection     (Pydantic gates between every stage)
  - Fault handler         (stops on logic failures, retries transient ones)
  - Self-correction       (feeds errors back to agent for one retry)
  - System call interface (scratchpad format enforced on every call)
  - I/O driver            (MCP query interface — no hard-coded field paths)
  - Kernel rules          (playbook.json hot tier injected into every call)
  - Adaptive kernel       (Stage 6 updates warm tier after verified PASS)
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional
from pydantic import ValidationError

from harness.core.claude_runner import run_agent, run_correction, PIPELINE_MODE
from harness.schemas.stage1 import Stage1Output
from harness.core.agents_md import load_hot_tier, load_warm_tier
from harness.core.mcp_log import MCPResourceLog
from harness.core.deterministic_checks import run_stage5a
from harness.core.playbook import PlaybookManager


# ─────────────────────────────────────────────────────────────
# HARNESS COMPONENT: Pydantic gate with self-correction
# ─────────────────────────────────────────────────────────────

def pydantic_gate_with_correction(
    stage_id: str,
    output_path: Path,
    schema_class,
    system: str,
    user: str,
    max_correction_attempts: int = 2,
):
    """
    Validates output against schema. If hallucination caused a schema
    violation, feeds the error back to the agent for self-correction.

    Auto-corrects: wrong enum values, wrong types, missing fields
                   (these are likely hallucinations)

    Hard stops after max_correction_attempts: if it keeps failing,
    the problem is in the prompt or schema, not a hallucination.
    """
    for attempt in range(1, max_correction_attempts + 2):
        raw = json.loads(output_path.read_text())
        try:
            validated = schema_class(**raw)
            if attempt > 1:
                print(f"  [Gate {stage_id}] PASS after {attempt-1} correction(s)")
            else:
                print(f"  [Gate {stage_id}] PASS")
            return validated
        except ValidationError as e:
            if attempt > max_correction_attempts:
                raise RuntimeError(
                    f"[Gate {stage_id}] FAIL after {max_correction_attempts} corrections.\n"
                    f"This is likely a prompt or schema issue, not hallucination.\n{e}"
                )

            print(f"  [Gate {stage_id}] schema error — sending correction to agent "
                  f"(attempt {attempt}/{max_correction_attempts})")

            corrected = run_correction(
                stage_id=stage_id,
                system=system,
                original_user=user,
                original_response=output_path.read_text(),
                correction_message=f"""
Your output failed schema validation:

{e}

Fix ONLY the fields listed above. Keep all correct fields unchanged.
Write the corrected complete JSON object only — no scratchpad needed.
""",
                output_path=output_path,
            )
            output_path.write_text(corrected)


# ─────────────────────────────────────────────────────────────
# HARNESS COMPONENT: Stage runner with transient retry
# ─────────────────────────────────────────────────────────────

def run_stage(
    stage_id: str,
    stage_prompt: str,
    hot_tier: str,
    warm_tier: str,
    data_context: str,
    output_path: Path,
    model: str = "claude-opus-4-5",
    max_retries: int = 3,
    client=None,  # unused in claudecode mode, kept for api mode compat
) -> tuple:
    """
    Runs one stage. Returns (json_str, system, user) so the caller
    can pass system+user to pydantic_gate_with_correction if needed.

    Auto-retries transient failures (API errors, network, bad JSON).
    Does NOT retry logic failures — those go to the gate for correction.
    """
    system = f"""
{hot_tier}

## Lessons from previous runs (warm tier for {stage_id})
{warm_tier if warm_tier else "(no lessons yet — first run)"}

## MANDATORY REASONING FORMAT
Before writing any JSON output, you MUST write a scratchpad
for every classification decision:

DECISION: [field name]
  Observation:  [exact value + source field path]
  Standard:     [exact threshold from hot tier]
  Rule applied: [rule ID and text]
  Rules skipped:[rules checked before this, why they did not fire]
  Conclusion:   [value] → [implication]

Write scratchpad first. Then write the JSON output.
"""

    user = f"""
{stage_prompt}

## DATA FOR THIS STAGE
{data_context}

Write your scratchpad reasoning first, then the JSON output.
"""

    return run_agent(
        stage_id=stage_id,
        system=system,
        user=user,
        output_path=output_path,
        model=model,
        max_retries=max_retries,
    )


def _extract_json(text: str, stage_id: str) -> str:
    import re
    matches = list(re.finditer(r'\{[\s\S]*\}', text))
    if not matches:
        raise RuntimeError(f"[{stage_id}] No JSON found in response.")
    json_str = matches[-1].group(0)
    json.loads(json_str)
    return json_str


# ─────────────────────────────────────────────────────────────
# HARNESS COMPONENT: Stage 5A with auto-correction
# ─────────────────────────────────────────────────────────────

def run_stage5a_with_correction(
    hot_tier, mcp_log, preprocessing_path,
    result_dir, target_usid, model,
    all_stage_systems, all_stage_users,
    max_correction_attempts=1,
):
    """
    Runs Stage 5A. If it fails, identifies the failing stage,
    feeds the specific error back to that agent for correction,
    then re-runs Stage 5A once more.

    max_correction_attempts=1 because:
    - If the agent self-corrects on the first try: hallucination, fixed.
    - If it fails again: structural prompt/schema issue, needs human.
    """
    for attempt in range(1, max_correction_attempts + 2):
        try:
            result = run_stage5a(
                preprocessing_path=preprocessing_path,
                result_dir=result_dir,
                target_usid=target_usid,
                mcp_log=mcp_log,
            )

            if not result["critical_failures"]:
                if attempt > 1:
                    print(f"  [Stage 5A] PASS after correction")
                return result

            if attempt > max_correction_attempts:
                print(f"\n[Stage 5A] FAIL after correction attempt — needs human review")
                return result

            # Feed failure back to the agent that caused it
            print(f"\n  [Stage 5A] failures found — sending corrections to agents...")

            for failure in result["critical_failures"]:
                # Determine which stage caused this failure
                failing_stage = _identify_failing_stage(failure["check_id"])
                if failing_stage not in all_stage_systems:
                    continue

                stage_output_path = _get_stage_output_path(
                    result_dir, target_usid, failing_stage)
                if not stage_output_path.exists():
                    continue

                print(f"  [Stage 5A] correcting {failing_stage} for {failure['check_id']}...")
                corrected = run_correction(
                    stage_id=failing_stage,
                    system=all_stage_systems[failing_stage],
                    original_user=all_stage_users[failing_stage],
                    original_response=stage_output_path.read_text(),
                    correction_message=f"""
Stage 5A numeric verification found an error in your output:

Check: {failure['check_id']}
Expected: {failure['expected']}
Found:    {failure['found']}
Note:     {failure.get('note', '')}

The value you cited does not match the preprocessing ground truth.
Read the correct value from the data and fix this field.
Return the complete corrected JSON object only.
""",
                    output_path=stage_output_path,
                )
                stage_output_path.write_text(corrected)
                print(f"  [Stage 5A] {failing_stage} output corrected")

        except RuntimeError as e:
            if attempt > max_correction_attempts:
                raise
            print(f"  [Stage 5A] error: {e} — attempting correction...")

    return result


def _identify_failing_stage(check_id: str) -> str:
    """Maps Stage 5A check IDs to the stage that produced them."""
    stage1_checks = {"V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"}
    stage2_checks = {"V9", "V10"}
    if check_id in stage1_checks:
        return "stage1"
    if check_id in stage2_checks:
        return "stage2"
    return "stage1"


def _get_stage_output_path(result_dir: Path, target_usid: str, stage_id: str) -> Path:
    paths = {
        "stage1": result_dir / "stage1_coverage_load.json",
        "stage2": result_dir / "stage2_attribute_config.json",
        "stage3": result_dir / "stage3_geographic.json",
        "stage4": result_dir / f"stage4_final_{target_usid}.json",
    }
    return paths.get(stage_id, result_dir / f"{stage_id}.json")


# ─────────────────────────────────────────────────────────────
# HARNESS COMPONENT: Stage 5B with auto-correction
# ─────────────────────────────────────────────────────────────

def run_stage5b_with_correction(
    s5b_system, all_outputs, hot_tier,
    result_dir, target_usid, model,
    all_stage_systems, all_stage_users,
    max_correction_attempts=1,
):
    """
    Runs Stage 5B. If it fails, feeds the specific reasoning error
    back to the failing stage, lets it regenerate, then re-runs 5B.
    """
    from harness.stages.stage5b_prompt import STAGE5B_PROMPT

    for attempt in range(1, max_correction_attempts + 2):
        s5b_json, _, _ = run_agent(
            stage_id="Stage5B",
            system=s5b_system,
            user=STAGE5B_PROMPT + "\n\n" + json.dumps(all_outputs, indent=2),
            output_path=result_dir / "stage5_verification.json",
            model=model,
        )
        s5b_raw = s5b_json
        (result_dir / "stage5_verification.json").write_text(s5b_raw)
        s5b_result = json.loads(s5b_raw)
        overall = s5b_result["verification_summary"]["overall_result"]

        if overall != "FAIL":
            if attempt > 1:
                print(f"  [Stage 5B] {overall} after correction")
            return s5b_result

        if attempt > max_correction_attempts:
            print(f"\n  [Stage 5B] FAIL after correction — needs human review")
            return s5b_result

        # Find failed checks and which stages they implicate
        failed_checks = [c for c in s5b_result["checks"] if c["result"] == "FAIL"]
        print(f"\n  [Stage 5B] {len(failed_checks)} check(s) failed — sending corrections...")

        for check in failed_checks:
            failing_stage = _identify_stage5b_failing_stage(check["check_id"])
            if failing_stage not in all_stage_systems:
                continue

            stage_output_path = _get_stage_output_path(
                result_dir, target_usid, failing_stage)
            if not stage_output_path.exists():
                continue

            print(f"  [Stage 5B] correcting {failing_stage} for {check['check_id']}...")
            corrected = run_correction(
                stage_id=failing_stage,
                system=all_stage_systems[failing_stage],
                original_user=all_stage_users[failing_stage],
                original_response=stage_output_path.read_text(),
                correction_message=f"""
The adversarial evaluator (Stage 5B) found a reasoning error:

Check: {check['check_id']}
Expected: {check['expected']}
Found:    {check['found']}
Note:     {check['note']}

Review your reasoning for this specific decision.
Apply the correct rule from the hot tier rules.
Return the complete corrected JSON object only.
""",
                output_path=stage_output_path,
            )
            stage_output_path.write_text(corrected)

            # Update all_outputs for the next 5B attempt
            all_outputs[failing_stage] = json.loads(corrected)

    return s5b_result


def _identify_stage5b_failing_stage(check_id: str) -> str:
    """Maps Stage 5B check IDs to the stage that produced them."""
    stage4_checks = {"V11", "V12", "V14", "V15"}
    stage3_checks = {"V13"}
    if check_id in stage4_checks:
        return "stage4"
    if check_id in stage3_checks:
        return "stage3"
    return "stage4"


# ─────────────────────────────────────────────────────────────
# HARNESS COMPONENT: Parallel Stage 1 + Stage 2
# ─────────────────────────────────────────────────────────────

async def run_stages_parallel(
    target_usid, result_dir,
    hot_tier, mcp_log, model,
) -> dict:
    """
    Runs Stage 1 and Stage 2 in parallel.
    Returns system+user for each stage (needed for gate correction).
    """
    warm_s1 = load_warm_tier("stage1")
    warm_s2 = load_warm_tier("stage2")

    # ── MCP queries — agents describe what they need ──────────
    # Stage 1 queries for signal and load data
    s1_data = mcp_log.query_resource(
        "preprocessing_stats.json",
        query="coverage summary signal statistics and load redistribution per backup",
        reader="stage1-agent",
    )
    # Stage 2 queries for capacity and attribute data
    s2_data = mcp_log.query_resource(
        "preprocessing_stats.json",
        query="capacity summary tower attributes and technology profile",
        reader="stage2-agent",
    )

    from harness.stages.stage1_prompt import STAGE1_PROMPT
    from harness.stages.stage2_prompt import STAGE2_PROMPT

    print("\n[Scheduler] Stage 1 + Stage 2 running in parallel...")
    loop = asyncio.get_event_loop()

    s1_task = loop.run_in_executor(None, run_stage,
        "Stage1",
        STAGE1_PROMPT.format(target_usid=target_usid),
        hot_tier, warm_s1,
        json.dumps(s1_data, indent=2),
        result_dir / "stage1_coverage_load.json",
        model,
    )
    s2_task = loop.run_in_executor(None, run_stage,
        "Stage2",
        STAGE2_PROMPT.format(target_usid=target_usid),
        hot_tier, warm_s2,
        json.dumps(s2_data, indent=2),
        result_dir / "stage2_attribute_config.json",
        model,
    )

    (s1_raw, s1_system, s1_user), (s2_raw, s2_system, s2_user) = \
        await asyncio.gather(s1_task, s2_task)

    print("[Scheduler] Stage 1 + Stage 2 complete")
    return {
        "stage1": {"system": s1_system, "user": s1_user},
        "stage2": {"system": s2_system, "user": s2_user},
    }


# ─────────────────────────────────────────────────────────────
# HARNESS COMPONENT: Context reset handoff for Stage 4
# ─────────────────────────────────────────────────────────────

def build_stage4_handoff(mcp_log: MCPResourceLog, target_usid: str) -> dict:
    """
    Builds Stage 4 handoff artifact by querying MCP for what Stage 4 needs.
    No hard-coded field paths — MCP extracts the relevant content.
    """
    s1_summary = mcp_log.query_resource(
        "stage1",
        query="load redistribution verdict coverage hole fraction per backup overload risks",
        reader="stage4-handoff",
    )
    s2_summary = mcp_log.query_resource(
        "stage2",
        query="capacity verdict NSA 5G downgrade risk findings for stage4",
        reader="stage4-handoff",
    )
    s3_summary = mcp_log.query_resource(
        "stage3",
        query="worst zone severity critical infrastructure impact zones geographic assessment",
        reader="stage4-handoff",
    )
    s1_findings = mcp_log.query_resource(
        "stage1", query="key findings", reader="stage4-handoff")
    s3_findings = mcp_log.query_resource(
        "stage3", query="key findings", reader="stage4-handoff")

    return {
        "from_stage1": s1_summary,
        "from_stage2": s2_summary,
        "from_stage3": s3_summary,
        "key_findings": (
            s1_findings.get("key_findings", []) +
            s2_summary.get("key_findings_for_stage4", []) +
            s3_findings.get("key_findings", [])
        ),
    }


# ─────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────

async def run_pipeline(
    target_usid: str,
    shutdown_start: str,
    shutdown_end: str,
    preprocessing_path: Path,
    result_dir: Path,
    start_from_stage: int = 1,
    model: str = "claude-opus-4-5",
):
    print(f"\n{'='*60}")
    print(f" USID Outage Impact Assessment — Harness v2.0")
    print(f" Target:   {target_usid}")
    print(f" Shutdown: {shutdown_start} -> {shutdown_end}")
    print(f" Model:    {model}")
    print(f"{'='*60}\n")

    result_dir.mkdir(parents=True, exist_ok=True)
    print(f"[Harness] Mode: {PIPELINE_MODE}")
    hot_tier = load_hot_tier()
    mcp_log = MCPResourceLog(preprocessing_path, result_dir)
    print(f"[Harness] MCP initialized — preprocessing v:{mcp_log.version_hash[:8]}")

    # Stores system+user per stage for self-correction loops
    stage_contexts = {}

    # ── STAGE 1 + STAGE 2 (parallel) ──────────────────────────
    if start_from_stage <= 1:
        contexts = await run_stages_parallel(
            target_usid, result_dir, hot_tier, mcp_log, model
        )
        stage_contexts.update(contexts)

        # Register outputs with MCP
        mcp_log.register_stage_output("stage1", result_dir / "stage1_coverage_load.json")
        mcp_log.register_stage_output("stage2", result_dir / "stage2_attribute_config.json")

        print("\n[Gate 1+2] Validating Stage 1 and Stage 2 outputs...")
        try:
            pydantic_gate_with_correction(
                "1", result_dir / "stage1_coverage_load.json", Stage1Output,
                stage_contexts["stage1"]["system"],
                stage_contexts["stage1"]["user"],
            )
            from schemas.stage2 import Stage2Output
            pydantic_gate_with_correction(
                "2", result_dir / "stage2_attribute_config.json", Stage2Output,
                stage_contexts["stage2"]["system"],
                stage_contexts["stage2"]["user"],
            )
        except RuntimeError as e:
            print(f"\n[Harness] STOPPED at Gate 1/2 — {e}")
            return None

    # ── STAGE 3 ────────────────────────────────────────────────
    if start_from_stage <= 3:
        warm_s3 = load_warm_tier("stage3")

        # Stage 3 queries MCP for what it needs — no hard-coded paths
        s3_preprocessing = mcp_log.query_resource(
            "preprocessing_stats.json",
            query="load redistribution overlap info SINR coverage holes",
            reader="stage3-agent",
        )
        s3_from_stage1 = mcp_log.query_resource(
            "stage1",
            query="load redistribution verdict and per backup overload risks",
            reader="stage3-agent",
        )
        s3_data = {**s3_preprocessing, "stage1_context": s3_from_stage1}

        from harness.stages.stage3_prompt import STAGE3_PROMPT
        _, s3_system, s3_user = run_stage("Stage3",
            STAGE3_PROMPT.format(target_usid=target_usid),
            hot_tier, warm_s3,
            json.dumps(s3_data, indent=2),
            result_dir / "stage3_geographic.json",
            model,
        )
        stage_contexts["stage3"] = {"system": s3_system, "user": s3_user}
        mcp_log.register_stage_output("stage3", result_dir / "stage3_geographic.json")

        print("\n[Gate 3] Validating Stage 3 output...")
        try:
            from schemas.stage3 import Stage3Output
            pydantic_gate_with_correction(
                "3", result_dir / "stage3_geographic.json", Stage3Output,
                s3_system, s3_user,
            )
        except RuntimeError as e:
            print(f"\n[Harness] STOPPED at Gate 3 — {e}")
            return None

    # ── STAGE 4 (context reset) ────────────────────────────────
    if start_from_stage <= 4:
        # Build handoff via MCP queries — no hard-coded field paths
        handoff = build_stage4_handoff(mcp_log, target_usid)
        print("\n[Context reset] Handoff artifact built for Stage 4")

        warm_s4 = load_warm_tier("stage4")
        from harness.stages.stage4_prompt import STAGE4_PROMPT
        _, s4_system, s4_user = run_stage("Stage4",
            STAGE4_PROMPT.format(
                target_usid=target_usid,
                shutdown_start=shutdown_start,
                shutdown_end=shutdown_end,
            ),
            hot_tier, warm_s4,
            json.dumps(handoff, indent=2),
            result_dir / f"stage4_final_{target_usid}.json",
            model,
        )
        stage_contexts["stage4"] = {"system": s4_system, "user": s4_user}
        mcp_log.register_stage_output(
            "stage4", result_dir / f"stage4_final_{target_usid}.json")

        print("\n[Gate 4] Validating Stage 4 output...")
        try:
            from schemas.stage4 import Stage4Output
            pydantic_gate_with_correction(
                "4", result_dir / f"stage4_final_{target_usid}.json", Stage4Output,
                s4_system, s4_user,
            )
        except RuntimeError as e:
            print(f"\n[Harness] STOPPED at Gate 4 — {e}")
            return None

    # ── STAGE 5A — with auto-correction ───────────────────────
    print("\n[Stage 5A] Deterministic numeric verification...")
    all_stage_systems = {k: v["system"] for k, v in stage_contexts.items()}
    all_stage_users   = {k: v["user"]   for k, v in stage_contexts.items()}

    s5a_result = run_stage5a_with_correction(
        hot_tier=hot_tier,
        mcp_log=mcp_log,
        preprocessing_path=preprocessing_path,
        result_dir=result_dir,
        target_usid=target_usid,
        model=model,
        all_stage_systems=all_stage_systems,
        all_stage_users=all_stage_users,
    )

    if s5a_result["critical_failures"]:
        print(f"\n[Harness] STOPPED — Stage 5A: {len(s5a_result['critical_failures'])} failure(s)")
        for f in s5a_result["critical_failures"]:
            print(f"  {f['check_id']}: expected {f['expected']}, found {f['found']}")
        print("[Harness] Needs human review — fix stage prompt or preprocessing")
        return None

    print(f"  [Stage 5A] PASS {s5a_result['passed']}/{s5a_result['total']} checks")

    # ── STAGE 5B — with auto-correction ───────────────────────
    print("\n[Stage 5B] Adversarial reasoning verification...")
    from harness.stages.stage5b_prompt import STAGE5B_EXAMPLES
    from schemas.stage4 import Stage5BOutput

    s5b_system = f"""
You are an adversarial senior RF network engineer.
Your job is to find flaws in this assessment.
Your default stance is SKEPTICISM.

{STAGE5B_EXAMPLES}

{hot_tier}
"""
    all_outputs = {
        "preprocessing": json.loads(preprocessing_path.read_text()),
        "stage1": json.loads((result_dir / "stage1_coverage_load.json").read_text()),
        "stage2": json.loads((result_dir / "stage2_attribute_config.json").read_text()),
        "stage3": json.loads((result_dir / "stage3_geographic.json").read_text()),
        "stage4": json.loads((result_dir / f"stage4_final_{target_usid}.json").read_text()),
    }

    s5b_result = run_stage5b_with_correction(
        s5b_system=s5b_system,
        all_outputs=all_outputs,
        hot_tier=hot_tier,
        result_dir=result_dir,
        target_usid=target_usid,
        model=model,
        all_stage_systems=all_stage_systems,
        all_stage_users=all_stage_users,
    )

    overall = s5b_result["verification_summary"]["overall_result"]
    print(f"  [Stage 5B] {overall}")

    if overall == "FAIL":
        print("[Harness] STOPPED — Stage 5B FAIL after correction attempt")
        print("[Harness] Needs human review — check reasoning and rules")
        return None

    # ── STAGE 6 — ACE Reflector (PASS only) ───────────────────
    print("\n[Stage 6] ACE Reflector...")
    playbook = PlaybookManager()

    from harness.stages.stage6_prompt import STAGE6_PROMPT
    s6_json, _, _ = run_agent(
        stage_id="Stage6",
        system="You write lessons for future pipeline runs. Be specific. "
               "Only write items for genuine edge cases or boundary conditions.",
        user=STAGE6_PROMPT + "\n\n" + json.dumps({
            "stage4_result": all_outputs["stage4"],
            "stage5a_result": s5a_result,
            "stage5b_result": s5b_result,
            "stage3_zones": all_outputs["stage3"].get("impact_zones", []),
        }, indent=2),
        output_path=result_dir / "stage6_lessons.json",
        model=model,
    )
    try:
        deltas = json.loads(s6_json)
        for delta in deltas.get("new_items", []):
            playbook.add_delta(
                stage_id=delta["applies_to"],
                item_type=delta["type"],
                content=delta["content"],
            )
        print(f"  [Stage 6] {len(deltas.get('new_items', []))} delta(s) written to playbook")
    except Exception:
        print("  [Stage 6] No new items to write")

    # ── Final summary ──────────────────────────────────────────
    stage4_out = json.loads(
        (result_dir / f"stage4_final_{target_usid}.json").read_text()
    )
    rating = stage4_out["overall_rating"]
    print(f"\n{'='*60}")
    print(f" COMPLETE — {target_usid}")
    print(f" Severity:  {rating['impact_severity'].upper()}")
    print(f" Level:     {rating['user_impact_level']} / 4")
    print(f" Verified:  {overall}")
    print(f"{'='*60}\n")
    return stage4_out


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-usid",    required=True)
    parser.add_argument("--shutdown-start", required=True)
    parser.add_argument("--shutdown-end",   required=True)
    parser.add_argument("--from-stage", type=int, default=1, choices=[1,2,3,4])
    parser.add_argument("--workspace",  default="/workspace")
    parser.add_argument("--model",      default="claude-opus-4-5")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    asyncio.run(run_pipeline(
        target_usid=args.target_usid,
        shutdown_start=args.shutdown_start,
        shutdown_end=args.shutdown_end,
        preprocessing_path=workspace/"results"/args.target_usid/"preprocessing_stats.json",
        result_dir=workspace/"results"/args.target_usid,
        start_from_stage=args.from_stage,
        model=args.model,
    ))