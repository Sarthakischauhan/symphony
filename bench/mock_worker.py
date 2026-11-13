"""One client, one process: sequential or concurrent streams against the mock. Prints one JSON line."""
import argparse
import asyncio
import json
import os
import resource
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clients  # noqa: E402
from _common import pct  # noqa: E402
from fixtures import TOKENS  # noqa: E402


def rss_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024


def server_conns(http_port, reset=False):
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{http_port}/{'reset' if reset else 'stats'}"))["n"]


async def main(a):
    base = {0: f"http://127.0.0.1:{a.http_port}", 1: f"https://localhost:{a.https_port}", 2: f"https://localhost:{a.rtt_port}"}[a.tls]
    t0 = time.perf_counter()
    run = clients.make(a.client, base)
    out = {"client": a.client, "tls": a.tls, "import_construct_ms": (time.perf_counter() - t0) * 1e3, "rss_after_construct_mb": rss_mb()}
    for _ in range(a.warmup):
        await run()
    server_conns(a.http_port, reset=True)

    async def one():
        s = time.perf_counter()
        first, n = await run()
        return (first - s) * 1e3, (time.perf_counter() - s) * 1e3, n

    cpu0 = time.process_time()
    w0 = time.perf_counter()
    if a.conc <= 1:
        res = [await one() for _ in range(a.iters)]
        requests = a.iters
    else:
        res = []
        for _ in range(a.rounds):
            res += await asyncio.gather(*[one() for _ in range(a.conc)])
        requests = a.conc * a.rounds
    wall = time.perf_counter() - w0
    cpu = time.process_time() - cpu0
    tt = [r[0] for r in res]
    tot = [r[1] for r in res]
    out.update(conc=a.conc, ttfe_p50=pct(tt, 50), ttfe_p95=pct(tt, 95), total_p50=pct(tot, 50), total_p95=pct(tot, 95),
               events=res[-1][2], events_per_s=res[-1][2] / (pct(tot, 50) / 1e3),
               cpu_ms_per_1k_tok=cpu * 1e3 / requests / (TOKENS / 1000), requests=requests,
               wall_ms_per_round=wall * 1e3 / (a.rounds if a.conc > 1 else 1),
               new_tcp_conns=server_conns(a.http_port) - 1,
               peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    print(json.dumps(out))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("client")
    p.add_argument("--tls", type=int, default=0)
    p.add_argument("--iters", type=int, default=100)
    p.add_argument("--warmup", type=int, default=3)
    p.add_argument("--conc", type=int, default=1)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--http-port", type=int, default=8801)
    p.add_argument("--https-port", type=int, default=8802)
    p.add_argument("--rtt-port", type=int, default=8803)
    asyncio.run(main(p.parse_args()))
