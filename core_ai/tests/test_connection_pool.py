"""Concurrent streams on one shared client each get their own connection."""

import asyncio

import httpcore
import httpx
import pytest
from httpcore._async.connection_pool import AsyncPoolRequest

from core_ai.providers.connection_pool import ConnectionPool, PooledTransport, provider_client
from sse_server import SSEServer

FRAMES = {"/stream": [b'data: {"n": 1}\n\n', b'data: {"n": 2}\n\n', b"data: [DONE]\n\n"]}


class CountingPool(ConnectionPool):
    passes = 0

    def _assign_requests_to_connections(self) -> list[object]:
        CountingPool.passes += 1
        return super()._assign_requests_to_connections()


def test_burst_gives_each_request_its_own_connection() -> None:
    """Two warm idle connections and a burst of ten: each idle connection goes
    to one request and the other eight open their own, with no retries.

    httpcore runs one assignment pass when a request arrives and one when its
    response closes, so 2 per request also shows the override is the method
    httpcore calls."""

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


async def _close_after_response(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    await reader.readuntil(b"\r\n\r\n")
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
    await writer.drain()
    writer.close()


def test_cancelled_request_does_not_leak_its_new_connection() -> None:
    """A queued request is given a new connection when the only one closes,
    then is cancelled before it runs. The never-connected connection is closed,
    so the single slot is free for the next request instead of a PoolTimeout."""

    async def run() -> None:
        server = await asyncio.start_server(_close_after_response, "127.0.0.1", 0)
        url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
        try:
            async with ConnectionPool(max_connections=1) as pool:
                first = await pool.handle_async_request(httpcore.Request("GET", url, headers=[(b"Host", b"x")]))
                queued = asyncio.create_task(pool.request("GET", url))
                await asyncio.sleep(0.05)
                await first.aread()
                await first.aclose()
                queued.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await queued
                response = await pool.request("GET", url, extensions={"timeout": {"pool": 2}})
                assert response.status == 200
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_httpcore_internals_the_pool_relies_on() -> None:
    """`ConnectionPool` replaces one private httpcore method and reads its
    state; `PooledTransport` sets httpx's only transport attribute. httpcore is
    pinned below 1.1; this fails if a release moves any of them."""
    assert "_assign_requests_to_connections" in vars(httpcore.AsyncConnectionPool)
    assert "create_connection" in vars(httpcore.AsyncConnectionPool)
    assert {"_requests", "_connections", "_max_connections", "_max_keepalive_connections"} <= vars(
        httpcore.AsyncConnectionPool()
    ).keys()
    request = AsyncPoolRequest(httpcore.Request("GET", "http://127.0.0.1/"))
    assert {"request", "connection"} <= vars(request).keys()
    assert {"is_queued", "assign_to_connection"} <= vars(AsyncPoolRequest).keys()
    assert vars(httpx.AsyncHTTPTransport()).keys() == {"_pool"}


@pytest.mark.parametrize("variable", ["HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"])
def test_proxy_settings_keep_httpx_proxy_routing(monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv(variable, "localhost" if variable == "NO_PROXY" else "http://proxy.invalid:3128")

    client = provider_client()

    assert not isinstance(client._transport, PooledTransport)
    if variable != "NO_PROXY":
        assert client._mounts


def test_requests_go_through_the_env_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bytes] = []

    async def proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        seen.append(head.split(b"\r\n", 1)[0])
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    async def run() -> None:
        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            monkeypatch.delenv(name, raising=False)
            monkeypatch.delenv(name.lower(), raising=False)
        monkeypatch.setenv("ALL_PROXY", f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}")
        try:
            async with provider_client() as client:
                response = await client.get("http://upstream.invalid/v1/models")
            assert response.text == "ok"
            assert seen == [b"GET http://upstream.invalid/v1/models HTTP/1.1"]
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_no_proxy_settings_use_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    assert isinstance(provider_client()._transport, PooledTransport)
