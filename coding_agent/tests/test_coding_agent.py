import asyncio
from pathlib import Path
from typing import Any

from core_ai.types import Message, StreamEvent
from core_harness import NullControlPlane
from coding_agent import CodingAgent


class FakeRegistry:
    """Drives write → read → final answer so we exercise the harness tool loop."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ):
        self.calls.append({"model_id": model_id, "messages": messages, "tools": tools})
        tool_names = {tool["name"] for tool in tools}
        assert tool_names == {"read", "write", "bash"}

        completed = {
            message.tool_call_id
            for message in messages
            if message.role == "tool" and message.tool_call_id
        }

        if "call-write" not in completed:
            yield StreamEvent(
                type="toolcall_start",
                content_index=0,
                tool_call_id="call-write",
                tool_name="write",
            )
            yield StreamEvent(
                type="toolcall_delta",
                content_index=0,
                delta='{"path": "hello.txt", "content": "hi"}',
            )
            yield StreamEvent(type="done", content_index=0)
            return

        if "call-read" not in completed:
            yield StreamEvent(
                type="toolcall_start",
                content_index=0,
                tool_call_id="call-read",
                tool_name="read",
            )
            yield StreamEvent(
                type="toolcall_delta",
                content_index=0,
                delta='{"path": "hello.txt"}',
            )
            yield StreamEvent(type="done", content_index=0)
            return

        yield StreamEvent(type="text_delta", content_index=0, delta="hi")
        yield StreamEvent(type="done", content_index=0)


def test_coding_agent_uses_core_harness_tool_loop(tmp_path: Path) -> None:
    registry = FakeRegistry()
    control_plane = NullControlPlane()
    agent = CodingAgent(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:coding-model",
        workspace=tmp_path,
        control_plane=control_plane,
    )

    result = asyncio.run(agent.run("Write hello.txt with hi, then read it back."))

    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "hi"
    assert [call.name for call in result.tool_calls] == ["write", "read"]
    assert result.output_text == "hi"
    assert len(registry.calls) == 3

    event_types = [event.event_type for event in control_plane.events]
    assert event_types[0] == "run_started"
    assert event_types.count("tool_execution_completed") == 2
    assert event_types[-1] == "run_completed"
