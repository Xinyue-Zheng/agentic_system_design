"""
make_viewer.py  ——  自包含图查看器生成器

放在项目根目录(和 run_case.py / graph.py 同级),运行:
    python make_viewer.py                 # 跑一个新 case 并出图
    python make_viewer.py --no-run x.json # 用已存的 route_log json 出图(不重跑)

产物: outage_viewer.html  —— 双击即开,左图右 checkpoint,不需要服务器。
不修改任何现有文件。
"""
import os, sys, json, html, argparse

# 默认真实模式;想用 mock 跑通链路可改成 "1"
os.environ.setdefault("OUTAGE_AGENT_MOCK_DATA", "1")
os.environ.setdefault("OUTAGE_AGENT_MOCK_LLM", "1")

# 节点 -> 颜色族(和左图一致)。teal=核心流程, purple=worker, amber=judge, gray=端点/记账
NODE_COLOR = {
    "init_case":        ("#888780", "#5F5E5A"),
    "score_actions":    ("#1D9E75", "#0F6E56"),
    "orchestrator":     ("#534AB7", "#3C3489"),
    "kpi_analyst":      ("#7F77DD", "#534AB7"),
    "coverage_surveyor":("#7F77DD", "#534AB7"),
    "attribute_lookup": ("#7F77DD", "#534AB7"),
    "update_chain":     ("#888780", "#5F5E5A"),
    "estimator":        ("#1D9E75", "#0F6E56"),
    "judge":            ("#BA7517", "#854F0B"),
    "reporter":         ("#888780", "#5F5E5A"),
}

def summarize(step: dict) -> str:
    """把一条 route_log 提炼成右栏副标题。按你真实字段挑要紧的。"""
    n = step.get("node", "?")
    bits = []
    if step.get("skipped"):
        bits.append("skipped: " + str(step.get("reason", "")))
    if "case_id" in step:        bits.append("case_id " + str(step["case_id"]))
    if "rrc_interval" in step:   bits.append("rrc " + str(step["rrc_interval"]))
    if "should_submit" in step:  bits.append("submit=" + str(step["should_submit"]))
    if "action_id" in step:      bits.append("pick " + str(step["action_id"]))
    if "deviated" in step:       bits.append("dev=" + str(step["deviated"]))
    if "r_pred" in step:         bits.append("r_pred " + str(step["r_pred"]))
    if "action" in step:         bits.append("E:" + str(step.get("evidence_id", step["action"])))
    if "r_actual" in step:       bits.append("r_act " + str(step["r_actual"]))
    if "milestones" in step:     bits.append("M:" + ",".join(k for k,v in step["milestones"].items() if v))
    if "verdict" in step:        bits.append("verdict " + str(step["verdict"]))
    if "status" in step:         bits.append("status " + str(step["status"]))
    if "error" in step:          bits.append("ERR " + str(step["error"]))
    return " · ".join(bits)

GRAPH_SVG = '''<svg width="100%" viewBox="0 0 260 540" role="img">
<defs><marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>
<line x1="130" y1="40"  x2="130" y2="58"  stroke="#0F6E56" marker-end="url(#ar)"/>
<line x1="130" y1="96"  x2="130" y2="114" stroke="#0F6E56" marker-end="url(#ar)"/>
<line x1="130" y1="152" x2="130" y2="170" stroke="#0F6E56" marker-end="url(#ar)"/>
<line x1="130" y1="208" x2="130" y2="226" stroke="#0F6E56" marker-end="url(#ar)"/>
<line x1="130" y1="264" x2="130" y2="282" stroke="#0F6E56" marker-end="url(#ar)"/>
<path d="M200 246 Q236 180 236 120 Q236 84 178 76" fill="none" stroke="#5DCAA5" stroke-dasharray="4 4" marker-end="url(#ar)"/>
<line x1="130" y1="320" x2="130" y2="338" stroke="#0F6E56" marker-end="url(#ar)"/>
<line x1="130" y1="376" x2="130" y2="394" stroke="#0F6E56" marker-end="url(#ar)"/>
<path d="M58 414 Q24 290 24 180 Q24 130 58 122" fill="none" stroke="#BA7517" stroke-dasharray="4 4" marker-end="url(#ar)"/>
<text x="18" y="270" transform="rotate(-90 18 270)" fill="#854F0B" style="font:11px sans-serif">revise</text>
<line x1="130" y1="432" x2="130" y2="450" stroke="#0F6E56" marker-end="url(#ar)"/>
<g><rect x="82" y="16" width="96" height="24" rx="6" fill="#F1EFE8" stroke="#5F5E5A" stroke-width=".5"/><text x="130" y="31" text-anchor="middle" fill="#2C2C2A" style="font:12px sans-serif">init_case</text></g>
<g><rect x="72" y="58" width="116" height="38" rx="8" fill="#E1F5EE" stroke="#0F6E56" stroke-width=".5"/><text x="130" y="82" text-anchor="middle" fill="#04342C" style="font:13px sans-serif;font-weight:500">score_actions</text></g>
<g><rect x="72" y="114" width="116" height="38" rx="8" fill="#EEEDFE" stroke="#3C3489" stroke-width=".5"/><text x="130" y="138" text-anchor="middle" fill="#26215C" style="font:13px sans-serif;font-weight:500">orchestrator</text></g>
<g><rect x="56" y="170" width="148" height="38" rx="8" fill="#EEEDFE" stroke="#534AB7" stroke-width=".5"/><text x="130" y="190" text-anchor="middle" fill="#26215C" style="font:12px sans-serif">kpi / coverage / attr</text></g>
<g><rect x="72" y="226" width="116" height="38" rx="8" fill="#F1EFE8" stroke="#5F5E5A" stroke-width=".5"/><text x="130" y="250" text-anchor="middle" fill="#2C2C2A" style="font:13px sans-serif;font-weight:500">update_chain</text></g>
<g><rect x="72" y="282" width="116" height="38" rx="8" fill="#E1F5EE" stroke="#0F6E56" stroke-width=".5"/><text x="130" y="306" text-anchor="middle" fill="#04342C" style="font:13px sans-serif;font-weight:500">estimator</text></g>
<g><rect x="82" y="338" width="96" height="38" rx="8" fill="#E1F5EE" stroke="#0F6E56" stroke-width=".5"/><text x="130" y="362" text-anchor="middle" fill="#04342C" style="font:13px sans-serif;font-weight:500">judge*</text></g>
<g><rect x="82" y="394" width="96" height="38" rx="8" fill="#FAEEDA" stroke="#854F0B" stroke-width=".5"/><text x="130" y="418" text-anchor="middle" fill="#412402" style="font:13px sans-serif;font-weight:500">judge</text></g>
<g><rect x="82" y="450" width="96" height="24" rx="6" fill="#F1EFE8" stroke="#5F5E5A" stroke-width=".5"/><text x="130" y="465" text-anchor="middle" fill="#2C2C2A" style="font:12px sans-serif">reporter</text></g>
</svg>'''

def build_html(case_id: str, report: str, route_log: list, n_ckpt: int) -> str:
    rows = []
    for i, step in enumerate(route_log, 1):
        node = step.get("node", "?")
        fill, stroke = NODE_COLOR.get(node, ("#888780", "#5F5E5A"))
        sub = html.escape(summarize(step))
        rows.append(f'''<div style="background:#fff;border:.5px solid #e5e3da;border-left:3px solid {stroke};border-radius:0 8px 8px 0;padding:9px 12px">
<div style="display:flex;justify-content:space-between"><span style="font-weight:500;font-size:14px;color:#2C2C2A">{html.escape(node)}</span><span style="font-size:12px;color:#9a988f">#{i}</span></div>
<div style="font-size:13px;color:#5F5E5A;margin-top:2px">{sub}</div></div>''')
    rows_html = "\n".join(rows)
    rep = html.escape(report or "")
    return f'''<!doctype html><meta charset="utf-8"><title>outage viewer · {html.escape(case_id)}</title>
<body style="font-family:system-ui,-apple-system,sans-serif;background:#faf9f5;margin:0;padding:24px;color:#2C2C2A">
<div style="max-width:1000px;margin:0 auto">
<div style="font-size:18px;font-weight:500;margin-bottom:4px">outage agent · {html.escape(case_id)}</div>
<div style="font-size:13px;color:#5F5E5A;margin-bottom:18px">{len(route_log)} route steps · {n_ckpt} checkpoints · * 中间是回到 judge 的占位</div>
<div style="display:grid;grid-template-columns:300px 1fr;gap:20px;align-items:start">
<div style="background:#fff;border:.5px solid #e5e3da;border-radius:12px;padding:14px">{GRAPH_SVG}</div>
<div><div style="display:flex;flex-direction:column;gap:8px">{rows_html}</div>
<div style="margin-top:18px;background:#fff;border:.5px solid #e5e3da;border-radius:12px;padding:14px;white-space:pre-wrap;font-size:13px;color:#2C2C2A">{rep}</div>
</div></div></div></body>'''

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-run", metavar="JSON", help="用已存的 {case_id, report, route_log} json,不重跑")
    ap.add_argument("--out", default="outage_viewer.html")
    args = ap.parse_args()

    if args.no_run:
        data = json.load(open(args.no_run))
        case_id   = data.get("case_id", "case")
        report    = data.get("report", "")
        route_log = data.get("route_log", [])
        n_ckpt    = data.get("n_ckpt", len(route_log))
    else:
        from run_case import load_case, run_case
        case = load_case(os.environ.get("OUTAGE_AGENT_CASE_SOURCE"))
        final, history = run_case(case)
        case_id   = case.get("case_id", "case")
        report    = final.get("report", "")
        route_log = final.get("route_log", [])
        n_ckpt    = len(list(history))

    open(args.out, "w").write(build_html(case_id, report, route_log, n_ckpt))
    print("wrote", args.out, "—", len(route_log), "steps")

if __name__ == "__main__":
    main()
