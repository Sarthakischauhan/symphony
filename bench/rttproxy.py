"""Userspace WAN emulator: delays each direction by RTT/2. usage: rttproxy.py <rtt_ms> <listen_port> <upstream_tls_port>"""
import asyncio
import sys
DELAY = float(sys.argv[1]) / 2000 if len(sys.argv) > 1 else 0.02  # arg 1 = RTT ms
LISTEN = int(sys.argv[2]) if len(sys.argv) > 2 else 8803
UPSTREAM = int(sys.argv[3]) if len(sys.argv) > 3 else 8802

async def pipe(reader, writer):
    q = asyncio.Queue()
    loop = asyncio.get_running_loop()
    async def sender():
        while True:
            due, data = await q.get()
            if data is None:
                break
            wait = due - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            writer.write(data)
            await writer.drain()
        writer.close()
    t = asyncio.create_task(sender())
    try:
        while data := await reader.read(65536):
            q.put_nowait((loop.time() + DELAY, data))
    finally:
        q.put_nowait((loop.time() + DELAY, None))
        await t

async def handle(cr, cw):
    sr, sw = await asyncio.open_connection("127.0.0.1", UPSTREAM)
    await asyncio.gather(pipe(cr, sw), pipe(sr, cw), return_exceptions=True)

async def main():
    s = await asyncio.start_server(handle, "127.0.0.1", LISTEN, backlog=1024)
    print("proxy ready", DELAY * 2000, "ms RTT", flush=True)
    await s.serve_forever()
asyncio.run(main())
