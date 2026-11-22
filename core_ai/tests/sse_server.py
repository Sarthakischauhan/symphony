"""A keep-alive HTTP/1.1 SSE server on loopback that counts TCP connections."""

import asyncio
import json
from typing import Dict, List, Tuple


class SSEServer:
    """Serves ``frames[path]`` as a chunked ``text/event-stream`` body, one chunk per frame."""

    def __init__(self, frames: Dict[str, List[bytes]]) -> None:
        self.frames = frames
        self.connections = 0
        self.closed = 0
        self.requests: List[Tuple[str, Dict[str, object]]] = []
        self._server: asyncio.AbstractServer | None = None

    @property
    def base(self) -> str:
        assert self._server is not None
        port = self._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def __aenter__(self) -> "SSEServer":
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                request_line, *header_lines = head.decode().split("\r\n")
                headers = {
                    name.strip().lower(): value.strip()
                    for name, _, value in (line.partition(":") for line in header_lines if line)
                }
                body = await reader.readexactly(int(headers.get("content-length", "0")))
                path = request_line.split(" ")[1].split("?")[0]
                self.requests.append((path, json.loads(body) if body else {}))
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                    b"Transfer-Encoding: chunked\r\n\r\n"
                )
                for frame in self.frames[path]:
                    writer.write(f"{len(frame):x}\r\n".encode() + frame + b"\r\n")
                    await writer.drain()
                writer.write(b"0\r\n\r\n")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            self.closed += 1
        finally:
            writer.close()
