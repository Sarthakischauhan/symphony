#!/usr/bin/env python3
"""Symphony provider-layer benchmark: one entry point.

  python bench/run.py --mock [--quick] [--with-node] [--rtt-ms 40]
  python bench/run.py --live --model gpt-6-luna --model gpt-5.6-luna --budget-usd 0.12 [--rounds 15] [--efforts none,low]
  python bench/run.py --mock --live --model gpt-4o-mini --budget-usd 0.05

Writes <out>/results.json, <out>/report.md and <out>/report.png (default out: bench/results/<UTC timestamp>/).
Live mode reads OPENAI_API_KEY from the environment, skips cleanly when it is absent, never prints it,
and hard-stops before any request whose worst-case cost would exceed --budget-usd.
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _common import write_json  # noqa: E402


def _wait_http(url, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(0.2)
    raise SystemExit(f"mock server did not start: {url}")


def _make_tls(tmp):
    cert, key = os.path.join(tmp, "cert.pem"), os.path.join(tmp, "key.pem")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert, "-days", "2",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                   check=True, capture_output=True)
    import certifi
    bundle = os.path.join(tmp, "bundle.pem")  # certifi + test cert, so per-client SSLContext cost stays realistic
    with open(bundle, "w") as out:
        out.write(open(certifi.where()).read() + open(cert).read())
    return cert, key, bundle


def run_mock(a):
    from clients import MOCK_CLIENTS
    import coldstart
    tmp = tempfile.mkdtemp(prefix="symphony-bench-")
    procs = []
    results = {"rows": [], "rtt_rows": [], "node_rows": []}
    try:
        cert, key, bundle = _make_tls(tmp)
        env = dict(os.environ, SSL_CERT_FILE=bundle, NODE_EXTRA_CA_CERTS=cert, BENCH_HTTP_PORT=str(a.http_port),
                   BENCH_HTTPS_PORT=str(a.https_port), BENCH_RTT_PORT=str(a.rtt_port))
        env.pop("OPENAI_API_KEY", None)  # mock workers never need a real key
        procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, "mock_server.py"), str(a.http_port), str(a.https_port), cert, key, "4"],
                                      cwd=HERE, stdout=subprocess.DEVNULL))
        _wait_http(f"http://127.0.0.1:{a.http_port}/stats")
        q = a.quick
        worker = [sys.executable, os.path.join(HERE, "mock_worker.py"), "--http-port", str(a.http_port),
                  "--https-port", str(a.https_port), "--rtt-port", str(a.rtt_port)]

        def one(client, *args):
            out = subprocess.run(worker + [client, *args], env=env, cwd=tmp, capture_output=True, text=True, timeout=1800)
            if out.returncode != 0:
                return {"client": client, "args": list(args), "error": out.stderr.strip().splitlines()[-1:]}
            return json.loads(out.stdout.strip().splitlines()[-1])

        concs = [1, 10] if q else [1, 10, 100]
        for tls in (0, 1):
            for conc in concs:
                for c in MOCK_CLIENTS:
                    slow = c.startswith("litellm")
                    if conc == 1:
                        args = ["--iters", str((10 if slow else 20) if q else (40 if slow else 100)), "--warmup", "3"]
                    else:
                        args = ["--conc", str(conc), "--rounds", str(1 if q or slow else (5 if conc == 10 else 3)), "--warmup", "2"]
                    row = one(c, "--tls", str(tls), *args)
                    print(f"  mock tls={tls} conc={conc} {c}: total_p50={row.get('total_p50')}", flush=True)
                    results["rows"].append(row)
        if a.rtt_ms > 0:
            procs.append(subprocess.Popen([sys.executable, os.path.join(HERE, "rttproxy.py"), str(a.rtt_ms), str(a.rtt_port), str(a.https_port)],
                                          cwd=HERE, stdout=subprocess.DEVNULL))
            time.sleep(1)
            for c in ["symphony-openai", "openai-sdk", "symphony-anthropic", "anthropic-sdk", "symphony-gemini", "google-genai"]:
                row = one(c, "--tls", "2", "--iters", "10" if q else "30", "--warmup", "3")
                row["rtt_ms"] = a.rtt_ms
                results["rtt_rows"].append(row)
        node_dir = os.path.join(HERE, "node")
        have_node = a.with_node and shutil.which("node") and os.path.isdir(os.path.join(node_dir, "node_modules"))
        if a.with_node and not have_node:
            print("  --with-node: run `npm install` in bench/node first; skipping Vercel AI SDK", flush=True)
        if have_node:
            for c in ("vercel-openai", "vercel-anthropic"):
                for tls in (0, 1):
                    for conc in concs:
                        args = [str(20 if q else 100), "0", "1"] if conc == 1 else ["0", str(conc), "1" if q else "3"]
                        out = subprocess.run(["node", "bench.mjs", c, str(tls), *args], env=env, cwd=node_dir, capture_output=True, text=True)
                        if out.returncode == 0:
                            results["node_rows"].append(json.loads(out.stdout.strip().splitlines()[-1]))
        results["coldstart"] = coldstart.run(5 if q else 20, tmp, node_dir if have_node else None)
    finally:
        for p in procs:
            p.terminate()
        shutil.rmtree(tmp, ignore_errors=True)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="local mock SSE benchmark (no network, no keys)")
    ap.add_argument("--quick", action="store_true", help="fewer iterations for a smoke run")
    ap.add_argument("--with-node", action="store_true", help="also run the Vercel AI SDK (needs npm install in bench/node)")
    ap.add_argument("--rtt-ms", type=float, default=40, help="emulated RTT for the TTFT-over-WAN rows (0 disables)")
    ap.add_argument("--http-port", type=int, default=8801)
    ap.add_argument("--https-port", type=int, default=8802)
    ap.add_argument("--rtt-port", type=int, default=8803)
    ap.add_argument("--live", action="store_true", help="live OpenAI Responses benchmark (needs OPENAI_API_KEY)")
    ap.add_argument("--model", action="append", default=[], help="OpenAI model id; repeatable")
    ap.add_argument("--budget-usd", type=float, default=None, help="hard cap for the whole live run (required with --live)")
    ap.add_argument("--rounds", type=int, default=15, help="interleaved rounds per model (each client: answer + tool loop per effort)")
    ap.add_argument("--efforts", default="none,low", help="reasoning efforts for reasoning models")
    ap.add_argument("--price-in", type=float, help="override $/1M input tokens")
    ap.add_argument("--price-out", type=float, help="override $/1M output tokens")
    ap.add_argument("--price-cached", type=float, help="override $/1M cached input tokens")
    ap.add_argument("--out", default=None, help="output directory")
    a = ap.parse_args()
    if not (a.mock or a.live):
        ap.error("pass --mock and/or --live")
    if a.live and (not a.model or a.budget_usd is None):
        ap.error("--live needs --model and --budget-usd")
    out = a.out or os.path.join(HERE, "results", datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    os.makedirs(out, exist_ok=True)
    import core_ai  # fail early if Symphony's provider layer is not importable
    results = {"started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "core_ai_file": core_ai.__file__,
               "python": sys.version.split()[0]}
    try:
        results["git_rev"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=os.path.dirname(core_ai.__file__),
                                            capture_output=True, text=True).stdout.strip() or None
    except OSError:
        results["git_rev"] = None
    if a.mock:
        print("mock: running", flush=True)
        results["mock"] = run_mock(a)
        write_json(os.path.join(out, "results.json"), results)
    if a.live:
        import live
        override = None
        if a.price_in is not None and a.price_out is not None:
            override = (a.price_in, a.price_out, a.price_cached if a.price_cached is not None else a.price_in)
        efforts = [e.strip() for e in a.efforts.split(",") if e.strip()]
        results["live"] = live.run(a.model, a.budget_usd, a.rounds, efforts, override)
    write_json(os.path.join(out, "results.json"), results)
    import report
    report.write(results, out)
    print(f"wrote {out}/results.json, report.md, report.png")
    if results.get("live") and not results["live"].get("skipped"):
        print(f"live spend (from usage tokens): ${results['live']['spent_usd']:.4f} of ${a.budget_usd}")


if __name__ == "__main__":
    main()
