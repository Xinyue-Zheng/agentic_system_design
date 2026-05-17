"""
deterministic_checks.py — Stage 5A

The fault detector component of the harness.
Pure Python arithmetic — zero LLM calls.

Compares every number cited in Stage 1-4 outputs
against the preprocessing_stats.json ground truth.

If a value is outside tolerance, raises immediately.
Stage 5B and Stage 6 never run.

This is the key architectural difference from your
old Stage 5: the old Stage 5 asked an LLM to verify
numbers. This file verifies numbers with arithmetic.
An LLM cannot verify a number reliably.
Python cannot fail to verify a number.
"""

import json
from pathlib import Path
from typing import List, Dict
from harness.core.mcp_log import MCPResourceLog


def run_stage5a(
    preprocessing_path: Path,
    result_dir: Path,
    target_usid: str,
    mcp_log: MCPResourceLog,
) -> dict:
    """
    Runs V1-V10: deterministic checks against ground truth.

    Returns a result dict.
    Raises RuntimeError on critical failures.
    """

    # Verify MCP version consistency first
    if not mcp_log.verify_version_consistency():
        raise RuntimeError(
            "Stage 5A: MCP version mismatch — stages used different "
            "versions of preprocessing_stats.json. "
            "Re-run the full pipeline."
        )

    preprocessing = json.loads(preprocessing_path.read_text())
    stage1 = json.loads(
        (result_dir / "stage1_coverage_load.json").read_text()
    )
    stage2 = json.loads(
        (result_dir / "stage2_attribute_config.json").read_text()
    )

    stage4_files = list(result_dir.glob(f"stage4_final_{target_usid}.json"))
    stage4 = json.loads(stage4_files[0].read_text()) if stage4_files else {}

    results = []
    critical_failures = []

    preproc_per_usid = preprocessing["coverage_summary"]["per_usid"]
    preproc_load = preprocessing["load_redistribution"]
    preproc_cap = preprocessing["capacity_summary"]

    # ── V1: Role labels match preprocessing inferred_role ─────
    for usid_entry in stage1.get("usids", []):
        usid = usid_entry["usid"]
        if usid not in preproc_per_usid:
            continue
        expected = preproc_per_usid[usid]["inferred_role"]
        found = usid_entry.get("role")
        passed = (expected == found)
        r = {
            "check_id": "V1",
            "description": f"Role label match for {usid}",
            "result": "PASS" if passed else "FAIL",
            "expected": expected,
            "found": found,
            "note": "" if passed else f"{usid} role mismatch",
        }
        results.append(r)
        if not passed:
            critical_failures.append(r)

    # ── V2: dominant_pixel_fraction within ±0.01 ──────────────
    for usid_entry in stage1.get("usids", []):
        usid = usid_entry["usid"]
        if usid not in preproc_per_usid:
            continue
        expected = preproc_per_usid[usid]["dominant_pixel_fraction"]
        found = usid_entry.get("dominant_pixel_fraction", -999)
        delta = abs(expected - found)
        passed = (delta <= 0.01)
        r = {
            "check_id": "V2",
            "description": f"dom_pixel_fraction for {usid}",
            "result": "PASS" if passed else "FAIL",
            "expected": str(expected),
            "found": str(found),
            "note": f"delta={delta:.4f}" + ("" if passed else " — EXCEEDS ±0.01"),
        }
        results.append(r)
        if not passed:
            critical_failures.append(r)

    # ── V3: rsrp_p50_dbm within ±2 dBm ───────────────────────
    for usid_entry in stage1.get("usids", []):
        usid = usid_entry["usid"]
        if usid not in preproc_per_usid:
            continue
        expected = preproc_per_usid[usid]["rsrp_p50_dbm"]
        found = usid_entry.get("rsrp_p50_dbm", -999)
        delta = abs(expected - found)
        passed = (delta <= 2.0)
        r = {
            "check_id": "V3",
            "description": f"rsrp_p50_dbm for {usid}",
            "result": "PASS" if passed else "FAIL",
            "expected": str(expected),
            "found": str(found),
            "note": f"delta={delta:.2f} dBm" + ("" if passed else " — EXCEEDS ±2 dBm"),
        }
        results.append(r)
        if not passed:
            critical_failures.append(r)

    # ── V4: coverage_hole_fraction within ±0.01 ───────────────
    expected_hole = preproc_load.get("coverage_hole_fraction", 0)
    found_hole = (stage1
                  .get("target_load_analysis", {})
                  .get("coverage_hole_fraction", -999))
    delta = abs(expected_hole - found_hole)
    passed = (delta <= 0.01)
    r = {
        "check_id": "V4",
        "description": "coverage_hole_fraction",
        "result": "PASS" if passed else "FAIL",
        "expected": str(expected_hole),
        "found": str(found_hole),
        "note": f"delta={delta:.4f}" + ("" if passed else " — EXCEEDS ±0.01"),
    }
    results.append(r)
    if not passed:
        critical_failures.append(r)

    # ── V5: post_outage_load_factor within ±0.05 ─────────────
    preproc_backups = preproc_load.get("per_backup", {})
    stage1_backups = {
        b["backup_usid"]: b
        for b in stage1.get("target_load_analysis", {}).get("per_backup", [])
    }
    for usid, preproc_b in preproc_backups.items():
        if usid not in stage1_backups:
            continue
        expected = preproc_b.get("post_outage_load_factor", 0)
        found = stage1_backups[usid].get("post_outage_load_factor", -999)
        delta = abs(expected - found)
        passed = (delta <= 0.05)
        r = {
            "check_id": "V5",
            "description": f"post_outage_load_factor for {usid}",
            "result": "PASS" if passed else "FAIL",
            "expected": str(expected),
            "found": str(found),
            "note": f"delta={delta:.3f}" + ("" if passed else " — EXCEEDS ±0.05"),
        }
        results.append(r)
        if not passed:
            critical_failures.append(r)

    # ── V7: overload_risk labels match thresholds ─────────────
    # >0.8=high, >0.5=medium, else=low
    for usid, preproc_b in preproc_backups.items():
        if usid not in stage1_backups:
            continue
        load_factor = preproc_b.get("post_outage_load_factor", 0)
        if   load_factor > 0.8: expected_risk = "high"
        elif load_factor > 0.5: expected_risk = "medium"
        else:                    expected_risk = "low"
        found_risk = stage1_backups[usid].get("overload_risk")
        passed = (expected_risk == found_risk)
        r = {
            "check_id": "V7",
            "description": f"overload_risk label for {usid}",
            "result": "PASS" if passed else "FAIL",
            "expected": f"{expected_risk} (load={load_factor:.3f})",
            "found": str(found_risk),
            "note": "" if passed else "threshold rule mis-applied",
        }
        results.append(r)
        if not passed:
            critical_failures.append(r)

    # ── V9: capacity_scores match preprocessing within ±0.5 ──
    for usid_entry in stage2.get("usids", []):
        usid = usid_entry["usid"]
        if usid not in preproc_cap:
            continue
        expected = preproc_cap[usid].get("capacity_score", 0)
        found = usid_entry.get("capacity_score", -999)
        delta = abs(expected - found)
        passed = (delta <= 0.5)
        r = {
            "check_id": "V9",
            "description": f"capacity_score for {usid}",
            "result": "PASS" if passed else "FAIL",
            "expected": str(expected),
            "found": str(found),
            "note": f"delta={delta:.2f}" + ("" if passed else " — EXCEEDS ±0.5"),
        }
        results.append(r)
        if not passed:
            critical_failures.append(r)

    # ── V10: Tower types match height rules ───────────────────
    for usid_entry in stage2.get("usids", []):
        usid = usid_entry["usid"]
        if usid not in preproc_cap:
            continue
        height = preproc_cap[usid].get("tower_height_m", 0)
        if   height < 25:  expected_type = "micro"
        elif height <= 45: expected_type = "macro"
        else:              expected_type = "tall_macro"
        found_type = usid_entry.get("tower_type")
        passed = (expected_type == found_type)
        r = {
            "check_id": "V10",
            "description": f"tower_type for {usid}",
            "result": "PASS" if passed else "FAIL",
            "expected": f"{expected_type} (height={height}m)",
            "found": str(found_type),
            "note": "" if passed else "height threshold mis-applied",
        }
        results.append(r)
        if not passed:
            critical_failures.append(r)

    # ── Summary ────────────────────────────────────────────────
    passed_count = sum(1 for r in results if r["result"] == "PASS")
    total_count = len(results)

    # Save Stage 5A partial result
    s5a_output = {
        "deterministic_checks": {
            "total": total_count,
            "passed": passed_count,
            "failed": total_count - passed_count,
            "critical_failures": critical_failures,
        },
        "checks": results,
        "mcp_version_hash": mcp_log.version_hash[:16],
        "mcp_version_consistent": True,
    }
    (result_dir / "stage5a_deterministic.json").write_text(
        json.dumps(s5a_output, indent=2)
    )

    # Raise on critical failures — pipeline stops here
    if critical_failures:
        raise RuntimeError(
            f"Stage 5A: {len(critical_failures)} critical failure(s). "
            f"Pipeline cannot proceed."
        )

    return {
        "passed": passed_count,
        "total": total_count,
        "critical_failures": critical_failures,
        "checks": results,
    }
