"""Graph assembly: hub-and-spoke + judge loop, with checkpointing.

Edges are ZERO-LOGIC readers of state -- all decisions were written by nodes
(see nodes.py), so LangSmith traces and LangGraph Studio show full decision
payloads at every branch point."""

from langgraph.graph import StateGraph, START, END

import nodes
from state import CaseState

WORKERS = ("kpi_analyst", "coverage_surveyor", "attribute_lookup")


# ---- conditional edge readers (no logic beyond reading state) ----
def route_after_score(state):
    return "estimator" if state["should_submit"] else "orchestrator"


def route_after_orchestrator(state):
    return state["current_decision"]["worker"]


def route_after_judge(state):
    v = state["judge_verdict"]["verdict"]
    if v == "REVISE":
        return "orchestrator"      # directive travels via state
    return "reporter"               # ACCEPT and ESCALATE both report


def build_graph(checkpointer=None):
    g = StateGraph(CaseState)
    g.add_node("init_case", nodes.init_case)
    g.add_node("score_actions", nodes.score_actions)
    g.add_node("orchestrator", nodes.orchestrator)
    for w in WORKERS:
        g.add_node(w, nodes._make_worker(w))
    g.add_node("update_chain", nodes.update_chain)
    g.add_node("estimator", nodes.estimator)
    g.add_node("judge", nodes.judge)
    g.add_node("reporter", nodes.reporter)

    g.add_edge(START, "init_case")
    g.add_edge("init_case", "score_actions")
    g.add_conditional_edges("score_actions", route_after_score,
                            {"estimator": "estimator",
                             "orchestrator": "orchestrator"})
    g.add_conditional_edges("orchestrator", route_after_orchestrator,
                            {w: w for w in WORKERS})
    for w in WORKERS:
        g.add_edge(w, "update_chain")
    g.add_edge("update_chain", "score_actions")
    g.add_edge("estimator", "judge")
    g.add_conditional_edges("judge", route_after_judge,
                            {"orchestrator": "orchestrator",
                             "reporter": "reporter"})
    g.add_edge("reporter", END)

    if checkpointer is None:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            import sqlite3
            checkpointer = SqliteSaver(sqlite3.connect("checkpoints.db",
                                                       check_same_thread=False))
        except ImportError:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()

    # interrupt_before=["judge"] -- uncomment for human-in-the-loop review
    return g.compile(checkpointer=checkpointer)
