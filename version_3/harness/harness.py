"""
harness.py
==========
Orchestrates the full telecom outage assessment pipeline for one ticket.

Pipeline steps
--------------
  1. Local preprocessing          (Python, in-process)
  2. Context Planner              (claude CLI, serial)
  3. Coverage / KPI / Config      (claude CLI, parallel)
  3b. Per-agent verification      (claude CLI, Coverage/KPI/Config)
  4. Geo Agent                    (claude CLI, after Coverage)
  4b. Per-agent verification      (claude CLI, Geo)
  5. Assessment Agent             (claude CLI, after all four)
  5b. Per-agent verification      (claude CLI, Assessment)
  6. Cross-Agent Verifier         (claude CLI, consistency checks + rerun/hitl)
  7. Reflector                    (claude CLI, memory store update)

Usage
-----
  python harness/harness.py <ticket_id>
  python harness/harness.py TKT-2026-04-19-0000
"""

import glob
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
DATA_DIR   = ROOT / "data"
SKILLS_DIR = ROOT / "skills"
ARTIFACTS  = ROOT / "artifacts"
MCP_SERVER = ROOT / "mcp_server" / "server.py"

sys.path.insert(0, str(ROOT))
from version_3.test_function.local_preprocessing import run_local_preprocessing  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# MCP config helpers
# ─────────────────────────────────────────────────────────────────────────────

def _write_mcp_config(run_dir: Path) -> Path:
    """Write a per-run MCP config pointing at the telecom_data stdio server."""
    config = {
        "mcpServers": {
            "telecom_data": {
                "command": sys.executable,
                "args": [str(MCP_SERVER)],
                "env": {"DATA_DIR": str(DATA_DIR), "MAP_OUTPUT_DIR": str(run_dir)},
            }
        }
    }
    path = run_dir / "mcp_config.json"
    path.write_text(json.dumps(config, indent=2))
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Agent runner
# ─────────────────────────────────────────────────────────────────────────────

def run_agent(
    agent_name: str,
    skill_files: List[str],
    allowed_tools: str,
    shared_context: dict,
    agent_context: dict,
    ticket: dict,
    run_id: str,
    neighbor_usids: list = None,
    extra_inputs: str = "",
    mcp_config: Optional[Path] = None,
    output_filename: Optional[str] = None,
) -> str:
    """Build prompt from skill files + context, then invoke claude CLI."""

    parts = []

    # 1. Skill file contents
    for sf in skill_files:
        path = ROOT / sf
        if path.exists():
            parts.append(path.read_text())
        else:
            print(f"  [WARN] skill file not found: {sf}")

    # 2. Context blocks
    parts.append("---\n## Shared Context\n\n" + json.dumps(shared_context, indent=2))
    parts.append("---\n## Your Context\n\n" + json.dumps(agent_context, indent=2))
    parts.append("---\n## Ticket\n\n" + json.dumps(ticket, indent=2))
    parts.append(
        "---\n## Run Parameters\n\n"
        f"run_id: {run_id}\n"
        f"affected_usid: {ticket['affected_usid']}\n"
        f"neighbor_usids: {json.dumps(neighbor_usids or [])}"
    )

    # 3. Extra inputs (e.g. upstream agent artifacts)
    if extra_inputs:
        parts.append(extra_inputs)

    # 4. Save instruction — use output_filename when provided (e.g. verification files)
    save_filename = output_filename or f"{agent_name}_artifact.json"
    parts.append(
        f"\nSave your artifact to artifacts/{run_id}/{save_filename} "
        "using the Write tool."
    )

    prompt = "\n\n".join(parts)

    cmd = ["claude", "-p", "--allowedTools", allowed_tools]
    if mcp_config is not None:
        cmd += ["--mcp-config", str(mcp_config)]

    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    if result.returncode != 0:
        print(f"  [WARN] {agent_name} exited {result.returncode}:\n"
              f"{result.stderr[:400]}")

    return result.stdout


# ─────────────────────────────────────────────────────────────────────────────
# Ticket loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_ticket(ticket_id: str) -> dict:
    tickets_path = DATA_DIR / "outage_tickets.json"
    with open(tickets_path) as f:
        data = json.load(f)
    for t in data["tickets"]:
        if t["ticket_id"] == ticket_id:
            return t
    print(f"ERROR: ticket {ticket_id!r} not found in {tickets_path}")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Skill-file selection based on planner flags
# ─────────────────────────────────────────────────────────────────────────────

def _select_skill_files(per_agent_context: dict, ticket: dict) -> dict:
    """Return skill file lists for all five agents."""

    coverage_flag = per_agent_context["coverage_agent"].get("flag")
    kpi_flag      = per_agent_context["kpi_agent"].get("flag")

    # Coverage
    coverage_skills = [
        "skills/reasoning/coverage_analysis_base.md",
        "skills/output/scratchpad_format.md",
        "skills/output/artifact_schema.md",
    ]
    if coverage_flag in ("PARTIAL_SECTOR_FAILURE", "FULL_SITE_FAILURE"):
        coverage_skills.append("skills/reasoning/coverage_directional_focus.md")

    # KPI — Sustained covers peak derivation internally when duration > 6h
    duration_hours = None
    if ticket.get("outage_end_utc"):
        start = datetime.fromisoformat(
            ticket["outage_start_utc"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(
            ticket["outage_end_utc"].replace("Z", "+00:00"))
        duration_hours = (end - start).total_seconds() / 3600

    kpi_skills = [
        "skills/reasoning/kpi_analysis_base.md",
        "skills/output/scratchpad_format.md",
        "skills/output/artifact_schema.md",
    ]

    if duration_hours is not None and duration_hours > 6:
        # Sustained covers peak hour derivation internally
        kpi_skills.append("skills/reasoning/kpi_sustained_pressure.md")
    elif kpi_flag == "PEAK_HOUR_OVERFLOW":
        # Short outage with peak overlap — run Peak independently
        kpi_skills.append("skills/reasoning/kpi_peak_hour_analysis.md")

    # Config
    config_skills = [
        "skills/reasoning/config_analysis_base.md",
        "skills/output/scratchpad_format.md",
        "skills/output/artifact_schema.md",
    ]

    # Geo
    geo_skills = [
        "skills/reasoning/geo_analysis_base.md",
        "skills/output/scratchpad_format.md",
        "skills/output/artifact_schema.md",
    ]

    # Assessment
    assessment_skills = [
        "skills/reasoning/assessment_agent.md",
        "skills/output/artifact_schema.md",
    ]

    return {
        "coverage":   coverage_skills,
        "kpi":        kpi_skills,
        "config":     config_skills,
        "geo":        geo_skills,
        "assessment": assessment_skills,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-agent verification helper
# ─────────────────────────────────────────────────────────────────────────────

def run_per_agent_verification(
    agent_name: str,
    run_dir: Path,
    shared_context: dict,
    mcp_cfg: Path,
    neighbor_usids: list,
    ticket: dict,
    run_id: str,
) -> dict:
    """Run per-agent verification immediately after an agent completes."""

    artifact_path = run_dir / f"{agent_name}_artifact.json"
    if not artifact_path.exists():
        print(f"  [WARN] {agent_name}_artifact.json missing — skipping verification")
        return {"overall": "skip", "reason": "artifact missing"}

    with open(artifact_path) as f:
        agent_artifact = json.load(f)

    extra_verification = (
        f"\n## Agent Name\n\n{agent_name}\n"
        f"\n## Agent Artifact\n\n{json.dumps(agent_artifact, indent=2)}\n"
        f"\n## Shared Context\n\n{json.dumps(shared_context, indent=2)}\n"
    )

    if "time_background" in shared_context:
        extra_verification += (
            f"\n## Time Background\n\n"
            f"{json.dumps(shared_context.get('time_background'), indent=2)}\n"
        )
    if "area_profile" in shared_context:
        extra_verification += (
            f"\n## Area Profile\n\n"
            f"{json.dumps(shared_context.get('area_profile'), indent=2)}\n"
        )

    run_agent(
        f"{agent_name}_verification",
        ["skills/verification/per_agent_verifier.md"],
        "Write",
        shared_context, {},
        ticket, run_id,
        neighbor_usids=neighbor_usids,
        extra_inputs=extra_verification,
        mcp_config=mcp_cfg,
        output_filename=f"{agent_name}_verification.json",
    )

    verification_path = run_dir / f"{agent_name}_verification.json"
    if verification_path.exists():
        with open(verification_path) as f:
            result = json.load(f)
        overall = result.get("overall", "unknown")
        flag_count = len(result.get("flags_for_cross_verifier", []))
        print(f"  [{agent_name} verification] {overall}"
              + (f" — {flag_count} flag(s) for cross-verifier" if flag_count else ""))
        return result
    return {"overall": "unknown"}


# ─────────────────────────────────────────────────────────────────────────────
# Reflector helper
# ─────────────────────────────────────────────────────────────────────────────

def _run_reflector(
    run_dir: Path,
    run_id: str,
    ticket: dict,
    mcp_cfg: Path,
    neighbor_usids: list,
    shared_context: dict,
) -> None:
    print("[Step 7] Reflector…")

    memory_store_path = ROOT / "memory_store" / "memory_store.json"
    memory_store_path.parent.mkdir(exist_ok=True)

    extra_reflector = ""

    verifier_path = run_dir / "cross_agent_verifier_artifact.json"
    if verifier_path.exists():
        with open(verifier_path) as f:
            verifier_data = json.load(f)
        extra_reflector += (
            "\n## Cross-Agent Verifier Output\n\n"
            + json.dumps(verifier_data, indent=2)
        )
    else:
        print("  [WARN] cross_agent_verifier_artifact.json missing — "
              "reflector will run without verifier payload")

    memory_store = {}
    if memory_store_path.exists():
        with open(memory_store_path) as f:
            memory_store = json.load(f)
    extra_reflector += (
        "\n\n## Existing Memory Store\n\n"
        + json.dumps(memory_store, indent=2)
    )

    run_agent(
        "reflector",
        ["skills/reflection/reflector.md"],
        "Write",
        shared_context, {},
        ticket, run_id,
        neighbor_usids, extra_reflector, mcp_cfg,
    )
    print("  [reflector] completed\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(ticket_id: str) -> None:

    ticket  = _load_ticket(ticket_id)
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id  = f"{ticket_id}_{ts}"
    run_dir = ARTIFACTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    mcp_cfg = _write_mcp_config(run_dir)

    print(f"\n{'='*60}")
    print(f"  Ticket:  {ticket_id}")
    print(f"  USID:    {ticket['affected_usid']}")
    print(f"  Type:    {ticket['outage_type']}")
    print(f"  Run ID:  {run_id}")
    print(f"  Output:  {run_dir}")
    print(f"{'='*60}\n")

    # ── Step 1: Local preprocessing ───────────────────────────────────────────
    print("[Step 1] Local preprocessing…")
    run_local_preprocessing(
        coverage_json_path=str(DATA_DIR / "usid_coverage_pixels.json"),
        attr_csv_path=str(DATA_DIR / "usid_attributes.csv"),
        target_usid=ticket["affected_usid"],
        output_dir=str(run_dir),
    )
    stats_path = run_dir / "preprocessing_stats.json"
    size_kb = stats_path.stat().st_size // 1024 if stats_path.exists() else 0
    print(f"  → preprocessing_stats.json ({size_kb} KB)\n")
    
    #get neighbor lists
    with open(stats_path) as f:
        preprocessing = json.load(f)
    neighbor_usids = preprocessing.get("neighbor_usids", [])
    print(f"  → {len(neighbor_usids)} neighbors identified: {neighbor_usids}\n")

    # ── Step 2: Context Planner ───────────────────────────────────────────────
    print("[Step 2] Context Planner…")

    planner_skill_paths = [
        SKILLS_DIR / "planner" / "planning_rules.md",
        SKILLS_DIR / "planner" / "context_rules" / "coverage_agent_context.md",
        SKILLS_DIR / "planner" / "context_rules" / "kpi_agent_context.md",
        SKILLS_DIR / "planner" / "context_rules" / "config_agent_context.md",
        SKILLS_DIR / "planner" / "context_rules" / "geo_agent_context.md",
        SKILLS_DIR / "planner" / "output_schema.md",
    ]
    planner_parts = []
    for p in planner_skill_paths:
        if p.exists():
            planner_parts.append(p.read_text())
        else:
            print(f"  [WARN] planner skill not found: {p}")

    planner_parts.append(
        "---\n\n## Ticket\n\n"
        + json.dumps(ticket, indent=2)
        + f"\n\n## Run parameters\n\nrun_id: {run_id}\n\n"
        "You are the Context Planner. Follow planning_rules.md exactly.\n"
        "Use the telecom_data MCP tools to retrieve any data you need.\n"
        "Output ONLY the final JSON block as defined in output_schema.md.\n"
        f"Save the JSON to artifacts/{run_id}/planner_output.json using the Write tool."
    )
    planner_prompt = "\n\n".join(planner_parts)

    subprocess.run(
        [
            "claude", "-p",
            "--mcp-config", str(mcp_cfg),
            "--allowedTools",
            "mcp__telecom_data__get_kpi_history,"
            "mcp__telecom_data__get_kpi_timeseries,"
            "Write",
        ],
        input=planner_prompt,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )

    planner_path = run_dir / "planner_output.json"
    if not planner_path.exists():
        print("  ERROR: planner_output.json was not created. Aborting.")
        sys.exit(1)

    with open(planner_path) as f:
        planner_output = json.load(f)

    shared_context    = planner_output["shared_context"]
    per_agent_context = planner_output["per_agent_context"]
    print(f"  → planner_output.json parsed "
          f"(outage_type={shared_context['outage_scope']['type']})\n")

    # ── Skill file selection ──────────────────────────────────────────────────
    skills = _select_skill_files(per_agent_context, ticket)

    # Verification flags accumulate across steps 3b, 4b, 5b and are passed to
    # the cross-agent verifier in Step 6.
    verification_flags: dict = {}

    # ── Step 3: Coverage / KPI / Config in parallel ───────────────────────────
    print("[Step 3] Coverage / KPI / Config agents (parallel)…")

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(
                run_agent,
                "coverage_agent",
                skills["coverage"],
                "mcp__telecom_data__get_coverage_pixels,"
                "mcp__telecom_data__get_coverage_pixels_by_sector,"
                "mcp__telecom_data__get_preprocessing_stats,"
                "Write",
                shared_context,
                per_agent_context["coverage_agent"],
                ticket, run_id,
                neighbor_usids,"", mcp_cfg,
            ): "coverage_agent",

            executor.submit(
                run_agent,
                "kpi_agent",
                skills["kpi"],
                "mcp__telecom_data__get_kpi_history,"
                "mcp__telecom_data__get_kpi_timeseries,"
                "Write",
                shared_context,
                per_agent_context["kpi_agent"],
                ticket, run_id, neighbor_usids, "", mcp_cfg,
            ): "kpi_agent",

            executor.submit(
                run_agent,
                "config_agent",
                skills["config"],
                "mcp__telecom_data__get_site_attributes,"
                "mcp__telecom_data__get_all_site_attributes,"
                "Write",
                shared_context,
                per_agent_context["config_agent"],
                ticket, run_id, 
                neighbor_usids, "", mcp_cfg,
            ): "config_agent",
        }

        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
                print(f"  [{name}] completed")
            except Exception as exc:
                print(f"  [{name}] ERROR: {exc}")

    print()

    # ── Step 3b: Per-agent verification (Coverage, KPI, Config) ──────────────
    print("[Step 3b] Per-agent verification (Coverage, KPI, Config)…")
    for _agent_name in ["coverage_agent", "kpi_agent", "config_agent"]:
        result = run_per_agent_verification(
            _agent_name, run_dir, shared_context,
            mcp_cfg, neighbor_usids, ticket, run_id,
        )
        verification_flags[_agent_name] = result.get("flags_for_cross_verifier", [])
    print()

    # ── Step 4: Geo Agent (after Coverage) ────────────────────────────────────
    print("[Step 4] Geo Agent…")

    extra_geo = ""
    coverage_artifact_path = run_dir / "coverage_agent_artifact.json"
    try:
        with open(coverage_artifact_path) as f:
            coverage_artifact = json.load(f)
        extra_geo = (
            "\n## Coverage Agent Artifact\n\n"
            + json.dumps(coverage_artifact, indent=2)
        )
    except FileNotFoundError:
        print("  [WARN] coverage_agent_artifact.json missing — "
              "geo agent will run without it")

    run_agent(
        "geo_agent",
        skills["geo"],
        "mcp__telecom_data__get_geo_features,Write",
        shared_context,
        per_agent_context["geo_agent"],
        ticket, run_id,neighbor_usids,
        extra_geo,
        mcp_cfg,
    )
    print("  [geo_agent] completed\n")

    # ── Step 4b: Per-agent verification (Geo) ────────────────────────────────
    print("[Step 4b] Per-agent verification (Geo)…")
    geo_ver = run_per_agent_verification(
        "geo_agent", run_dir, shared_context,
        mcp_cfg, neighbor_usids, ticket, run_id,
    )
    verification_flags["geo_agent"] = geo_ver.get("flags_for_cross_verifier", [])
    print()

    # ── Step 5: Assessment Agent ──────────────────────────────────────────────
    print("[Step 5] Assessment Agent…")

    geo_path = run_dir / "geo_agent_artifact.json"
    if geo_path.exists():
        with open(geo_path) as f:
            geo_data = json.load(f)
        map_available = (geo_data
                         .get("area_overview", {})
                         .get("map_available", True))
        if not map_available:
            print("\n  [ERROR] Geo Agent: real map not available.")
            print("  MCP get_geo_features tool must be connected.")
            print("  Verify MCP server and retry.")
            print("  Pipeline will continue but geo analysis is unreliable.\n")

    geo_maps = glob.glob(str(run_dir / "geo_map_*.png"))
    if geo_maps:
        for map_path in geo_maps:
            dest = run_dir / Path(map_path).name
            if not dest.exists():
                shutil.copy2(map_path, dest)
        print(f"  [geo] {len(geo_maps)} map image(s) saved to artifacts/{run_id}/")
    else:
        print("  [geo] No map images found — confirm get_geo_features saved images.")

    extra_assessment_parts = []
    for agent in ["coverage_agent", "kpi_agent", "config_agent", "geo_agent"]:
        path = run_dir / f"{agent}_artifact.json"
        try:
            with open(path) as f:
                artifact = json.load(f)
            extra_assessment_parts.append(
                f"\n## {agent} Artifact\n\n" + json.dumps(artifact, indent=2)
            )
        except FileNotFoundError:
            print(f"  [WARN] {agent}_artifact.json missing — "
                  "assessment agent will proceed without it")

    run_agent(
        "assessment_agent",
        skills["assessment"],
        "Write",
        shared_context,
        {},
        ticket, run_id,neighbor_usids,
        "\n".join(extra_assessment_parts),
        mcp_cfg,
    )
    print("  [assessment_agent] completed\n")

    # ── Step 5b: Per-agent verification (Assessment) ──────────────────────────
    print("[Step 5b] Per-agent verification (Assessment)…")
    asm_ver = run_per_agent_verification(
        "assessment_agent", run_dir, shared_context,
        mcp_cfg, neighbor_usids, ticket, run_id,
    )
    verification_flags["assessment_agent"] = asm_ver.get(
        "flags_for_cross_verifier", []
    )
    print()

    # ── Step 6: Cross-Agent Verifier ──────────────────────────────────────────
    print("[Step 6] Cross-Agent Verifier…")

    all_artifacts = {}
    for name in ["planner_output", "coverage_agent_artifact",
                 "kpi_agent_artifact", "config_agent_artifact",
                 "geo_agent_artifact", "assessment_agent_artifact"]:
        path = run_dir / f"{name}.json"
        if path.exists():
            with open(path) as f:
                all_artifacts[name] = json.load(f)
        else:
            print(f"  [WARN] {name}.json missing")

    extra_verifier = "\n".join(
        f"\n## {name}\n\n{json.dumps(artifact, indent=2)}"
        for name, artifact in all_artifacts.items()
    )
    extra_verifier += "\n\n## Retry Count\n\nretry_count: 0"
    extra_verifier += (
        "\n\n## Per-Agent Verification Flags\n\n"
        + json.dumps(verification_flags, indent=2)
    )

    run_agent(
        "cross_agent_verifier",
        ["skills/verification/cross_agent_verifier.md"],
        "Write",
        shared_context, {},
        ticket, run_id,
        neighbor_usids, extra_verifier, mcp_cfg,
    )

    verifier_path = run_dir / "cross_agent_verifier_artifact.json"
    verifier_output = {}
    if verifier_path.exists():
        with open(verifier_path) as f:
            verifier_output = json.load(f)

    overall_result = verifier_output.get("overall_result", "pass")
    print(f"  [cross_agent_verifier] result: {overall_result}\n")

    # Tool mapping used for targeted agent reruns
    _AGENT_TOOLS = {
        "coverage_agent": (
            "mcp__telecom_data__get_coverage_pixels,"
            "mcp__telecom_data__get_coverage_pixels_by_sector,"
            "mcp__telecom_data__get_preprocessing_stats,"
            "Write"
        ),
        "kpi_agent": (
            "mcp__telecom_data__get_kpi_history,"
            "mcp__telecom_data__get_kpi_timeseries,"
            "Write"
        ),
        "config_agent": (
            "mcp__telecom_data__get_site_attributes,"
            "mcp__telecom_data__get_all_site_attributes,"
            "Write"
        ),
        "geo_agent": "mcp__telecom_data__get_geo_features,Write",
    }

    if overall_result == "hitl":
        print("  !! HUMAN IN THE LOOP REQUIRED !!")
        escalation = verifier_output.get("escalation_report", {})
        print(f"  Reason: {escalation.get('description', '')}")
        print(f"  Artifacts: artifacts/{run_id}/")
        escalation_path = run_dir / "ESCALATION_REQUIRED.txt"
        escalation_path.write_text(json.dumps(escalation, indent=2))
        _run_reflector(run_dir, run_id, ticket, mcp_cfg,
                       neighbor_usids, shared_context)
        # Fall through to summary — do not return, so summary still prints

    elif overall_result == "rerun":
        rerun_agents = verifier_output.get("rerun_agents", [])
        print(f"  [RERUN] Agents to re-run: {rerun_agents}")
        discrepancy_note = (
            "\n\n## Verifier Discrepancy Note\n\n"
            + "\n".join(
                d.get("description", "")
                for d in verifier_output
                    .get("reflector_payload", {})
                    .get("discrepancies", [])
            )
        )
        for agent_name in rerun_agents:
            if agent_name not in _AGENT_TOOLS:
                print(f"  [WARN] Cannot rerun {agent_name} — no tool mapping")
                continue
            print(f"  [RERUN] Re-running {agent_name}…")
            agent_key = agent_name.replace("_agent", "")
            agent_skills = skills.get(agent_key, [])
            agent_extra = discrepancy_note
            if agent_name == "geo_agent":
                try:
                    with open(run_dir / "coverage_agent_artifact.json") as f:
                        cov = json.load(f)
                    agent_extra = (
                        "\n## Coverage Agent Artifact\n\n"
                        + json.dumps(cov, indent=2)
                        + discrepancy_note
                    )
                except FileNotFoundError:
                    pass
            run_agent(
                agent_name, agent_skills, _AGENT_TOOLS[agent_name],
                shared_context, per_agent_context.get(agent_name, {}),
                ticket, run_id, neighbor_usids, agent_extra, mcp_cfg,
            )
            print(f"  [RERUN] {agent_name} completed")

        # Reload updated artifacts and re-run verifier with retry_count=1
        for name in ["coverage_agent_artifact", "kpi_agent_artifact",
                     "config_agent_artifact", "geo_agent_artifact"]:
            path = run_dir / f"{name}.json"
            if path.exists():
                with open(path) as f:
                    all_artifacts[name] = json.load(f)

        extra_verifier_retry = (
            "\n".join(
                f"\n## {name}\n\n{json.dumps(artifact, indent=2)}"
                for name, artifact in all_artifacts.items()
            )
            + "\n\n## Retry Count\n\nretry_count: 1"
        )
        run_agent(
            "cross_agent_verifier",
            ["skills/verification/cross_agent_verifier.md"],
            "Write",
            shared_context, {},
            ticket, run_id,
            neighbor_usids, extra_verifier_retry, mcp_cfg,
        )
        if verifier_path.exists():
            with open(verifier_path) as f:
                verifier_output = json.load(f)
        if verifier_output.get("overall_result") == "hitl":
            print("  !! STILL CONFLICTING — ESCALATING TO HUMAN !!")
            escalation_path = run_dir / "ESCALATION_REQUIRED.txt"
            escalation_path.write_text(
                json.dumps(verifier_output.get("escalation_report"), indent=2)
            )

    # ── Step 7: Reflector ─────────────────────────────────────────────────────
    if overall_result != "hitl":
        _run_reflector(run_dir, run_id, ticket, mcp_cfg,
                       neighbor_usids, shared_context)

    # ── Summary ───────────────────────────────────────────────────────────────
    assessment_path = run_dir / "assessment_agent_artifact.json"
    try:
        with open(assessment_path) as f:
            assessment = json.load(f)
        severity = assessment.get("overall_severity", "unknown")
        summary  = assessment.get("summary", "(no summary)")
    except FileNotFoundError:
        severity = "unknown"
        summary  = "(assessment artifact missing)"

    print(f"\n{'='*60}")
    print("=== RUN COMPLETE ===")
    print(f"Run ID:   {run_id}")
    print(f"Ticket:   {ticket_id}")
    print(f"USID:     {ticket['affected_usid']}")
    print(f"Type:     {ticket['outage_type']}")
    print(f"\nArtifacts saved to: artifacts/{run_id}/")

    artifact_files = [
        "planner_output.json",
        "coverage_agent_artifact.json",
        "coverage_agent_verification.json",
        "kpi_agent_artifact.json",
        "kpi_agent_verification.json",
        "config_agent_artifact.json",
        "config_agent_verification.json",
        "geo_agent_artifact.json",
        "geo_agent_verification.json",
        "assessment_agent_artifact.json",
        "assessment_agent_verification.json",
        "cross_agent_verifier_artifact.json",
        "reflector_artifact.json",
        "ESCALATION_REQUIRED.txt (if hitl)",
    ]
    for fname in artifact_files:
        status = "✓" if (run_dir / fname).exists() else "✗ MISSING"
        print(f"  {status}  {fname}")

    print(f"\nFinal severity: {severity}")
    print(f"Summary: {summary}")
    print(f"{'='*60}\n")


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python harness/harness.py <ticket_id>")
        print("Example: python harness/harness.py TKT-2026-04-19-0000")
        sys.exit(1)
    run_pipeline(sys.argv[1])
