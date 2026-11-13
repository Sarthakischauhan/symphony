"""Render results.json -> report.md + report.png."""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _f(v, nd=0):
    if v is None:
        return "–"
    return f"{v:,.{nd}f}"


def _get(rows, client, tls, conc=1):
    for r in rows:
        if r.get("client") == client and r.get("tls") == tls and r.get("conc", 1) == conc and "error" not in r:
            return r
    return None


def mock_md(m):
    rows = m["rows"] + m.get("node_rows", [])
    clients = []
    for r in rows:
        if r.get("client") not in clients:
            clients.append(r.get("client"))
    concs = sorted({r.get("conc", 1) for r in rows})
    top = concs[-1]
    out = ["## Mock (local SSE replay: 2,150 tokens + tool call per stream)", "",
           f"| client | TTFE p50/p95 ms | total p50/p95 ms | events/s | CPU ms/1k tok | TLS total p50 | {top}× TLS wall ms | {top}× peak RSS MB | new conns/requests |",
           "|---|---|---|---|---|---|---|---|---|"]
    for c in clients:
        a, t, w = _get(rows, c, 0), _get(rows, c, 1), _get(rows, c, 1, top)
        if a is None:
            continue
        out.append(f"| {c} | {_f(a['ttfe_p50'], 2)} / {_f(a['ttfe_p95'], 2)} | {_f(a['total_p50'], 1)} / {_f(a['total_p95'], 1)} | "
                   f"{_f(a['events_per_s'])} | {_f(a['cpu_ms_per_1k_tok'], 1)} | {_f(t and t['total_p50'], 1)} | "
                   f"{_f(w and w['wall_ms_per_round'])} | {_f(w and w['peak_rss_mb'])} | {max(a['new_tcp_conns'], 0)}/{a['requests']} |")
    if m.get("rtt_rows"):
        out += ["", f"TTFT over TLS with emulated {m['rtt_rows'][0].get('rtt_ms')} ms RTT (TCP SYN not delayed, so this under-counts reconnects):", "",
                "| client | TTFT p50 | TTFT p95 | total p50 | new conns/requests |", "|---|---|---|---|---|"]
        for r in m["rtt_rows"]:
            if "error" not in r:
                out.append(f"| {r['client']} | {_f(r['ttfe_p50'], 1)} | {_f(r['ttfe_p95'], 1)} | {_f(r['total_p50'], 1)} | {max(r['new_tcp_conns'], 0)}/{r['requests']} |")
    cs = m.get("coldstart")
    if cs:
        out += ["", "| package | cold import p50 ms (net) | p95 | RSS MB | construct ms |", "|---|---|---|---|---|"]
        for k, v in cs.items():
            if isinstance(v, dict):
                out.append(f"| {k} | {_f(v['net_p50'])} | {_f(v['net_p95'])} | {_f(v.get('rss_mb'))} | {_f(v.get('construct_ms'), 3)} |")
    errs = [r for r in m["rows"] if "error" in r]
    if errs:
        out += ["", f"Worker errors: {len(errs)} (" + "; ".join(f"{e['client']}: {e['error']}" for e in errs[:3]) + ")"]
    return "\n".join(out)


def live_md(lv):
    if lv.get("skipped"):
        return f"## Live\n\nSkipped: {lv['reason']}."
    out = ["## Live (OpenAI Responses API, interleaved)", "",
           f"Budget ${lv['budget_usd']}, spent **${lv['spent_usd']:.4f}** (computed from returned usage tokens, "
           "cached input at the cached rate)."]
    for mres in lv["models"]:
        f = mres["facts"]
        out += ["", f"### {mres['model']}  (price $/1M in/out/cached: {mres['price_per_1m']})", "",
                f"Symphony catalog: in_catalog={f['in_catalog']}, api={f['catalog_api']}, reasoning={f['catalog_reasoning']}; "
                f"provider routes to **{f['symphony_routes_to']}**, sends `reasoning` param: **{f['symphony_sends_reasoning_param']}**"
                + ("" if f["symphony_sends_reasoning_param"] or not f["catalog_reasoning"] else
                   " → requested effort is ignored and the API default (medium) applies") + ".",
                "", "| client | effort | answer TTFT p50/p95 ms | answer total p50/p95 | visible tok/s | reasoning tok (answer p50) | "
                "first tool-arg delta p50/p95 | tool args complete p50/p95 | 2-step loop e2e p50/p95 | warm new conns | truncated (no usage) / empty answers | errors | cost $ |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for s in mres["summary"].values():
            out.append(f"| {s['client']} | {s['effort']} | {_f(s['answer_ttft_p50'])} / {_f(s['answer_ttft_p95'])} | "
                       f"{_f(s['answer_total_p50'])} / {_f(s['answer_total_p95'])} | {_f(s['answer_visible_tok_s_p50'])} | "
                       f"{_f(s['answer_reasoning_tokens_p50'])} | {_f(s['tool_first_arg_p50'])} / {_f(s['tool_first_arg_p95'])} | "
                       f"{_f(s['tool_args_done_p50'])} / {_f(s['tool_args_done_p95'])} | {_f(s['loop_e2e_p50'])} / {_f(s['loop_e2e_p95'])} | "
                       f"{s['warm_new_conns']}/{s['warm_requests']} | {s['incomplete']}/{s['n_requests']} · {s['empty_answers']} | {s['errors']} | {s['cost_usd']:.4f} |")
        errs = sorted({e for s in mres["summary"].values() for e in s["error_samples"]})
        if errs:
            out += ["", "Errors seen: " + "; ".join(f"`{e}`" for e in errs)]
        if mres["stopped"]:
            out += ["", f"**Hard stop:** {mres['stopped']}"]
    return "\n".join(out)


COLORS = {"symphony": "#d62728", "vercel": "#1f77b4"}


def _color(name):
    if name.startswith("symphony"):
        return COLORS["symphony"]
    if name.startswith("vercel"):
        return COLORS["vercel"]
    return "#7f7f7f"


def _bars(ax, items, title, xlabel, log=False):
    items = [(n, v) for n, v in items if v is not None]
    names = [n for n, _ in items]
    vals = [v for _, v in items]
    ax.barh(names, vals, color=[_color(n) for n in names])
    ax.invert_yaxis()
    ax.set_title(title, fontsize=11, weight="bold")
    ax.set_xlabel(xlabel)
    if log:
        ax.set_xscale("log")
    for i, v in enumerate(vals):
        ax.text(v, i, f" {v:,.0f}" if v >= 10 else f" {v:.1f}", va="center", fontsize=8)


def chart(results, path):
    panels = []
    m = results.get("mock")
    if m:
        rows = m["rows"] + m.get("node_rows", [])
        clients = list(dict.fromkeys(r.get("client") for r in rows if "error" not in r))
        top = max(r.get("conc", 1) for r in rows)
        if m.get("coldstart"):
            panels.append(([(k, v["net_p50"]) for k, v in m["coldstart"].items() if isinstance(v, dict)], "Mock: cold import p50 ms", "ms", True))
        panels.append(([(c, (_get(rows, c, 0) or {}).get("cpu_ms_per_1k_tok")) for c in clients], "Mock: client CPU ms per 1k tokens", "ms", True))
        if m.get("rtt_rows"):
            panels.append(([(r["client"], r.get("ttfe_p50")) for r in m["rtt_rows"]], "Mock: TTFT p50 ms at emulated RTT", "ms", False))
        panels.append(([(c, (_get(rows, c, 1, top) or {}).get("wall_ms_per_round")) for c in clients], f"Mock: {top} concurrent TLS streams, wall ms", "ms", True))
    lv = results.get("live")
    if lv and not lv.get("skipped"):
        for mres in lv["models"]:
            s = list(mres["summary"].values())
            panels.append(([(f"{x['client']} @{x['effort']}", x["answer_ttft_p50"]) for x in s], f"LIVE {mres['model']}: answer TTFT p50 ms", "ms", False))
            panels.append(([(f"{x['client']} @{x['effort']}", x["loop_e2e_p50"]) for x in s], f"LIVE {mres['model']}: 2-step tool loop e2e p50 ms", "ms", False))
    if not panels:
        return
    rows_n = (len(panels) + 1) // 2
    fig, axes = plt.subplots(rows_n, 2, figsize=(16, 5 * rows_n), squeeze=False)
    for ax, (items, title, xl, log) in zip(axes.flat, panels):
        _bars(ax, items, title, xl, log)
    for ax in list(axes.flat)[len(panels):]:
        ax.axis("off")
    fig.suptitle("Symphony core_ai provider benchmark (red = Symphony, grey = other clients, blue = Vercel AI SDK)", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, dpi=100)
    plt.close(fig)


def write(results, out_dir):
    parts = ["# Symphony provider-layer benchmark", "",
             f"core_ai: `{results.get('core_ai_file')}` (git {results.get('git_rev')}), Python {results.get('python')}, started {results.get('started_utc')}."]
    if results.get("mock"):
        parts += ["", mock_md(results["mock"])]
    if results.get("live"):
        parts += ["", live_md(results["live"])]
    with open(os.path.join(out_dir, "report.md"), "w") as f:
        f.write("\n".join(parts) + "\n")
    chart(results, os.path.join(out_dir, "report.png"))
