import json
import pathlib
import re
import subprocess
import anthropic

SKILL_PATH = pathlib.Path(__file__).parent.parent / "skills" / "planner" / "skill.md"
MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 1024

# Extracted from data/outage_tickets.json
TICKET_FULL = {
    "ticket_id": "TKT-2026-04-19-0004",
    "usid": "USID_41",
    "outage_type": "Full Outage",
    "start_utc": "2026-04-19T19:53:36Z",
    "end_utc": "2026-04-20T00:17:31Z",
    "affected_sectors": ["S0", "S1"],
}

TICKET_PARTIAL = {
    "ticket_id": "TKT-2026-04-17-0002",
    "usid": "USID_09",
    "outage_type": "Partial Outage",
    "start_utc": "2026-04-17T10:31:15Z",
    "end_utc": "2026-04-17T20:58:56Z",
    "affected_sectors": ["S0", "S2"],
}

AGENTS = ["coverage_agent", "kpi_agent", "attribute_agent"]


OUTPUT_PATH = pathlib.Path(__file__).parent.parent / "output" / "planner_output.json"


def extract_json(raw: str) -> dict | None:
    # Strip ANSI escape codes
    clean = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', raw)
    # Strip markdown fences
    clean = re.sub(r'^```(?:json)?\s*', '', clean.strip(), flags=re.MULTILINE)
    clean = re.sub(r'```\s*$', '', clean.strip(), flags=re.MULTILINE)
    clean = clean.strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    # Fall back to extracting the outermost JSON object
    start, end = clean.find('{'), clean.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(clean[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def load_pdf_as_base64(path: str) -> str:
    """Load a PDF file and return it as a base64-encoded string."""
    import base64
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def call_planner(system: str, ticket: dict) -> tuple[dict | None, str]:
    """Call Claude Code via the claude CLI subprocess."""
    user_message = "Process this ticket: " + json.dumps(ticket, indent=2)
    proc = subprocess.run(
        ["claude", "-p", "--system-prompt", system],
        input=user_message,
        capture_output=True,
        text=True,
    )
    raw = proc.stdout.strip()
    if not raw:
        raw = proc.stderr.strip()
    return extract_json(raw), raw


def call_planner_api(system: str, ticket: dict) -> tuple[dict | None, str]:
    """Call the Claude model API directly via the Anthropic SDK."""
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[
            {"role": "user", "content": "Process this ticket: " + json.dumps(ticket, indent=2)}
        ],
    )
    raw = message.content[0].text.strip()
    return extract_json(raw), raw


def call_planner_with_pdf(
    system: str, ticket: dict, pdf_path: str
) -> tuple[dict | None, str]:
    """Call Claude Code via the claude CLI subprocess, embedding PDF as base64 in the message."""
    pdf_data = load_pdf_as_base64(pdf_path)
    user_message = (
        "<document>\n"
        "<title>Outage Assessment Framework</title>\n"
        "<context>Use this document to understand the key impact dimensions "
        "and risk signals when framing sub-questions.</context>\n"
        f"<source type=\"base64\" media_type=\"application/pdf\">{pdf_data}</source>\n"
        "</document>\n\n"
        "Process this ticket: " + json.dumps(ticket, indent=2)
    )
    proc = subprocess.run(
        ["claude", "-p", "--system-prompt", system],
        input=user_message,
        capture_output=True,
        text=True,
    )
    raw = proc.stdout.strip()
    if not raw:
        raw = proc.stderr.strip()
    return extract_json(raw), raw


def call_planner_api_with_pdf(
    system: str, ticket: dict, pdf_path: str
) -> tuple[dict | None, str]:
    """Call Claude API with a PDF reference document as a document block."""
    client = anthropic.Anthropic()
    pdf_data = load_pdf_as_base64(pdf_path)
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data,
                        },
                        "title": "Outage Assessment Framework",
                        "context": (
                            "Use this document to understand the key impact "
                            "dimensions and risk signals when framing sub-questions."
                        ),
                    },
                    {
                        "type": "text",
                        "text": "Process this ticket: " + json.dumps(ticket, indent=2),
                    },
                ],
            }
        ],
    )
    raw = message.content[0].text.strip()
    return extract_json(raw), raw


def print_result(label: str, ticket: dict, result: dict | None, raw: str) -> None:
    print(f"\n── TICKET {label}: {ticket['ticket_id']} ({ticket['outage_type']}) ──")
    if result is None:
        print(f"ERROR: could not parse JSON response\n{raw}")
    else:
        print(json.dumps(result, indent=2))


def print_diff(result_a: dict | None, result_b: dict | None) -> None:
    print("\n── QUESTION DIFF ──")
    for agent in AGENTS:
        q_a = result_a["assigned_questions"].get(agent, "<missing>") if result_a else "<error>"
        q_b = result_b["assigned_questions"].get(agent, "<missing>") if result_b else "<error>"
        print(f"\n{agent}")
        print(f"  FULL:    {q_a}")
        print(f"  PARTIAL: {q_b}")


def main() -> None:
    system = SKILL_PATH.read_text()

    result_a, raw_a = call_planner_with_pdf(system, TICKET_FULL, "version_4/skills/reference_document.pdf")
    result_b, raw_b = call_planner_with_pdf(system, TICKET_PARTIAL, "version_4/skills/reference_document.pdf")

    print_result("A", TICKET_FULL, result_a, raw_a)
    print_result("B", TICKET_PARTIAL, result_b, raw_b)

    print_diff(result_a, result_b)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    for ticket, raw in [(TICKET_FULL, raw_a), (TICKET_PARTIAL, raw_b)]:
        out_file = OUTPUT_PATH.parent / f"planner_{ticket['ticket_id']}.json"
        out_file.write_text(raw)
        print(f"\nResult saved to {out_file}")


if __name__ == "__main__":
    main()
