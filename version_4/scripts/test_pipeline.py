import json
import re
import subprocess
import threading
import anthropic
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import base64

client = anthropic.Anthropic()
_print_lock = threading.Lock()
OUTPUT_BASE     = Path(__file__).parent.parent / "output"
MCP_CONFIG_PATH = Path(__file__).parent.parent / "mcp_server" / "mcp_config.json"
PLANNER_MODEL  = "claude-sonnet-4-5"
AGENT_MODEL    = "claude-sonnet-4-5"
EVAL_MODEL     = "claude-sonnet-4-5"
AGENT_TOKENS   = 4096
EVAL_TOKENS    = 1024
PLANNER_TOKENS = 1024

# ─── HELPER FUNCTIONS ───────────────────────────────────────────────────────

def load_skill(path: str) -> str:
    return Path(path).read_text()

def load_pdf(path: str) -> str:
    return base64.standard_b64encode(
        Path(path).read_bytes()
    ).decode("utf-8")

def make_doc_block(pdf_b64: str, title: str) -> dict:
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": pdf_b64,
        },
        "title": title,
    }

def parse_json(text: str, label: str) -> dict | None:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        print(f"[ERROR] Could not parse JSON for {label}:\n{text}")
        return None

def parse_analysis_block(text: str) -> dict | None:
    match = re.search(r"<analysis>\s*(.*?)\s*</analysis>", text, re.DOTALL)
    if not match:
        print("[ERROR] No <analysis> block found in agent output")
        return None
    return parse_json(match.group(1), "analysis block")

# ─── CLI HELPERS ────────────────────────────────────────────────────────────

def make_cli_doc(pdf_b64: str, title: str) -> str:
    return (
        f"<document>\n"
        f"<title>{title}</title>\n"
        f"<source type=\"base64\" media_type=\"application/pdf\">"
        f"{pdf_b64}"
        f"</source>\n"
        f"</document>\n\n"
    )

def run_cli(system: str, user_message: str) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--system-prompt", system],
        input=user_message,
        capture_output=True,
        text=True,
    )
    raw = proc.stdout.strip()
    if not raw:
        raw = proc.stderr.strip()
    return raw

_MCP_ALLOWED_TOOLS = ",".join([
    "Bash",
    "mcp__telecom_data__get_kpi_history",
    "mcp__telecom_data__get_kpi_timeseries",
    "mcp__telecom_data__get_site_attributes",
    "mcp__telecom_data__get_all_site_attributes",
    "mcp__telecom_data__get_coverage_pixels",
    "mcp__telecom_data__get_coverage_pixels_by_sector",
    "mcp__telecom_data__get_geo_features",
    "mcp__telecom_data__get_area_profile",
    "mcp__telecom_data__get_ticket",
    "mcp__telecom_data__get_all_tickets",
])

def run_agent_cli_with_mcp(system: str, user_message: str,
                           output_dir: Path | None = None) -> str:
    """Like run_cli but connects to the MCP server for real data access.
    --allowedTools pre-approves each MCP tool so no interactive prompt is needed
    (works under root, unlike --dangerously-skip-permissions).
    output_dir is injected as MAP_OUTPUT_DIR into the MCP server env so that
    get_geo_features saves its PNG to the ticket output folder."""
    import tempfile, os

    if output_dir is not None:
        base = json.loads(MCP_CONFIG_PATH.read_text())
        base["mcpServers"]["telecom_data"]["env"]["MAP_OUTPUT_DIR"] = str(output_dir)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir="/tmp"
        )
        json.dump(base, tmp)
        tmp.close()
        config_path = tmp.name
    else:
        config_path = str(MCP_CONFIG_PATH)

    try:
        proc = subprocess.run(
            [
                "claude", "-p",
                "--system-prompt", system,
                "--mcp-config", config_path,
                "--allowedTools", _MCP_ALLOWED_TOOLS,
            ],
            input=user_message,
            capture_output=True,
            text=True,
        )
    finally:
        if output_dir is not None:
            os.unlink(config_path)

    raw = proc.stdout.strip()
    if not raw:
        raw = proc.stderr.strip()
    return raw

def parse_cli_json(text: str, label: str) -> dict | None:
    text = re.sub(r"\x1b\[[0-9;]*[mGKHF]", "", text)
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"^```\s*$", "", text.strip(), flags=re.MULTILINE)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    print(f"[ERROR] Could not parse CLI JSON for {label}:\n{text}")
    return None

# ─── CALL FUNCTIONS ─────────────────────────────────────────────────────────

def call_planner(skill: str, pdf_b64: str, ticket: dict) -> dict | None:
    response = client.messages.create(
        model=PLANNER_MODEL,
        max_tokens=PLANNER_TOKENS,
        system=skill,
        messages=[{
            "role": "user",
            "content": [
                make_doc_block(pdf_b64, "Outage Assessment Framework"),
                {
                    "type": "text",
                    "text": "Process this ticket:\n" + json.dumps(ticket, indent=2),
                },
            ],
        }],
    )
    return parse_json(response.content[0].text, "planner")


def call_planner_evaluator(skill: str, pdf_b64: str,
                           ticket: dict,
                           planner_output: dict) -> dict | None:
    response = client.messages.create(
        model=EVAL_MODEL,
        max_tokens=EVAL_TOKENS,
        system=skill,
        messages=[{
            "role": "user",
            "content": [
                make_doc_block(pdf_b64, "Outage Assessment Framework"),
                {
                    "type": "text",
                    "text": (
                        "Original ticket:\n"
                        + json.dumps(ticket, indent=2)
                        + "\n\nPlanner output:\n"
                        + json.dumps(planner_output, indent=2)
                    ),
                },
            ],
        }],
    )
    return parse_json(response.content[0].text, "planner_evaluator")


def call_agent(agent_id: str, skill: str, pdf_b64: str,
               ticket_parsed: dict,
               agent_task: dict) -> str:
    response = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=AGENT_TOKENS,
        system=skill,
        messages=[{
            "role": "user",
            "content": [
                make_doc_block(pdf_b64, f"{agent_id} Reference Document"),
                {
                    "type": "text",
                    "text": (
                        f"Assigned question: {agent_task['question']}\n\n"
                        f"Recommended tools: "
                        f"{json.dumps(agent_task['recommended_tools'])}\n\n"
                        f"Ticket context:\n"
                        f"{json.dumps(ticket_parsed, indent=2)}"
                    ),
                },
            ],
        }],
    )
    return response.content[0].text


def call_agent_evaluator(skill: str, agent_id: str,
                         assigned_question: str,
                         recommended_tools: list,
                         agent_output: str) -> dict | None:
    response = client.messages.create(
        model=EVAL_MODEL,
        max_tokens=EVAL_TOKENS,
        system=skill,
        messages=[{
            "role": "user",
            "content": (
                f"Agent ID: {agent_id}\n\n"
                f"Assigned question: {assigned_question}\n\n"
                f"Recommended tools: {json.dumps(recommended_tools)}\n\n"
                f"Agent output:\n{agent_output}"
            ),
        }],
    )
    return parse_json(response.content[0].text, f"{agent_id}_evaluator")

# ─── CLI CALL FUNCTIONS ─────────────────────────────────────────────────────

def call_planner_cli(skill: str, pdf_b64: str, ticket: dict) -> dict | None:
    user_message = (
        make_cli_doc(pdf_b64, "Outage Assessment Framework")
        + "Process this ticket:\n"
        + json.dumps(ticket, indent=2)
    )
    raw = run_cli(skill, user_message)
    return parse_cli_json(raw, "planner_cli")


def call_planner_evaluator_cli(skill: str, pdf_b64: str,
                                ticket: dict,
                                planner_output: dict) -> dict | None:
    user_message = (
        make_cli_doc(pdf_b64, "Outage Assessment Framework")
        + "Original ticket:\n"
        + json.dumps(ticket, indent=2)
        + "\n\nPlanner output:\n"
        + json.dumps(planner_output, indent=2)
    )
    raw = run_cli(skill, user_message)
    return parse_cli_json(raw, "planner_evaluator_cli")


def call_agent_cli(agent_id: str, skill: str, pdf_b64: str,
                   ticket_parsed: dict,
                   agent_task: dict,
                   output_dir: Path | None = None) -> str:
    user_message = (
        make_cli_doc(pdf_b64, f"{agent_id} Reference Document")
        + f"Assigned question: {agent_task['question']}\n\n"
        + f"Recommended tools: {json.dumps(agent_task['recommended_tools'])}\n\n"
        + f"Ticket context:\n{json.dumps(ticket_parsed, indent=2)}"
    )
    return run_agent_cli_with_mcp(skill, user_message, output_dir=output_dir)


def call_agent_evaluator_cli(skill: str, agent_id: str,
                              assigned_question: str,
                              recommended_tools: list,
                              agent_output: str) -> dict | None:
    user_message = (
        f"Agent ID: {agent_id}\n\n"
        f"Assigned question: {assigned_question}\n\n"
        f"Recommended tools: {json.dumps(recommended_tools)}\n\n"
        f"Agent output:\n{agent_output}"
    )
    raw = run_cli(skill, user_message)
    return parse_cli_json(raw, f"{agent_id}_evaluator_cli")

# ─── OUTPUT HELPERS ─────────────────────────────────────────────────────────

def save_output(path: Path, content: str | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, dict):
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False))
    else:
        path.write_text(content)
    print(f"  [saved] {path}")

# ─── PRINT HELPERS ──────────────────────────────────────────────────────────

def section(title: str):
    print(f"\n── {title} ──")

def banner(title: str):
    print(f"\n{'═'*50}")
    print(f"  {title}")
    print('═'*50)

def status(passed: bool):
    return "✅ PASS" if passed else "❌ FAIL"

# ─── MAIN PIPELINE ──────────────────────────────────────────────────────────

def run_pipeline(ticket: dict, skills: dict, pdf_b64: str):
    banner(f"TICKET: {ticket['ticket_id']} ({ticket['outage_type']})")
    out_dir = OUTPUT_BASE / ticket["ticket_id"]

    # ── STEP 1: Planner ──
    section("PLANNER OUTPUT")
    planner_output = call_planner_cli(skills["planner"], pdf_b64, ticket)
    if not planner_output:
        print("Planner failed to return valid output. Aborting.")
        return
    print(json.dumps(planner_output, indent=2, ensure_ascii=False))
    save_output(out_dir / "planner.json", planner_output)

    # ── STEP 2: Planner Evaluator ──
    section("PLANNER EVAL")
    planner_eval = call_planner_evaluator_cli(
        skills["planner_evaluator"], pdf_b64, ticket, planner_output
    )
    if not planner_eval:
        print("Planner evaluator failed. Aborting.")
        return
    print(json.dumps(planner_eval, indent=2, ensure_ascii=False))
    save_output(out_dir / "planner_eval.json", planner_eval)
    print(f"STATUS: {status(planner_eval.get('pass', False))}")

    if not planner_eval.get("pass", False):
        print(f"FAIL REASONS: {planner_eval.get('fail_reasons', [])}")
        print("Planner did not pass. Skipping agents.")
        return

    # ── STEP 3: Extract planner outputs per agent ──
    ticket_parsed = planner_output["ticket_parsed"]
    assigned      = planner_output["assigned_questions"]
    agent_ids     = ["coverage_agent", "kpi_agent", "attribute_agent"]

    # ── STEP 4: Run all 3 agent+eval pairs in parallel (chained) ──
    # Each thread runs its agent then immediately its evaluator.
    section("RUNNING AGENTS + EVALUATORS IN PARALLEL (CHAINED)")
    agent_outputs = {}
    eval_outputs = {}

    def run_agent_and_eval(agent_id: str) -> tuple[str, str, dict | None]:
        output = call_agent_cli(
            agent_id,
            skills[agent_id],
            pdf_b64,
            ticket_parsed,
            assigned[agent_id],
            output_dir=out_dir,
        )
        save_output(out_dir / f"{agent_id}.txt", output)
        task = assigned[agent_id]
        result = call_agent_evaluator_cli(
            skills["sub_agent_evaluator"],
            agent_id,
            task["question"],
            task["recommended_tools"],
            output,
        )
        if result:
            save_output(out_dir / f"{agent_id}_eval.json", result)
        with _print_lock:
            print(f"  [{agent_id}] done → [{agent_id}_evaluator] done")
        return agent_id, output, result

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_agent_and_eval, aid): aid for aid in agent_ids
        }
        for future in as_completed(futures):
            agent_id, output, result = future.result()
            agent_outputs[agent_id] = output
            eval_outputs[agent_id] = result

    # ── STEP 5: Print agent outputs ──
    for agent_id in agent_ids:
        section(f"{agent_id.upper()} OUTPUT")
        print(agent_outputs[agent_id])

    # ── STEP 6: Print evaluator results ──
    for agent_id in agent_ids:
        section(f"{agent_id.upper()} EVAL")
        result = eval_outputs[agent_id]
        if result:
            print(json.dumps(result, indent=2, ensure_ascii=False))
            print(f"STATUS: {status(result.get('pass', False))}")
            if not result.get("pass"):
                print(f"FAIL REASONS: {result.get('fail_reasons', [])}")
        else:
            print("Evaluator returned no result.")

    # ── STEP 7: Summary ──
    banner("SUMMARY")
    print(f"{'agent':<25} {'pass':<8} {'overall':<10} {'confidence'}")
    print("-" * 55)
    for agent_id in agent_ids:
        ev = eval_outputs.get(agent_id) or {}
        ag = parse_analysis_block(agent_outputs.get(agent_id, "")) or {}
        print(
            f"{agent_id:<25} "
            f"{str(ev.get('pass', '?')):<8} "
            f"{ev.get('overall', '?'):<10} "
            f"{ag.get('confidence', '?')}"
        )


# ─── ENTRY POINT ────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # Load all skills
    _root = Path(__file__).parent.parent
    skills = {
        "planner":             load_skill(_root / "skills/planner/skill.md"),
        "planner_evaluator":   load_skill(_root / "skills/planner_evaluator/skill.md"),
        "coverage_agent":      load_skill(_root / "skills/coverage_agent/skill.md"),
        "kpi_agent":           load_skill(_root / "skills/kpi_agent/skill.md"),
        "attribute_agent":     load_skill(_root / "skills/attribute_agent/skill.md"),
        "sub_agent_evaluator": load_skill(_root / "skills/sub_agent_evaluator/skill.md"),
    }

    # Single shared PDF used by all agents
    pdf_b64 = load_pdf(_root / "skills/reference_document.pdf")

    # One Full Outage (USID_19, all sectors) and one Partial Outage
    # (USID_09, sectors S0 and S2) drawn from outage_tickets.json.
    # TKT-2026-04-30-0000 end_utc is estimated from the 4.6 h impact note.
    tickets = [
        # {
        #     "ticket_id": "TKT-2026-04-30-0000",
        #     "usid": "USID_19",
        #     "outage_type": "Full Outage",
        #     "start_utc": "2026-04-30T00:29:01Z",
        #     "end_utc": "2026-04-30T05:05:01Z",
        #     "affected_sectors": None,
        # },
        {
            "ticket_id": "TKT-2026-04-17-0002",
            "usid": "USID_09",
            "outage_type": "Partial Outage",
            "start_utc": "2026-04-17T10:31:15Z",
            "end_utc": "2026-04-17T20:58:56Z",
            "affected_sectors": ["S0", "S2"],
        },
    ]

    import sys
    outage_filter = sys.argv[1] if len(sys.argv) > 1 else None
    for ticket in tickets:
        if outage_filter and ticket["outage_type"].lower() != outage_filter.lower():
            continue
        run_pipeline(ticket, skills, pdf_b64)
        print("\n")
