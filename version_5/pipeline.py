"""
Pipeline for base station outage impact assessment.

Stages:
  1  Load ticket
  2  Identify neighbor USIDs
  3  Coverage + attribute preprocessing (ThreadPoolExecutor)
  4  KPI Agent
  5  KPI Evaluator
  6  Final Assessment Agent
  7  Final Assessment Evaluator
  8  Human-review gate
  9  Summary table
"""

from __future__ import annotations

import base64
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
import pandas as pd

from preprocessing.attribute_preprocessing import run_attribute_preprocessing
from preprocessing.coverage_preprocessing import (
    get_neighbor_usids,
    run_coverage_preprocessing,
)

# ─── CONSTANTS ────────────────────────────────────────────────────────────────

MODEL       = "claude-sonnet-4-5"
SKILLS_DIR  = Path("/workspace/version_5/skills")
DATA_DIR    = Path("/workspace/version_3/data")
OUTPUT_BASE = Path("/workspace/version_5/outputs")

_client = anthropic.Anthropic()

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def load_skill(agent_name: str) -> str:
    return (SKILLS_DIR / agent_name / "skill.md").read_text()


def load_pdf_b64(agent_name: str) -> str | None:
    path = SKILLS_DIR / agent_name / "reference_document.pdf"
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode()


def load_image_b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def parse_analysis_block(text: str) -> dict | None:
    m = re.search(r"<analysis>(.*?)</analysis>", text, re.DOTALL)
    if not m:
        print("  [warn] No <analysis> block found in response")
        return None
    return parse_json_safe(m.group(1).strip())


def parse_json_safe(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [warn] JSON parse error: {e}")
        return None


def human_review_needed(fa_analysis: dict, fa_eval: dict) -> tuple[bool, list[str]]:
    reasons = []
    if fa_analysis.get("confidence") == "low":
        reasons.append("FA agent confidence is low")
    if fa_analysis.get("flags", {}).get("unresolved"):
        reasons.append(
            f"FA has {len(fa_analysis['flags']['unresolved'])} unresolved flag(s)"
        )
    if not fa_eval.get("pass", True):
        fail_reasons = fa_eval.get("fail_reasons") or []
        reasons.append(f"FA evaluator failed: {'; '.join(fail_reasons)}")
    return bool(reasons), reasons


# ─── DATA LOADING ─────────────────────────────────────────────────────────────

def load_ticket(ticket_id: str) -> dict:
    data = json.loads((DATA_DIR / "outage_tickets.json").read_text())
    for ticket in data["tickets"]:
        if ticket["ticket_id"] == ticket_id:
            return ticket
    raise ValueError(f"Ticket {ticket_id!r} not found in {DATA_DIR / 'outage_tickets.json'}")


def load_kpi_data(usid: str) -> list[dict]:
    df = pd.read_csv(DATA_DIR / "kpi_sector_timeseries.csv")
    return df[df["usid"] == usid].to_dict(orient="records")


def _parse_affected_sectors(ticket: dict) -> list[str] | None:
    """
    Convert the ticket's affected_sectors field into the format
    coverage_preprocessing expects (list of full sector IDs, or None for all).
    """
    raw = ticket.get("affected_sectors")
    usid = ticket["affected_usid"]

    if raw is None or str(raw).strip().upper() == "ALL":
        return None

    parts = [s.strip() for s in str(raw).split(",") if s.strip()]
    # Build full sector IDs: "S0" → "USID_XX_S0"
    return [f"{usid}_{p}" if not p.startswith(usid) else p for p in parts]


# ─── API CALL FUNCTIONS ───────────────────────────────────────────────────────

def call_kpi_agent(ticket: dict, neighbor_usids: list[str]) -> str:
    skill   = load_skill("kpi_agent")
    pdf_b64 = load_pdf_b64("kpi_agent")

    target_usid = ticket["affected_usid"]
    all_usids   = [target_usid] + neighbor_usids

    kpi_sections = []
    for usid in all_usids:
        rows  = load_kpi_data(usid)
        label = "TARGET" if usid == target_usid else "BACKUP"
        kpi_sections.append(
            f"=== KPI Data: {usid} ({label}) — {len(rows)} rows ===\n"
            + json.dumps(rows, indent=2)
        )

    user_text = (
        f"Ticket context:\n{json.dumps(ticket, indent=2)}\n\n"
        + "\n\n".join(kpi_sections)
    )

    content: list[dict] = []
    if pdf_b64:
        content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
        })
    content.append({"type": "text", "text": user_text})

    response = _client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=skill,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text


def call_kpi_evaluator(ticket: dict, kpi_output: str) -> dict | None:
    skill = load_skill("kpi_evaluator")

    user_text = (
        f"Ticket context:\n{json.dumps(ticket, indent=2)}\n\n"
        f"KPI Agent output:\n{kpi_output}"
    )

    response = _client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=skill,
        messages=[{"role": "user", "content": user_text}],
    )
    result = parse_json_safe(response.content[0].text)
    if result is None:
        print("  [error] KPI evaluator returned unparseable output")
    return result


def call_final_assessment(
    ticket: dict,
    coverage_result: dict,
    attribute_result: dict,
    kpi_output: str,
    map_paths: dict,
) -> str:
    skill   = load_skill("final_assessment")
    pdf_b64 = load_pdf_b64("final_assessment")

    content: list[dict] = []

    if pdf_b64:
        content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
        })

    for map_name, map_path in map_paths.items():
        content.append({"type": "text", "text": f"[Map: {map_name}]"})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": load_image_b64(map_path),
            },
        })

    # Exclude map_paths from serialized coverage to avoid path noise in the text block
    coverage_for_text = {k: v for k, v in coverage_result.items() if k != "map_paths"}

    user_text = (
        f"Ticket context:\n{json.dumps(ticket, indent=2)}\n\n"
        f"=== Coverage Evidence ===\n{json.dumps(coverage_for_text, indent=2)}\n\n"
        f"=== Attribute Evidence ===\n{json.dumps(attribute_result, indent=2)}\n\n"
        f"=== KPI Agent Output ===\n{kpi_output}"
    )
    content.append({"type": "text", "text": user_text})

    response = _client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=skill,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text


def call_final_assessment_evaluator(
    ticket: dict,
    coverage_result: dict,
    attribute_result: dict,
    kpi_output: str,
    fa_output: str,
) -> dict | None:
    skill = load_skill("final_assessment_evaluator")

    coverage_for_text = {k: v for k, v in coverage_result.items() if k != "map_paths"}

    user_text = (
        f"Ticket context:\n{json.dumps(ticket, indent=2)}\n\n"
        f"=== Coverage Evidence ===\n{json.dumps(coverage_for_text, indent=2)}\n\n"
        f"=== Attribute Evidence ===\n{json.dumps(attribute_result, indent=2)}\n\n"
        f"=== KPI Agent Output ===\n{kpi_output}\n\n"
        f"=== Final Assessment Output ===\n{fa_output}"
    )

    response = _client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=skill,
        messages=[{"role": "user", "content": user_text}],
    )
    result = parse_json_safe(response.content[0].text)
    if result is None:
        print("  [error] FA evaluator returned unparseable output")
    return result


# ─── MAIN PIPELINE ────────────────────────────────────────────────────────────

def run_pipeline(ticket_id: str) -> dict:
    print(f"\n{'=' * 60}")
    print(f"  Pipeline: {ticket_id}")
    print(f"{'=' * 60}\n")

    # STEP 1 — Load ticket
    print("[1/9] Loading ticket...")
    ticket           = load_ticket(ticket_id)
    usid             = ticket["affected_usid"]
    outage_type      = ticket["outage_type"]
    start_utc        = ticket.get("outage_start_utc")
    end_utc          = ticket.get("outage_end_utc")
    affected_sectors = _parse_affected_sectors(ticket)
    print(f"      USID={usid}  type={outage_type}  start={start_utc}  end={end_utc}")
    print(f"      affected_sectors={affected_sectors}")

    # STEP 2 — Identify neighbor USIDs
    print("[2/9] Identifying neighbor USIDs...")
    neighbor_usids = get_neighbor_usids(usid)
    print(f"      Neighbors: {neighbor_usids}")

    # STEP 3 — Coverage + attribute preprocessing
    # Attribute depends on coverage output, so coverage runs first.
    # Both are submitted to the pool to keep the executor pattern as specified.
    print("[3/9] Running preprocessing...")
    output_dir = str(OUTPUT_BASE / ticket_id / "coverage")

    with ThreadPoolExecutor(max_workers=2) as pool:
        coverage_result  = pool.submit(
            run_coverage_preprocessing, usid, affected_sectors, output_dir
        ).result()
        attribute_result = pool.submit(
            run_attribute_preprocessing,
            usid,
            neighbor_usids,
            coverage_result["per_backup"],
        ).result()

    map_paths = coverage_result["map_paths"]
    print(f"      Maps: {list(map_paths.keys())}")
    print(f"      Affected pixels: {coverage_result['coverage_hole']['affected_coordinate_count']}")

    # STEP 4 — KPI Agent
    print("[4/9] Calling KPI Agent...")
    kpi_output   = call_kpi_agent(ticket, neighbor_usids)
    kpi_analysis = parse_analysis_block(kpi_output)
    kpi_conf     = (kpi_analysis or {}).get("confidence", "N/A")
    print(f"      KPI confidence: {kpi_conf}")

    # STEP 5 — KPI Evaluator
    print("[5/9] Calling KPI Evaluator...")
    kpi_eval = call_kpi_evaluator(ticket, kpi_output)
    if kpi_eval:
        kpi_overall = kpi_eval.get("overall", 0.0)
        kpi_pass    = kpi_eval.get("pass", False)
        print(f"      overall={kpi_overall:.2f}  pass={kpi_pass}")
        if not kpi_pass:
            print(f"      [warn] KPI eval failed: {kpi_eval.get('fail_reasons')} — continuing")
    else:
        print("      [warn] KPI evaluator parse failed — continuing")

    # STEP 6 — Final Assessment Agent
    print("[6/9] Calling Final Assessment Agent...")
    fa_output   = call_final_assessment(
        ticket, coverage_result, attribute_result, kpi_output, map_paths
    )
    fa_analysis = parse_analysis_block(fa_output)
    fa_conf     = (fa_analysis or {}).get("confidence", "N/A")
    fa_severity = (fa_analysis or {}).get("overall_severity", "N/A")
    print(f"      severity={fa_severity}  confidence={fa_conf}")

    # STEP 7 — Final Assessment Evaluator
    print("[7/9] Calling Final Assessment Evaluator...")
    fa_eval = call_final_assessment_evaluator(
        ticket, coverage_result, attribute_result, kpi_output, fa_output
    )
    if fa_eval:
        fa_overall = fa_eval.get("overall", 0.0)
        fa_pass    = fa_eval.get("pass", False)
        print(f"      overall={fa_overall:.2f}  pass={fa_pass}")
        if not fa_pass:
            print(f"      FA eval failed: {fa_eval.get('fail_reasons')}")
    else:
        print("      [warn] FA evaluator parse failed")

    # STEP 8 — Human review gate
    print("[8/9] Checking human review requirement...")
    needs_review, review_reasons = human_review_needed(
        fa_analysis or {}, fa_eval or {}
    )
    if needs_review:
        print("      *** HUMAN REVIEW REQUIRED ***")
        for reason in review_reasons:
            print(f"        - {reason}")
    else:
        print("      Human review not required.")

    # STEP 9 — Summary table
    print("[9/9] Summary\n")
    col = "{:<28} {:<8} {:<8} {}"
    print("  " + col.format("Stage", "Pass", "Score", "Confidence"))
    print("  " + "-" * 58)

    def _row(label, eval_dict, conf):
        if eval_dict is None:
            return f"  {label:<28} {'ERR':<8} {'N/A':<8} {conf}"
        p = str(eval_dict.get("pass", "?"))
        s = f"{eval_dict.get('overall', 0.0):.2f}"
        return f"  {label:<28} {p:<8} {s:<8} {conf}"

    print(_row("KPI Agent",         kpi_eval, kpi_conf))
    print(_row("Final Assessment",  fa_eval,  fa_conf))
    print()

    return {
        "ticket_id":        ticket_id,
        "ticket":           ticket,
        "coverage_result":  coverage_result,
        "attribute_result": attribute_result,
        "kpi_output":       kpi_output,
        "kpi_analysis":     kpi_analysis,
        "kpi_eval":         kpi_eval,
        "fa_output":        fa_output,
        "fa_analysis":      fa_analysis,
        "fa_eval":          fa_eval,
        "human_review":     {"needed": needs_review, "reasons": review_reasons},
    }


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ticket_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not ticket_id:
        print("Usage: python pipeline.py <ticket_id>")
        sys.exit(1)
    run_pipeline(ticket_id)
