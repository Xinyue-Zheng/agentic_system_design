"""
make_viewer.py  --  self-contained graph + checkpoint viewer

Run from the project root (same folder as run_case.py / graph.py):

    python make_viewer.py                 # run a case, write outage_viewer.html (permanent file)
    python make_viewer.py --serve         # same, but also serve it at localhost:PORT (like Copilot)
    python make_viewer.py --no-run x.json # render from a saved route_log json (no re-run)

The LEFT graph is produced by LangGraph itself via app.get_graph().draw_mermaid()
(so this counts as "visualized with LangGraph"); the RIGHT panel is the real
route_log + checkpoint history from this run. No existing files are modified.

Note on --serve: the localhost link is only alive while THIS script's process
is running (the terminal stays blocked). Ctrl+C ends the process and the link
dies. The .html file, by contrast, is permanent -- double-click it any time.
"""
import os, sys, json, html, argparse

# Default to real mode. Set these to "1" to dry-run the pipeline without Snowflake/LLM.
os.environ.setdefault("OUTAGE_AGENT_MOCK_DATA", "1")
os.environ.setdefault("OUTAGE_AGENT_MOCK_LLM", "1")

# Node -> left-border color in the right panel (matches the mermaid node families).
NODE_COLOR = {
    "init_case": "#5F5E5A", "score_actions": "#0F6E56", "orchestrator": "#3C3489",
    "kpi_analyst": "#534AB7", "coverage_surveyor": "#534AB7", "attribute_lookup": "#534AB7",
    "update_chain": "#5F5E5A", "estimator": "#0F6E56", "judge": "#854F0B", "reporter": "#5F5E5A",
}

def summarize(step: dict) -> str:
    """Condense one route_log entry into the right-panel subtitle."""
    bits = []
    if step.get("skipped"):      bits.append("skipped: " + str(step.get("reason", "")))
    if "case_id" in step:        bits.append("case_id " + str(step["case_id"]))
    if "rrc_interval" in step:   bits.append("rrc " + str(step["rrc_interval"]))
    if "should_submit" in step:  bits.append("submit=" + str(step["should_submit"]))
    if "action_id" in step:      bits.append("pick " + str(step["action_id"]))
    if "deviated" in step:       bits.append("dev=" + str(step["deviated"]))
    if "r_pred" in step:         bits.append("r_pred " + str(step["r_pred"]))
    if "action" in step:         bits.append("E:" + str(step.get("evidence_id", step["action"])))
    if "r_actual" in step:       bits.append("r_act " + str(step["r_actual"]))
    if "milestones" in step:     bits.append("M:" + ",".join(k for k, v in step["milestones"].items() if v))
    if "verdict" in step:        bits.append("verdict " + str(step["verdict"]))
    if "status" in step:         bits.append("status " + str(step["status"]))
    if "error" in step:          bits.append("ERR " + str(step["error"]))
    return " . ".join(bits)

def build_html(case_id, report, route_log, n_ckpt, mermaid_src):
    rows = []
    for i, step in enumerate(route_log, 1):
        node = step.get("node", "?")
        stroke = NODE_COLOR.get(node, "#5F5E5A")
        rows.append(
            f'<div style="background:#fff;border:.5px solid #e5e3da;border-left:3px solid {stroke};'
            f'border-radius:0 8px 8px 0;padding:9px 12px">'
            f'<div style="display:flex;justify-content:space-between">'
            f'<span style="font-weight:500;font-size:14px;color:#2C2C2A">{html.escape(node)}</span>'
            f'<span style="font-size:12px;color:#9a988f">#{i}</span></div>'
            f'<div style="font-size:13px;color:#5F5E5A;margin-top:2px">{html.escape(summarize(step))}</div></div>'
        )
    rows_html = "\n".join(rows)
    rep = html.escape(report or "")
    mermaid_js = html.escape(mermaid_src)
    return f'''<!doctype html><meta charset="utf-8"><title>outage viewer - {html.escape(case_id)}</title>
<body style="font-family:system-ui,-apple-system,sans-serif;background:#faf9f5;margin:0;padding:24px;color:#2C2C2A">
<div style="max-width:1040px;margin:0 auto">
<div style="font-size:18px;font-weight:500;margin-bottom:4px">outage agent - {html.escape(case_id)}</div>
<div style="font-size:13px;color:#5F5E5A;margin-bottom:18px">{len(route_log)} route steps . {n_ckpt} checkpoints . left graph by LangGraph draw_mermaid()</div>
<div style="display:grid;grid-template-columns:340px 1fr;gap:20px;align-items:start">
<div style="background:#fff;border:.5px solid #e5e3da;border-radius:12px;padding:14px">
<div class="mermaid">{mermaid_js}</div></div>
<div><div style="display:flex;flex-direction:column;gap:8px">{rows_html}</div>
<div style="margin-top:18px;background:#fff;border:.5px solid #e5e3da;border-radius:12px;padding:14px;white-space:pre-wrap;font-size:13px">{rep}</div>
</div></div></div>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
mermaid.initialize({{ startOnLoad: true, theme: 'base',
  themeVariables: {{ primaryColor:'#E1F5EE', primaryBorderColor:'#0F6E56',
                     primaryTextColor:'#04342C', lineColor:'#1D9E75' }} }});
</script></body>'''

def serve(path, port=8000):
    """Serve the generated html at localhost:PORT until Ctrl+C (like Copilot's link)."""
    import http.server, socketserver, functools, webbrowser
    directory = os.path.dirname(os.path.abspath(path)) or "."
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    url = f"http://localhost:{port}/{os.path.basename(path)}"
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"serving at {url}  (Ctrl+C to stop -- link dies when this process ends)")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        httpd.serve_forever()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-run", metavar="JSON", help="render from saved {case_id,report,route_log,mermaid} json")
    ap.add_argument("--serve", action="store_true", help="also serve at localhost after writing the file")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--out", default="outage_viewer.html")
    args = ap.parse_args()

    if args.no_run:
        d = json.load(open(args.no_run))
        case_id, report = d.get("case_id", "case"), d.get("report", "")
        route_log, n_ckpt = d.get("route_log", []), d.get("n_ckpt", 0)
        mermaid_src = d.get("mermaid", "graph TD\n  A[no graph in json]")
    else:
        from run_case import load_case, run_case
        from graph import build_graph
        # LangGraph's own diagram of the compiled graph -- the "LangGraph-produced" figure.
        mermaid_src = build_graph().get_graph().draw_mermaid()
        case = load_case(os.environ.get("OUTAGE_AGENT_CASE_SOURCE"))
        final, history = run_case(case)
        case_id   = case.get("case_id", "case")
        report    = final.get("report", "")
        route_log = final.get("route_log", [])
        n_ckpt    = len(list(history))

    open(args.out, "w").write(build_html(case_id, report, route_log, n_ckpt, mermaid_src))
    print("wrote", args.out, "-", len(route_log), "steps")
    if args.serve:
        serve(args.out, args.port)

if __name__ == "__main__":
    main()
