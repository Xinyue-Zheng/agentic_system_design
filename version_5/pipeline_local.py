"""
Pipeline for base station outage impact assessment — local POC version.

Changes from pipeline.py:
  - Tickets read from CSV (ticket_samples_cases.csv) with columns:
      USID, ALARM_TIME, RESOLVED_TIME  (full-outage only, no sector field)
  - API calls use OpenAI-compatible client (streaming)
  - Coverage preprocessing uses coverage_preprocessing_new_format.py
  - No MCP server; all data and outputs are stored locally

Stages:
  1  Load ticket from CSV
  2  Identify neighbor USIDs (new-format coverage data)
  3  Coverage + attribute preprocessing in parallel
  4  KPI Agent
  5  KPI Evaluator
  6  Final Assessment Agent
  7  Final Assessment Evaluator
  8  Human-review gate
  9  Summary + save all outputs as JSON
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from openai import OpenAI

from preprocessing.attribute_preprocessing import run_attribute_preprocessing
from preprocessing.coverage_preprocessing_new_format import (
    get_neighbor_usids,
    load_enodeb_usid_map,
    run_coverage_preprocessing_new,
)

# ─── CONFIGURATION  (edit these for your environment) ─────────────────────────

# OpenAI-compatible endpoint
BASE_URL = "https://your-endpoint/v1"   # replace with actual endpoint
API_KEY  = os.environ.get("OPENAI_API_KEY", "your-api-key")
MODEL    = "your-model-name"            # replace with actual model name

# Sampling
TEMPERATURE = 0.5
TOP_P       = 0.9
MAX_TOKENS  = 4096    # for agents
EVAL_TOKENS = 2048    # for evaluators

# Paths
SKILLS_DIR        = Path("/workspace/version_5/skills")
TICKET_CSV        = Path("/workspace/version_5/data/ticket_samples_cases.csv")
COVERAGE_DATA_ROOT = Path("/workspace/version_5/data/coverage")   # root with USID subfolders
ENODEB_CSV        = None   # e.g. Path("/workspace/version_5/data/enodeb_usid.csv"), or None
KPI_CSV           = Path("/workspace/version_3/data/kpi_sector_timeseries.csv")
OUTPUT_BASE       = Path("/workspace/version_5/outputs")

# ─── CLIENT ───────────────────────────────────────────────────────────────────

_client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def load_skill(agent_name: str) -> str:
    return (SKILLS_DIR / agent_name / "skill.md").read_text()


def load_image_b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def _image_block(b64_data: str) -> dict:
    """OpenAI image_url content block from base64 PNG data."""
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{b64_data}"},
    }


def _call_api(system: str, user_content: list | str, max_tokens: int = MAX_TOKENS) -> str:
    """
    Call the OpenAI-compatible API with streaming.
    system      : system prompt string
    user_content: string or list of content blocks (text / image_url dicts)
    Returns the full response text.
    """
    if isinstance(user_content, str):
        user_content = [{"type": "text", "text": user_content}]

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_content},
    ]

    stream = _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=TEMPERATURE,
        top_p=TOP_P,
        max_tokens=max_tokens,
        stream=True,
    )

    text = ""
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            text += delta
    return text


def parse_analysis_block(text: str) -> dict | None:
    m = re.search(r"<analysis>(.*?)</analysis>", text, re.DOTALL)
    if not m:
        print("  [warn] No <analysis> block found in response")
        return None
    return parse_json_safe(m.group(1).strip())


def parse_json_safe(text: str) -> dict | None:
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"^```\s*$",         "", text.strip(), flags=re.MULTILINE)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try extracting the first {...} block
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    print(f"  [warn] JSON parse failed")
    return None


def save_output(path: Path, content: str | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, dict):
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False))
    else:
        path.write_text(content, encoding="utf-8")
    print(f"  [saved] {path}")


def human_review_needed(fa_analysis: dict, fa_eval: dict) -> tuple[bool, list[str]]:
    reasons = []
    if fa_analysis.get("confidence") == "low":
        reasons.append("FA agent confidence is low")
    if fa_analysis.get("flags", {}).get("unresolved"):
        n = len(fa_analysis["flags"]["unresolved"])
        reasons.append(f"FA has {n} unresolved flag(s)")
    if not fa_eval.get("pass", True):
        fail_reasons = fa_eval.get("fail_reasons") or []
        reasons.append(f"FA evaluator failed: {'; '.join(fail_reasons)}")
    return bool(reasons), reasons


# ─── TICKET LOADING ───────────────────────────────────────────────────────────

def load_ticket(ticket_id: str) -> dict:
    """
    Load a single ticket row from the CSV by matching TICKET_ID column.
    Normalises fields to a standard internal dict:
      ticket_id, usid, alarm_time, resolved_time, outage_type
    """
    df = pd.read_csv(TICKET_CSV, dtype=str)
    df.columns = df.columns.str.strip()

    # Support common ticket-id column names
    id_col = _find_column(df, ["TICKET_ID", "ticket_id", "ID", "id"])
    if id_col:
        match = df[df[id_col].str.strip() == str(ticket_id)]
    else:
        raise ValueError(f"No ticket-ID column found in {TICKET_CSV}")

    if match.empty:
        raise ValueError(f"Ticket {ticket_id!r} not found in {TICKET_CSV}")

    return _row_to_ticket(match.iloc[0])


def list_tickets() -> list[str]:
    """Return all ticket IDs from the CSV (for batch runs)."""
    df = pd.read_csv(TICKET_CSV, dtype=str)
    df.columns = df.columns.str.strip()
    id_col = _find_column(df, ["TICKET_ID", "ticket_id", "ID", "id"])
    if not id_col:
        raise ValueError(f"No ticket-ID column found in {TICKET_CSV}")
    return df[id_col].str.strip().tolist()


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _row_to_ticket(row: pd.Series) -> dict:
    """Convert a CSV row to the internal ticket dict."""
    usid         = row.get("USID",          row.get("usid", "")).strip()
    alarm_time   = row.get("ALARM_TIME",    row.get("alarm_time", "")).strip()
    resolved_time = row.get("RESOLVED_TIME", row.get("resolved_time", "")).strip()
    id_col_val   = row.get("TICKET_ID",     row.get("ticket_id", row.get("ID", ""))).strip()

    # Derive a readable ticket ID if none present
    ticket_id = id_col_val or f"{usid}_{alarm_time[:10]}"

    return {
        "ticket_id":    ticket_id,
        "usid":         usid,
        "outage_type":  "Full Outage",     # all cases in this CSV are full outage
        "alarm_time":   alarm_time,
        "resolved_time": resolved_time,
        # Expose the raw row as extra context for agents
        "raw": {k: str(v) for k, v in row.items()},
    }


# ─── KPI DATA LOADING ─────────────────────────────────────────────────────────

def load_kpi_data(usid: str) -> list[dict]:
    """Return historical KPI rows for a given USID from the timeseries CSV."""
    df = pd.read_csv(KPI_CSV, dtype=str)
    df.columns = df.columns.str.strip()
    usid_col = _find_column(df, ["usid", "USID"])
    if not usid_col:
        raise ValueError(f"No USID column found in {KPI_CSV}")
    rows = df[df[usid_col].str.strip() == usid]
    return rows.to_dict(orient="records")


# ─── API CALL FUNCTIONS ───────────────────────────────────────────────────────

def call_kpi_agent(ticket: dict, neighbor_usids: list[str]) -> str:
    skill = load_skill("kpi_agent")

    target_usid = ticket["usid"]
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

    return _call_api(skill, user_text, max_tokens=MAX_TOKENS)


def call_kpi_evaluator(ticket: dict, kpi_output: str) -> dict | None:
    skill = load_skill("kpi_evaluator")

    user_text = (
        f"Ticket context:\n{json.dumps(ticket, indent=2)}\n\n"
        f"KPI Agent output:\n{kpi_output}"
    )

    raw = _call_api(skill, user_text, max_tokens=EVAL_TOKENS)
    result = parse_json_safe(raw)
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
    skill = load_skill("final_assessment")

    # Build a multimodal content list: maps first, then text
    content: list[dict] = []

    for map_name, map_path in map_paths.items():
        content.append({"type": "text", "text": f"[Map: {map_name}]"})
        content.append(_image_block(load_image_b64(map_path)))

    coverage_for_text = {k: v for k, v in coverage_result.items() if k != "map_paths"}

    user_text = (
        f"Ticket context:\n{json.dumps(ticket, indent=2)}\n\n"
        f"=== Coverage Evidence ===\n{json.dumps(coverage_for_text, indent=2)}\n\n"
        f"=== Attribute Evidence ===\n{json.dumps(attribute_result, indent=2)}\n\n"
        f"=== KPI Agent Output ===\n{kpi_output}"
    )
    content.append({"type": "text", "text": user_text})

    return _call_api(skill, content, max_tokens=MAX_TOKENS)


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

    raw = _call_api(skill, user_text, max_tokens=EVAL_TOKENS)
    result = parse_json_safe(raw)
    if result is None:
        print("  [error] FA evaluator returned unparseable output")
    return result


# ─── MAIN PIPELINE ────────────────────────────────────────────────────────────

def run_pipeline(ticket_id: str) -> dict:
    print(f"\n{'=' * 60}")
    print(f"  Pipeline: {ticket_id}")
    print(f"{'=' * 60}\n")

    out_dir = OUTPUT_BASE / ticket_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # STEP 1 — Load ticket from CSV
    print("[1/9] Loading ticket...")
    ticket = load_ticket(ticket_id)
    usid   = ticket["usid"]
    print(f"      USID={usid}  alarm={ticket['alarm_time']}  resolved={ticket['resolved_time']}")
    save_output(out_dir / "ticket.json", ticket)

    # STEP 2 — Identify neighbor USIDs from new coverage data
    print("[2/9] Identifying neighbor USIDs...")
    enodeb_map = load_enodeb_usid_map(str(ENODEB_CSV)) if ENODEB_CSV and ENODEB_CSV.exists() else {}
    neighbor_usids = get_neighbor_usids(str(COVERAGE_DATA_ROOT), usid, enodeb_map)
    print(f"      Neighbors: {neighbor_usids}")

    # STEP 3 — Coverage + attribute preprocessing
    # Attribute needs coverage per_backup output, so coverage runs first.
    # Both submitted to the ThreadPoolExecutor as specified.
    print("[3/9] Running preprocessing...")
    coverage_output_dir = str(out_dir / "coverage")

    with ThreadPoolExecutor(max_workers=2) as pool:
        coverage_result = pool.submit(
            run_coverage_preprocessing_new,
            str(COVERAGE_DATA_ROOT),
            usid,
            str(ENODEB_CSV) if ENODEB_CSV and ENODEB_CSV.exists() else None,
            None,                  # full outage → affected_sectors = None
            coverage_output_dir,
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

    # Save preprocessing results (exclude map coords to keep file readable)
    coverage_summary = {k: v for k, v in coverage_result.items() if k != "coverage_hole_coords"}
    save_output(out_dir / "coverage_result.json",   coverage_summary)
    save_output(out_dir / "attribute_result.json",  attribute_result)

    # STEP 4 — KPI Agent
    print("[4/9] Calling KPI Agent...")
    kpi_output   = call_kpi_agent(ticket, neighbor_usids)
    kpi_analysis = parse_analysis_block(kpi_output)
    kpi_conf     = (kpi_analysis or {}).get("confidence", "N/A")
    print(f"      KPI confidence: {kpi_conf}")
    save_output(out_dir / "kpi_agent_output.txt",  kpi_output)
    if kpi_analysis:
        save_output(out_dir / "kpi_analysis.json", kpi_analysis)

    # STEP 5 — KPI Evaluator
    print("[5/9] Calling KPI Evaluator...")
    kpi_eval = call_kpi_evaluator(ticket, kpi_output)
    if kpi_eval:
        kpi_overall = kpi_eval.get("overall", 0.0)
        kpi_pass    = kpi_eval.get("pass", False)
        print(f"      overall={kpi_overall:.2f}  pass={kpi_pass}")
        if not kpi_pass:
            print(f"      [warn] KPI eval failed: {kpi_eval.get('fail_reasons')} — continuing")
        save_output(out_dir / "kpi_eval.json", kpi_eval)
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
    save_output(out_dir / "fa_agent_output.txt",  fa_output)
    if fa_analysis:
        save_output(out_dir / "fa_analysis.json", fa_analysis)

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
        save_output(out_dir / "fa_eval.json", fa_eval)
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

    human_review_result = {"needed": needs_review, "reasons": review_reasons}
    save_output(out_dir / "human_review.json", human_review_result)

    # STEP 9 — Summary
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

    print(_row("KPI Agent",         kpi_eval,  kpi_conf))
    print(_row("Final Assessment",  fa_eval,   fa_conf))
    print()
    print(f"  Outputs saved to: {out_dir}")
    print()

    result = {
        "ticket_id":        ticket_id,
        "ticket":           ticket,
        "coverage_result":  coverage_summary,
        "attribute_result": attribute_result,
        "kpi_output":       kpi_output,
        "kpi_analysis":     kpi_analysis,
        "kpi_eval":         kpi_eval,
        "fa_output":        fa_output,
        "fa_analysis":      fa_analysis,
        "fa_eval":          fa_eval,
        "human_review":     human_review_result,
    }
    save_output(out_dir / "pipeline_result.json", {
        k: v for k, v in result.items()
        if k not in ("kpi_output", "fa_output")   # raw text already saved separately
    })
    return result


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ticket_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not ticket_id:
        print("Usage: python pipeline_local.py <ticket_id>")
        print()
        print("To run all tickets in the CSV:")
        print("  for tid in $(python -c \"")
        print("    from pipeline_local import list_tickets")
        print("    print(*list_tickets(), sep='\\n')\"); do")
        print("      python pipeline_local.py $tid")
        print("  done")
        sys.exit(1)
    run_pipeline(ticket_id)
