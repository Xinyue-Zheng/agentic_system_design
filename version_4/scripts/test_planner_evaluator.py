import json
import pathlib
import subprocess
import sys
import anthropic

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_planner import (
    TICKET_FULL,
    TICKET_PARTIAL,
    call_planner_with_pdf,
    call_planner_api_with_pdf,
    load_pdf_as_base64,
    extract_json,
    MODEL,
    MAX_TOKENS,
)

OUTPUT_DIR = pathlib.Path(__file__).parent.parent / "output"
PLANNER_SKILL_PATH = pathlib.Path(__file__).parent.parent / "skills" / "planner" / "skill.md"
EVALUATOR_SKILL_PATH = pathlib.Path(__file__).parent.parent / "skills" / "planner_evaluator" / "skill.md"
PLANNER_PDF = "version_4/skills/reference_document.pdf"
EVALUATOR_PDF = "version_4/skills/reference_document.pdf"


AGENTS = ["coverage_agent", "kpi_agent", "attribute_agent"]


def print_diff(result_full: dict | None, result_partial: dict | None) -> None:
    print("\n── QUESTION DIFF ──")
    for agent in AGENTS:
        print(f"\n{agent}:")
        aq_full    = (result_full    or {}).get("assigned_questions", {}).get(agent, {})
        aq_partial = (result_partial or {}).get("assigned_questions", {}).get(agent, {})
        q_full    = aq_full.get("question", "<missing>")    if isinstance(aq_full, dict)    else "<error>"
        q_partial = aq_partial.get("question", "<missing>") if isinstance(aq_partial, dict) else "<error>"
        t_full    = aq_full.get("recommended_tools", [])    if isinstance(aq_full, dict)    else []
        t_partial = aq_partial.get("recommended_tools", []) if isinstance(aq_partial, dict) else []
        print(f"  Full Outage question:    {q_full}")
        print(f"  Partial Outage question: {q_partial}")
        print(f"  Full Outage tools:    {t_full}")
        print(f"  Partial Outage tools: {t_partial}")


def call_evaluator_api_with_pdf(
    system: str, ticket: dict, planner_output: dict, pdf_path: str
) -> tuple[dict | None, str]:
    client = anthropic.Anthropic()
    pdf_data = load_pdf_as_base64(pdf_path)
    user_text = (
        "Evaluate this Planner output.\n\n"
        "Original ticket:\n" + json.dumps(ticket, indent=2) + "\n\n"
        "Planner output:\n" + json.dumps(planner_output, indent=2)
    )
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
                            "Use this document to check whether the Planner's "
                            "sub-questions cover the key impact dimensions."
                        ),
                    },
                    {
                        "type": "text",
                        "text": user_text,
                    },
                ],
            }
        ],
    )
    raw = message.content[0].text.strip()
    return extract_json(raw), raw


def call_evaluator_with_pdf(
    system: str, ticket: dict, planner_output: dict, pdf_path: str
) -> tuple[dict | None, str]:
    pdf_data = load_pdf_as_base64(pdf_path)
    user_message = (
        "<document>\n"
        "<title>Outage Assessment Framework</title>\n"
        "<context>Use this document to check whether the Planner's "
        "sub-questions cover the key impact dimensions.</context>\n"
        f"<source type=\"base64\" media_type=\"application/pdf\">{pdf_data}</source>\n"
        "</document>\n\n"
        "Evaluate this Planner output.\n\n"
        "Original ticket:\n" + json.dumps(ticket, indent=2) + "\n\n"
        "Planner output:\n" + json.dumps(planner_output, indent=2)
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


def print_ticket_result(
    ticket: dict,
    planner_result: dict | None,
    eval_result: dict | None,
    eval_raw: str,
) -> None:
    print(f"\n── TICKET {ticket['ticket_id']} ({ticket['outage_type']}) ──")
    print("PLANNER OUTPUT:")
    print(json.dumps(planner_result, indent=2) if planner_result else "<parse error>")
    print("\nEVALUATOR RESULT:")
    if eval_result:
        print(json.dumps(eval_result, indent=2))
    else:
        print(f"ERROR: could not parse evaluator response\n{eval_raw}")


def print_summary(rows: list[tuple[str, dict | None]]) -> None:
    print("\n── SUMMARY ──")
    cols = f"{'ticket_id':<26} {'goal_align':>10} {'complete':>8} {'specific':>8} {'tool_appr':>9} {'overall':>7} {'pass':>5}"
    print(cols)
    print("─" * len(cols))
    for ticket_id, er in rows:
        if er is None:
            print(f"{ticket_id:<26} {'ERROR':>10}")
            continue
        ga = er.get("goal_alignment", {}).get("score", "?")
        co = er.get("completeness", {}).get("score", "?")
        sp = er.get("specificity", {}).get("score", "?")
        ta = er.get("tool_appropriateness", {}).get("score", "?")
        ov = er.get("overall", "?")
        pa = er.get("pass", "?")
        print(f"{ticket_id:<26} {ga!s:>10} {co!s:>8} {sp!s:>8} {ta!s:>9} {ov!s:>7} {pa!s:>5}")


def main() -> None:
    planner_system = PLANNER_SKILL_PATH.read_text()
    evaluator_system = EVALUATOR_SKILL_PATH.read_text()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    planner_results = {}
    for ticket in [TICKET_FULL, TICKET_PARTIAL]:
        tid = ticket["ticket_id"]
        planner_result, planner_raw = call_planner_with_pdf(planner_system, ticket, PLANNER_PDF)
        eval_result, eval_raw = call_evaluator_with_pdf(
            evaluator_system, ticket, planner_result or {}, EVALUATOR_PDF
        )
        print_ticket_result(ticket, planner_result, eval_result, eval_raw)
        summary_rows.append((tid, eval_result))
        planner_results[ticket["outage_type"]] = planner_result

        (OUTPUT_DIR / f"planner_{tid}.json").write_text(planner_raw)
        (OUTPUT_DIR / f"evaluator_{tid}.json").write_text(eval_raw)
        print(f"Saved planner and evaluator output for {tid}")

    print_diff(planner_results.get("Full Outage"), planner_results.get("Partial Outage"))
    print_summary(summary_rows)


if __name__ == "__main__":
    main()
