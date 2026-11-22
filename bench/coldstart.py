"""Cold import time per package (subprocess, p50/p95 net of bare interpreter) + client construction."""
import subprocess
import sys
import time

from _common import pct
from clients import IMPORTS

CONSTRUCT = {
    "symphony": "from core_ai.providers.openai import OpenAIProvider as C; mk=lambda: C(api_key='k')",
    "openai-sdk": "from openai import AsyncOpenAI as C; mk=lambda: C(api_key='k')",
    "anthropic-sdk": "from anthropic import AsyncAnthropic as C; mk=lambda: C(api_key='k')",
    "google-genai": "from google import genai; mk=lambda: genai.Client(api_key='k')",
}


def timed(args, n, cwd):
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        subprocess.run(args, check=True, cwd=cwd, stdout=subprocess.DEVNULL)
        ts.append((time.perf_counter() - t) * 1e3)
    return ts


def run(n, cwd, node_dir=None):
    py = sys.executable
    base = pct(timed([py, "-c", "pass"], n, cwd), 50)
    res = {"python_baseline_ms": base}
    for name, code in IMPORTS.items():
        ts = timed([py, "-c", code], n, cwd)
        rss = subprocess.run([py, "-c", code + "\nimport resource;print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)"],
                             capture_output=True, text=True, cwd=cwd).stdout.split()[-1]
        res[name] = {"net_p50": pct(ts, 50) - base, "net_p95": pct(ts, 95) - base, "rss_mb": int(rss) / 1024}
    for name, code in CONSTRUCT.items():
        out = subprocess.run([py, "-c", code + "\nimport time\nmk()\nt=time.perf_counter()\nfor _ in range(200): mk()\n"
                              "print((time.perf_counter()-t)/200*1e3)"], capture_output=True, text=True, cwd=cwd).stdout.split()[-1]
        res[name]["construct_ms"] = float(out)
    import httpx
    t = time.perf_counter()
    for _ in range(100):
        httpx.AsyncClient()
    res["symphony"]["per_request_asyncclient_ms"] = (time.perf_counter() - t) / 100 * 1e3
    if node_dir:
        nb = pct(timed(["node", "-e", "1"], n, node_dir), 50)
        ts = timed(["node", "--input-type=module", "-e", "await import('ai'); await import('@ai-sdk/openai'); await import('@ai-sdk/anthropic')"], n, node_dir)
        res["vercel-ai-sdk"] = {"net_p50": pct(ts, 50) - nb, "net_p95": pct(ts, 95) - nb}
    return res
