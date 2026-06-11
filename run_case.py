"""Entry point: run one case with full checkpointing + LangSmith tracing.

LangSmith setup (zero code -- environment only):
    export LANGSMITH_TRACING=true
    export LANGSMITH_API_KEY=...
    export LANGSMITH_PROJECT=outage-impact
Then every case appears as one trace (run tree); with `langgraph dev` +
Studio Trace Mode you also get the graph view with per-step highlighting.

Real mode:
    export OUTAGE_AGENT_MOCK=0
    export AZURE_OPENAI_API_KEY=... AZURE_OPENAI_ENDPOINT=...
    export AZ_DEPLOY_ORCH=... AZ_DEPLOY_EST=... AZ_DEPLOY_JUDGE=... AZ_DEPLOY_WORKER=...
"""

import json
import uuid

from graph import build_graph


def run_case(case: dict, thread_id: str | None = None):
    app = build_graph()
    thread_id = thread_id or f"case-{case.get('case_id', uuid.uuid4().hex[:8])}"
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 80,
              "tags": [f"case:{case.get('case_id')}"]}

    final = app.invoke({"case": case}, config=config)

    # ---- console summary: the per-case decision trail ----
    print("=" * 70)
    print("ROUTE LOG (every decision point, as stored in state):")
    for step in final["route_log"]:
        print("  ", json.dumps(step, default=str)[:160])
    print("=" * 70)
    print(final["report"])
    print("=" * 70)

    # ---- checkpoints: one snapshot per superstep, time-travel ready ----
    history = list(app.get_state_history(config))
    print(f"checkpoints saved: {len(history)} (thread_id={thread_id})")
    print("fork example: app.update_state(history[k].config, {...}); "
          "app.invoke(None, history[k].config)")
    return final, history


if __name__ == "__main__":
    demo_case = {
        "case_id": "TICKET-DEMO-001",
        "target_cells": ["CELL_X"],
        "enodeb": "111111",
        "outage_window": ["2026-06-15T22:00", "2026-06-16T04:00"],
        "location": {"lat": 0.0, "lon": 0.0},
    }
    run_case(demo_case)
