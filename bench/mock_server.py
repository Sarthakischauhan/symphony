"""Multi-worker aiohttp mock replaying fixtures.STREAMS. Counts accepted TCP connections.

usage: python mock_server.py <http_port> <https_port> <cert.pem> <key.pem> [workers]
"""
import asyncio
import multiprocessing as mp
import signal
import ssl
import sys

from aiohttp import web

from fixtures import STREAMS

COUNTER = None


async def stream(kind, request):
    await request.read()
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await resp.prepare(request)
    for frame in STREAMS[kind]:
        await resp.write(frame)
    await resp.write_eof()
    return resp


async def stats(request):
    return web.json_response({"n": COUNTER.value})


async def reset(request):
    with COUNTER.get_lock():
        COUNTER.value = 0
    return web.json_response({"n": 0})


async def serve(http_port, https_port, cert, key):
    app = web.Application()
    app.router.add_post("/v1/chat/completions", lambda r: stream("openai", r))
    app.router.add_post("/v1/messages", lambda r: stream("anthropic", r))
    app.router.add_post(r"/v1beta/models/{m}", lambda r: stream("gemini", r))
    app.router.add_get("/stats", stats)
    app.router.add_get("/reset", reset)
    runner = web.AppRunner(app, keepalive_timeout=75)
    await runner.setup()
    inner = runner.server

    def factory():
        with COUNTER.get_lock():
            COUNTER.value += 1
        return inner()

    loop = asyncio.get_running_loop()
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(cert, key)
    await loop.create_server(factory, "127.0.0.1", http_port, backlog=1024, reuse_port=True)
    await loop.create_server(factory, "127.0.0.1", https_port, ssl=ctx, backlog=1024, reuse_port=True)
    print("ready", flush=True)
    await asyncio.Event().wait()


def worker(counter, *args):
    global COUNTER
    COUNTER = counter
    asyncio.run(serve(*args))


if __name__ == "__main__":
    http_port, https_port, cert, key = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
    workers = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    counter = mp.Value("i", 0)
    procs = [mp.Process(target=worker, args=(counter, http_port, https_port, cert, key)) for _ in range(workers)]
    for p in procs:
        p.start()

    def _stop(signum, frame):  # run.py terminates us; take the workers down too
        for p in procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    for p in procs:
        p.join()
