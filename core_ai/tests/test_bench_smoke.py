"""Mock-only smoke run of bench/: Symphony's clients against the recorded fixture streams."""

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Tuple

import pytest

from sse_server import SSEServer

BENCH = Path(__file__).resolve().parents[2] / "bench"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"bench_{name}", BENCH / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("kind", ["openai", "anthropic", "gemini"])
def test_bench_symphony_client_streams_fixtures_on_one_connection(kind: str) -> None:
    fixtures = _load("fixtures")
    clients = _load("clients")
    frames = fixtures.STREAMS[kind]
    paths = {
        "openai": "/v1/chat/completions",
        "anthropic": "/v1/messages",
        "gemini": "/v1beta/models/gemini-3.8-flash:streamGenerateContent",
    }

    async def run() -> Tuple[int, list]:
        async with SSEServer({paths[kind]: frames}) as server:
            stream = clients.make(f"symphony-{kind}", server.base)
            results = [await stream() for _ in range(3)]
            return server.connections, results

    connections, results = asyncio.run(run())
    assert connections == 1
    for first_text, events in results:
        assert first_text is not None
        assert events > fixtures.N_TEXT
