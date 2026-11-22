"""One HTTP/1.1 connection pool per provider, shared by its concurrent streams."""

import urllib.request
from typing import Optional

import httpcore
import httpx

LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=100)


class ConnectionPool(httpcore.AsyncConnectionPool):
    """httpcore's pool, giving each idle connection to one request.

    HTTP/1.1 only: a connection handed to a request is not offered to another,
    so an HTTP/2 connection would not multiplex.

    httpcore 1.0.9 hands an idle connection to every queued request, and keeps
    handing it out until the winner starts sending. The losers raise
    ``ConnectionNotAvailable`` and retry on the next idle connection instead
    of opening one, so a burst of concurrent streams on a shared client runs
    over the few connections left idle by the last burst, a few at a time.
    It also evicts idle connections whenever the whole pool, not the idle
    part, is over ``max_keepalive_connections``. Upstream: encode/httpcore#1035.

    A connection that no request holds and that is not idle was opened for a
    request cancelled before it ran. It would stay connecting and hold a slot
    forever, so it is closed.
    """

    def _assign_requests_to_connections(self) -> list[httpcore.AsyncConnectionInterface]:
        closing: list[httpcore.AsyncConnectionInterface] = []
        reserved = {request.connection for request in self._requests if request.connection is not None}
        idle = sum(1 for connection in self._connections if connection.is_idle())

        for connection in list(self._connections):
            if connection.is_closed():
                self._connections.remove(connection)
            elif connection in reserved:
                continue
            elif connection.has_expired():
                self._connections.remove(connection)
                closing.append(connection)
                idle -= connection.is_idle()
            elif not connection.is_idle():
                self._connections.remove(connection)
                closing.append(connection)
            elif idle > self._max_keepalive_connections:
                self._connections.remove(connection)
                closing.append(connection)
                idle -= 1

        available = [
            connection
            for connection in self._connections
            if connection.is_available() and connection not in reserved
        ]
        for pool_request in [request for request in self._requests if request.is_queued()]:
            origin = pool_request.request.url.origin
            connection = next(
                (candidate for candidate in available if candidate.can_handle_request(origin)),
                None,
            )
            if connection is not None:
                available.remove(connection)
            elif len(self._connections) < self._max_connections:
                connection = self.create_connection(origin)
                self._connections.append(connection)
            elif available:
                # Full pool: replace an idle connection to another origin.
                stale = available.pop(0)
                self._connections.remove(stale)
                closing.append(stale)
                connection = self.create_connection(origin)
                self._connections.append(connection)
            else:
                continue
            pool_request.assign_to_connection(connection)
        return closing


class PooledTransport(httpx.AsyncHTTPTransport):
    """httpx's default HTTP/1.1 transport over `ConnectionPool`.

    Every pooled connection may stay idle (httpx keeps 20 of 100) until the
    5 s keep-alive expiry. A burst of concurrent streams that needed N
    connections then finds them all warm on the next turn, instead of 80 new
    TLS handshakes competing with 20 reused streams for the event loop.
    """

    def __init__(self, limits: httpx.Limits = LIMITS) -> None:
        # AsyncHTTPTransport's only state is its pool; build ours instead of
        # letting the base build, and pay the SSL context for, httpcore's.
        self._pool = ConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
        )


def provider_client(transport: Optional[httpx.AsyncBaseTransport] = None) -> httpx.AsyncClient:
    """The client a provider keeps for its lifetime.

    httpx reads HTTPS_PROXY, ALL_PROXY and NO_PROXY only when no transport is
    passed, so with any proxy variable set the provider gets httpx's own
    transport and proxy routing instead of `PooledTransport`.
    """
    if transport is None and not urllib.request.getproxies():
        transport = PooledTransport()
    return httpx.AsyncClient(transport=transport)
