"""
mcp_log.py — MCP resource server with query interface

Two access patterns:
  read_resource()   — reads specific named fields (for preprocessing)
  query_resource()  — agents describe what they need; MCP extracts it
                      more flexible, no hard-coded field paths

Every read is logged with timestamp and version hash.
Stage 5A reads this log to verify version consistency across stages.
"""

import json
import hashlib
import datetime
from pathlib import Path
from typing import List, Optional


class MCPResourceLog:

    def __init__(self, preprocessing_path: Path, result_dir: Path):
        self.preprocessing_path = preprocessing_path
        self.result_dir = result_dir
        self.log_path = result_dir / "mcp_access_log.json"

        content = preprocessing_path.read_bytes()
        self.version_hash = hashlib.sha256(content).hexdigest()
        self._data = {"preprocessing": json.loads(preprocessing_path.read_text())}
        self._log = []

    def register_stage_output(self, stage_id: str, file_path: Path):
        """
        Register a stage output file with MCP after the harness
        validates it. Agents can then query it by stage_id.
        """
        content = file_path.read_bytes()
        version = hashlib.sha256(content).hexdigest()
        self._data[stage_id] = json.loads(file_path.read_text())
        self._log_entry(
            reader="harness",
            resource=file_path.name,
            version=version[:16],
            fields=["registered"],
            query=None
        )

    def read_resource(self, resource_name: str, fields: List[str], reader: str) -> dict:
        """
        Read specific named fields from a resource.
        Used for preprocessing_stats.json where field names are stable.
        """
        source_key = "preprocessing" if "preprocessing" in resource_name else resource_name
        data = self._data.get(source_key, {})

        self._log_entry(reader=reader, resource=resource_name,
                        version=self.version_hash[:16], fields=fields, query=None)

        result = {}
        for field in fields:
            if field in data:
                result[field] = data[field]
            else:
                print(f"  [MCP] WARNING: field '{field}' not found in {resource_name}")
        return result

    def query_resource(self, resource_name: str, query: str, reader: str) -> dict:
        """
        Query a resource by describing what is needed.
        More flexible than read_resource — no hard-coded field paths.

        Example queries:
          "load redistribution verdict and per-backup overload risks"
          "worst zone severity and critical infrastructure flags"
          "capacity score and NSA 5G downgrade risk"

        The MCP server extracts the relevant fields based on the query.
        Each agent describes what it needs; MCP handles the extraction.
        This means schema changes in upstream stages do not break
        downstream stage code — only the MCP query logic needs updating.
        """
        source_key = "preprocessing" if "preprocessing" in resource_name else resource_name
        data = self._data.get(source_key, {})

        if not data:
            print(f"  [MCP] WARNING: resource '{resource_name}' not registered yet")
            return {}

        result = self._extract_by_query(data, query)

        self._log_entry(reader=reader, resource=resource_name,
                        version=self.version_hash[:16],
                        fields=list(result.keys()), query=query)

        print(f"  [MCP] {reader} QUERY '{resource_name}': {query[:60]}")
        return result

    def _extract_by_query(self, data: dict, query: str) -> dict:
        """
        Extracts fields from data based on a natural language query.
        Maps query intent to known field patterns.

        This is intentionally simple — a lookup table of query patterns
        to field extraction logic. In production this could be replaced
        with a proper semantic search or an LLM-based extractor.
        """
        query_lower = query.lower()
        result = {}

        # Load redistribution queries (Stage 3 needs from Stage 1)
        if any(k in query_lower for k in ["load", "redistribution", "verdict", "overload"]):
            if "target_load_analysis" in data:
                tla = data["target_load_analysis"]
                result["load_redistribution_verdict"] = tla.get("load_redistribution_verdict")
                result["coverage_hole_fraction"] = tla.get("coverage_hole_fraction")
                result["per_backup_overload_risks"] = {
                    b["backup_usid"]: {
                        "overload_risk": b.get("overload_risk"),
                        "post_outage_load_factor": b.get("post_outage_load_factor"),
                        "handover_quality": b.get("handover_quality"),
                    }
                    for b in tla.get("per_backup", [])
                }

        # Zone severity queries (Stage 4 needs from Stage 3)
        if any(k in query_lower for k in ["zone", "severity", "geographic", "impact"]):
            if "impact_zones" in data:
                result["impact_zones"] = data["impact_zones"]
                result["worst_zone_severity"] = data.get("worst_zone_severity")
                result["geographic_character"] = data.get("geographic_character")
                result["coverage_hole_geographic_assessment"] = data.get(
                    "coverage_hole_geographic_assessment")

        # Critical infrastructure queries
        if any(k in query_lower for k in ["critical", "infrastructure"]):
            if "impact_zones" in data:
                result["any_critical_infrastructure"] = any(
                    z.get("is_critical_infrastructure", False)
                    for z in data.get("impact_zones", [])
                )

        # Capacity queries (Stage 4 needs from Stage 2)
        if any(k in query_lower for k in ["capacity", "5g", "nsa", "downgrade"]):
            result["overall_capacity_verdict"] = data.get("overall_capacity_verdict")
            result["nsa_5g_downgrade_risk"] = data.get("nsa_5g_downgrade_risk")
            result["key_findings_for_stage4"] = data.get("key_findings_for_stage4", [])

        # Key findings queries
        if "findings" in query_lower:
            result["key_findings"] = (
                data.get("key_findings_for_stage3", []) +
                data.get("key_findings_for_stage4", [])
            )

        # Coverage and signal queries (preprocessing)
        if any(k in query_lower for k in ["coverage", "rsrp", "signal", "dominance"]):
            if "coverage_summary" in data:
                result["coverage_summary"] = data["coverage_summary"]

        if any(k in query_lower for k in ["sinr", "regime", "overlap"]):
            if "overlap_info" in data:
                result["overlap_info"] = data["overlap_info"]
            if "load_redistribution" in data:
                result["load_redistribution"] = data["load_redistribution"]

        # Fallback: return full data if no pattern matched
        if not result:
            print(f"  [MCP] WARNING: no pattern matched query '{query}' — returning full resource")
            return data

        return result

    def verify_version_consistency(self) -> bool:
        """Called by Stage 5A to verify all stages read same preprocessing version."""
        preprocess_reads = [
            e for e in self._log
            if "preprocessing" in e.get("resource", "")
            and e.get("reader") != "harness"
        ]
        if not preprocess_reads:
            return True

        versions = set(e["version_hash"] for e in preprocess_reads)
        if len(versions) > 1:
            print(f"  [MCP] VERSION MISMATCH: {versions}")
            return False

        print(f"  [MCP] Version consistent across all reads: {list(versions)[0]}")
        return True

    def _log_entry(self, reader, resource, version, fields, query):
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "reader": reader,
            "resource": resource,
            "version_hash": version,
            "fields_requested": fields,
        }
        if query:
            entry["query"] = query
        self._log.append(entry)
        self._save_log()

    def _save_log(self):
        self.log_path.write_text(json.dumps(self._log, indent=2))

    def get_log(self) -> list:
        return self._log