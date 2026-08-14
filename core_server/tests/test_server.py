"""SSE server tests against a fake model registry (no live API)."""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any

import httpx
import pytest
import uvicorn
from core_ai.types import Message, StreamEvent
from core_harness import Tool
from fastapi.testclient import TestClient

from core_server import ServerConfig, build_config, create_app, encode_sse
from core_server.sse import SSEControlPlane
from core_harness.models.control_plane import ControlPlaneEvent


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ):
        self.calls.append(
            {"model_id": model_id, "messages": messages, "tools": tools}
        )
        tool_names = {item.get("name") for item in tools}
        if "echo" in tool_names and len(self.calls) == 1:
            yield StreamEvent(
                type="toolcall_start",
                content_index=0,
                tool_call_id="call-echo",
                tool_name="echo",
            )
            yield StreamEvent(
                type="toolcall_delta",
                content_index=0,
                delta='{"text": "pong"}',
            )
            yield StreamEvent(type="usage", prompt_tokens=4, completion_tokens=2, total_tokens=6)
            yield StreamEvent(type="done", content_index=0)
            return
        yield StreamEvent(type="text_delta", content_index=0, delta="hello from harness")
        yield StreamEvent(type="usage", prompt_tokens=8, completion_tokens=3, total_tokens=11)
        yield StreamEvent(type="done", content_index=0)


def echo(text: str) -> str:
    return text


def make_app(*, tools: list[Tool] | None = None, system_prompt: str = "Be brief.") -> tuple[Any, FakeRegistry]:
    registry = FakeRegistry()
    app = create_app(
        ServerConfig(
            registry=registry,  # type: ignore[arg-type]
            model_id="openai:test",
            system_prompt=system_prompt,
            tools=tools or [],
        )
    )
    return app, registry


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    event_type = "message"
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "":
            if data_lines:
                events.append((event_type, json.loads("\n".join(data_lines))))
            event_type = "message"
            data_lines = []
    if data_lines:
        events.append((event_type, json.loads("\n".join(data_lines))))
    return events


def test_health_reports_model_and_tools() -> None:
    app, _ = make_app(tools=[Tool(echo)])
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["model_id"] == "openai:test"
    assert body["tools"] == ["echo"]


def test_default_model_is_luna() -> None:
    config = build_config(registry=FakeRegistry())  # type: ignore[arg-type]
    assert config.model_id == "openai:gpt-5.6-luna"


def test_runs_stream_harness_events() -> None:
    app, registry = make_app()
    with TestClient(app).stream("POST", "/runs", json={"message": "hi"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(response.read().decode())

    names = [name for name, _ in events]
    assert names[0] == "run_started"
    assert "text_delta" in names
    assert names[-1] == "run_completed"
    delta = next(payload for name, payload in events if name == "text_delta")
    assert delta["payload"]["delta"] == "hello from harness"
    assert "Be brief." in str(registry.calls[0]["messages"][0].content)


def test_custom_prompt_and_tools_are_used() -> None:
    app, registry = make_app(tools=[Tool(echo)], system_prompt="Use the echo tool.")
    with TestClient(app).stream(
        "POST",
        "/runs",
        json={"message": "ping", "system_prompt": "Always echo.", "model_id": "openai:custom"},
    ) as response:
        events = parse_sse(response.read().decode())

    names = [name for name, _ in events]
    assert "tool_execution_completed" in names
    assert registry.calls[0]["model_id"] == "openai:custom"
    assert "Always echo." in str(registry.calls[0]["messages"][0].content)
    result = next(payload for name, payload in events if name == "tool_execution_completed")
    assert result["payload"]["result"] == "pong"


def test_runs_accept_conversation_history() -> None:
    app, registry = make_app()
    with TestClient(app).stream(
        "POST",
        "/runs",
        json={
            "message": "continue",
            "conversation": [
                {"role": "user", "content": "remember this"},
                {"role": "assistant", "content": "I will"},
            ],
        },
    ) as response:
        response.read()

    contents = [message.content for message in registry.calls[0]["messages"]]
    assert "remember this" in contents
    assert "I will" in contents
    assert "continue" in contents


def test_encode_sse_uses_harness_event_shape() -> None:
    frame = encode_sse(ControlPlaneEvent.typed("text_delta", {"delta": "hi"}))
    assert frame.startswith("event: text_delta\n")
    assert json.loads(frame.split("data: ", 1)[1]) == {
        "event_type": "text_delta",
        "payload": {"delta": "hi"},
    }


def test_sse_control_plane_queues_events() -> None:
    async def scenario() -> None:
        plane = SSEControlPlane()
        await plane.emit("run_started", {"model_id": "openai:test"})
        event = await plane.queue.get()
        assert event is not None
        assert event.event_type == "run_started"
        await plane.close()
        assert await plane.queue.get() is None

    import asyncio

    asyncio.run(scenario())


def test_running_uvicorn_server_streams_events() -> None:
    app, _ = make_app()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(50):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started
        with httpx.stream(
            "POST",
            f"http://127.0.0.1:{port}/runs",
            json={"message": "hi"},
            timeout=10.0,
        ) as response:
            assert response.status_code == 200
            events = parse_sse(response.read().decode())
        names = [name for name, _ in events]
        assert "run_started" in names
        assert "run_completed" in names
        health = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5.0)
        assert health.json()["ok"] is True
    finally:
        server.should_exit = True
        thread.join(timeout=5)
