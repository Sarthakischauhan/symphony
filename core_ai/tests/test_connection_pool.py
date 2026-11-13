"""Concurrent streams on one shared client each get their own connection."""

import asyncio

import httpx

from core_ai.providers.http import ConnectionPool, PooledTransport
from sse_server import SSEServer

FRAMES = {"/stream": [b'data: {"n": 1}\n\n', b'data: {"n": 2}\n\n', b"data: [DONE]\n\n"]}


class CountingPool(ConnectionPool):
    passes = 0

    def _assign_requests_to_connections(self) -> list[object]:
        CountingPool.passes += 1
        return super()._assign_requests_to_connections()


def test_burst_gives_each_request_its_own_connection() -> None:
    """Two warm idle connections and a burst of ten: each idle connection goes
    to one request and the other eight open their own, with no retries (one
    assignment pass when a request arrives and one when its response closes)."""

    async def run() -> None:
        async with SSEServer(FRAMES) as server, CountingPool() as pool:

            async def one() -> None:
                async with pool.stream("POST", server.base + "/stream") as response:
                    await response.aread()

            await asyncio.gather(one(), one())
            assert server.connections == 2
            CountingPool.passes = 0
            await asyncio.gather(*(one() for _ in range(10)))
            assert CountingPool.passes == 2 * 10
            assert server.connections == 10

    asyncio.run(run())


def test_next_burst_reuses_every_connection() -> None:
    """A burst wider than httpx's 20 keep-alive connections finds all of them
    warm on the next turn."""

    async def run() -> None:
        async with SSEServer(FRAMES) as server, httpx.AsyncClient(transport=PooledTransport()) as client:

            async def one() -> None:
                async with client.stream("POST", server.base + "/stream") as response:
                    await response.aread()

            for _ in range(3):
                await asyncio.gather(*(one() for _ in range(30)))
            assert server.connections == 30
            assert server.closed == 0

    asyncio.run(run())
