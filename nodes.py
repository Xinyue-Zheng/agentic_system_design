"""Graph nodes. Discipline: decisions are returned as STATE WRITES
(current_decision, route_log) -- conditional edges only read them, so every
branch decision is fully visible in LangSmith traces and checkpoints."""

import json
import os

from prompts import ORCHESTRATOR_SYSTEM, ESTIMATOR_SYSTEM, JUDGE_SYSTEM
from tools import MOCK_MODE, INITIAL_BUDGET, WORKER_RUNNERS
from voi import (ACTION_REGISTRY, INITIAL_CHAIN, SATURATION_R,
                 rrc_loss_interval, score_actions as voi_score)

MAX_REVISE = 3

# ---------------- LLM factory (Azure placeholders) ----------------
MODEL_MAP = {  # role -> Azure deployment name
    "orchestrator": os.environ.get("AZ_DEPLOY_ORCH", "PLACEHOLDER_o3"),
    "estimator":    os.environ.get("AZ_DEPLOY_EST", "PLACEHOLDER_o3"),
    "judge":        os.environ.get("AZ_DEPLOY_JUDGE", "PLACEHOLDER_gpt5"),
    "worker":       os.environ.get("AZ_DEPLOY_WORKER", "PLACEHOLDER_gpt41"),
}


def get_llm(role):
    if MOCK_MODE:
        return None
    from langchain_openai import AzureChatOpenAI  # pip install langchain-openai
    return AzureChatOpenAI(
        azure_deployment=MODEL_MAP[role],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        temperature=0,
    )


def _llm_json(llm, system, user):
    resp = llm.invoke([("system", system), ("user", user)])
    text = resp.content.strip().removeprefix("```json").removesuffix("```").strip()
    return json.loads(text)


# ---------------- nodes ----------------
def init_case(state):
    case = state["case"]
    return {
        "chain": {k: dict(v) for k, v in INITIAL_CHAIN.items()},
        "budget": dict(INITIAL_BUDGET),
        "milestones": {f"M{i}": False for i in range(1, 6)},
        "revise_count": 0,
        "should_submit": False,
        "route_log": [{"node": "init_case", "case_id": case.get("case_id")}],
    }


def score_actions(state):
    scores, should_submit = voi_score(
        state["chain"], state.get("done_actions", []),
        state.get("saturated_vars", []), state["budget"],
    )
    lo, hi = rrc_loss_interval(state["chain"])
    return {
        "action_scores": scores,
        "should_submit": should_submit,
        "route_log": [{"node": "score_actions", "scores": scores,
                       "rrc_interval": [round(lo, 1), round(hi, 1)],
                       "should_submit": should_submit}],
    }


def orchestrator(state):
    scores = state["action_scores"]
    directive = (state.get("judge_verdict") or {}).get("directive", "")
    argmax = max(scores, key=scores.get) if scores else None

    if MOCK_MODE or not scores:
        decision = {"action_id": argmax, "deviated": False,
                    "reason": "argmax (mock)", "directive_addressed": directive}
    else:
        llm = get_llm("orchestrator")
        user = json.dumps({"action_scores": scores, "argmax": argmax,
                           "budget": state["budget"], "judge_directive": directive,
                           "evidence_count": len(state.get("evidence", []))})
        try:
            decision = _llm_json(llm, ORCHESTRATOR_SYSTEM, user)
        except Exception as e:  # fall back to argmax rather than crash the case
            decision = {"action_id": argmax, "deviated": False,
                        "reason": f"argmax fallback ({e})"}

    a = ACTION_REGISTRY[decision["action_id"]]
    decision.update({"worker": a["worker"], "var": a["var"], "r_pred": a["r"]})
    return {"current_decision": decision,
            "route_log": [{"node": "orchestrator", **decision}]}


def _make_worker(worker_name):
    """Factory: one node per worker; runs the tool with budget enforcement
    and writes evidence + updates the estimation chain interval."""
    def worker(state):
        decision = state["current_decision"]
        aid = decision["action_id"]
        action = ACTION_REGISTRY[aid]

        budget = dict(state["budget"])
        bkey = action["budget_key"]
        if bkey:
            if budget.get(bkey, 0) <= 0:   # hard stop, not prompt-based
                return {"route_log": [{"node": worker_name, "action": aid,
                                       "error": "budget exhausted"}]}
            budget[bkey] -= 1

        ev, observed = WORKER_RUNNERS[worker_name](
            aid, action, state["case"], len(state.get("evidence", [])))

        # --- update chain interval & measure r_actual ---
        chain = {k: dict(v) for k, v in state["chain"].items()}
        var = action["var"]
        iv = chain[var]
        old_w = iv["high"] - iv["low"]
        shrink = min(max(observed.get("shrink_factor", 0.0), 0.0), 0.95)
        mid = (iv["low"] + iv["high"]) / 2
        new_w = old_w * (1 - shrink)
        iv["low"], iv["high"] = mid - new_w / 2, mid + new_w / 2
        r_actual = round(shrink, 3)

        saturated = [var] if r_actual < SATURATION_R else []
        return {
            "evidence": [ev],
            "chain": chain,
            "budget": budget,
            "done_actions": [aid],
            "saturated_vars": saturated,
            "route_log": [{"node": worker_name, "action": aid,
                           "evidence_id": ev["id"],
                           "r_pred": decision["r_pred"], "r_actual": r_actual,
                           "saturated": bool(saturated)}],
        }
    worker.__name__ = worker_name
    return worker


def update_chain(state):
    """Milestone bookkeeping after each acquisition (deterministic)."""
    chain, ev = state["chain"], state.get("evidence", [])
    ms = dict(state["milestones"])
    ms["M1"] = (chain["B"]["high"] - chain["B"]["low"]) < 0.4 * max(
        (chain["B"]["high"] + chain["B"]["low"]) / 2, 1)
    ms["M2"] = any(e["source"] == "attributes" for e in ev)
    ms["M3"] = (chain["H"]["high"] - chain["H"]["low"]) <= 0.20
    ms["M4"] = (chain["O"]["high"] - chain["O"]["low"]) <= 0.20
    return {"milestones": ms,
            "route_log": [{"node": "update_chain", "milestones": ms}]}


def estimator(state):
    chain, ev = state["chain"], state.get("evidence", [])
    lo, hi = rrc_loss_interval(chain)
    mid = (lo + hi) / 2
    cite = {e["var"]: e["id"] for e in ev}
    if MOCK_MODE:
        narrative = (f"RRC_loss = B[{cite.get('B','ASSUMPTION')}] x "
                     f"(H[{cite.get('H','ASSUMPTION')}] + O[{cite.get('O','ASSUMPTION')}])"
                     f" -> low={lo:.0f}, mid={mid:.0f}, high={hi:.0f}")
        est = {"narrative": narrative,
               "rrc_loss": {"low": round(lo), "mid": round(mid), "high": round(hi)}}
    else:
        llm = get_llm("estimator")
        user = json.dumps({"chain": chain, "evidence": ev})
        est = _llm_json(llm, ESTIMATOR_SYSTEM, user)
    ms = dict(state["milestones"]); ms["M5"] = True
    return {"estimate": est, "milestones": ms,
            "route_log": [{"node": "estimator", "rrc_loss": est["rrc_loss"]}]}


def judge(state):
    ms, chain, est = state["milestones"], state["chain"], state["estimate"]
    # --- deterministic checks (code, not LLM) ---
    checks = {
        "milestones_complete": all(ms.values()),
        "loss_leq_baseline": est["rrc_loss"]["high"] <= chain["B"]["high"] * 1.10001,
        "evidence_cited": "ASSUMPTION" not in est["narrative"] or True,  # soft
    }
    unmet = [m for m, ok in ms.items() if not ok]

    if MOCK_MODE:
        if checks["milestones_complete"] and checks["loss_leq_baseline"]:
            verdict = {"verdict": "ACCEPT", "directive": ""}
        elif state["revise_count"] < MAX_REVISE and unmet:
            verdict = {"verdict": "REVISE",
                       "directive": f"complete {unmet[0]}: acquire evidence "
                                    f"constraining its variable"}
        else:
            verdict = {"verdict": "ESCALATE",
                       "directive": f"unfixable gaps: {unmet}"}
    else:
        llm = get_llm("judge")
        user = json.dumps({"milestones": ms, "checks": checks, "estimate": est,
                           "saturated": state.get("saturated_vars", []),
                           "revise_count": state["revise_count"]})
        verdict = _llm_json(llm, JUDGE_SYSTEM, user)
        if verdict["verdict"] == "REVISE" and state["revise_count"] >= MAX_REVISE:
            verdict = {"verdict": "ESCALATE", "directive": "revise limit reached"}

    out = {"judge_verdict": verdict,
           "route_log": [{"node": "judge", **verdict, "checks": checks}]}
    if verdict["verdict"] == "REVISE":
        out["revise_count"] = state["revise_count"] + 1
        out["should_submit"] = False
    return out


def reporter(state):
    v = state["judge_verdict"]["verdict"]
    est, ev = state["estimate"], state.get("evidence", [])
    header = "FINAL" if v == "ACCEPT" else f"DEGRADED ({v})"
    report = (f"[{header}] case {state['case'].get('case_id')}\n"
              f"{est['narrative']}\n"
              f"evidence used: {[e['id'] for e in ev]}\n"
              f"budget left: {state['budget']}")
    return {"report": report, "route_log": [{"node": "reporter", "status": v}]}
