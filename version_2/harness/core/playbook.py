"""
playbook.py — the ACE warm tier component

Manages the evolving context (warm tier) of AGENTS.md.
Stage 6 calls add_delta() after a verified-passing run.
Every subsequent run loads the relevant lessons per stage.

Never rewrites. Only appends structured delta items.
This prevents context collapse — the core ACE innovation.
"""

import json
import datetime
from pathlib import Path

PLAYBOOK_PATH = Path("/workspace/context/playbook.json")


class PlaybookManager:

    def __init__(self):
        PLAYBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not PLAYBOOK_PATH.exists():
            PLAYBOOK_PATH.write_text(json.dumps(
                {"version": 1, "items": []}, indent=2
            ))

    def add_delta(self, stage_id: str, item_type: str, content: str):
        """
        Add one delta item to the warm tier.
        Never rewrites existing items — only appends.

        item_type: "pattern" | "correction" | "warning" | "threshold_note"
        """
        playbook = json.loads(PLAYBOOK_PATH.read_text())

        # Simple deduplication — skip if identical content exists
        existing = [i["content"] for i in playbook["items"]]
        if content in existing:
            return

        playbook["items"].append({
            "id": len(playbook["items"]),
            "applies_to": stage_id,
            "type": item_type,
            "content": content,
            "added_at": datetime.datetime.now().isoformat(),
        })
        PLAYBOOK_PATH.write_text(json.dumps(playbook, indent=2))

    def get_warm_tier(self, stage_id: str) -> str:
        """
        Returns warm tier content for a specific stage.
        Formatted as readable text for injection into agent context.
        """
        try:
            playbook = json.loads(PLAYBOOK_PATH.read_text())
        except FileNotFoundError:
            return ""

        items = [
            i for i in playbook["items"]
            if i["applies_to"] == stage_id
        ]
        if not items:
            return ""

        lines = []
        for item in items:
            lines.append(
                f"- [{item['type']}] {item['content']}"
            )
        return "\n".join(lines)
