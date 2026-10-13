"""Agent Client Protocol host: mapping and the session loop, with a fake agent."""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
from typing import Any

import pytest

from core_harness import Answer, HarnessCancelled, HarnessLimitExceeded, Interrupt, UserInput

from coding_agent.protocols import acp
from coding_agent.protocols.acp.mapping import (
    permission_answer,
    permission_request,
    prompt_text,
    session_updates,
)


def test_stream_events_become_session_updates() -> None:
    assert session_updates("text_delta", {"delta": "Hi"}) == [
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Hi"}}
    ]
    assert session_updates("reasoning_delta", {"delta": "hmm"})[0]["sessionUpdate"] == "agent_thought_chunk"
    assert session_updates("tool_call_started", {"tool_call_id": "c1", "tool_name": "bash"}) == [
        {"sessionUpdate": "tool_call", "toolCallId": "c1", "title": "bash", "kind": "execute", "status": "pending"}
    ]
    assert session_updates("tool_call_arguments", {"tool_call_id": "c1", "arguments": '{"command": "ls"}'}) == [
        {"sessionUpdate": "tool_call_update", "toolCallId": "c1", "rawInput": {"command": "ls"}}
    ]
    assert session_updates("tool_call_arguments", {"tool_call_id": "c1", "arguments": '{"comm'}) == []
    started = session_updates("tool_execution_started", {"tool_call_id": "c1", "arguments": {"command": "ls"}})
    assert started == [{
        "sessionUpdate": "tool_call_update", "toolCallId": "c1", "status": "in_progress",
        "rawInput": {"command": "ls"},
    }]
    done = session_updates("tool_execution_completed", {"tool_call_id": "c1", "status": "error", "result": "boom"})
    assert done[0]["status"] == "failed"
    assert done[0]["content"] == [{"type": "content", "content": {"type": "text", "text": "boom"}}]
    assert session_updates("context", {"tokens_used": 23, "context_limit": 400}) == [
        {"sessionUpdate": "usage_update", "used": 23, "size": 400}
    ]
    assert session_updates("run_started", {"prompt": "x"}) == []


def test_subagent_events_are_not_narrated() -> None:
    assert session_updates("text_delta", {"delta": "child", "parent_id": "root"}) == []


def test_approval_question_round_trips_through_permission_options() -> None:
    asked = {
        "request_id": "q-1", "question": "Allow bash command once?", "kind": "approval",
        "choices": ["Allow once", "Always allow", "Deny"], "tool_call_id": "c1",
    }
    request = permission_request("s-1", asked)
    assert request["sessionId"] == "s-1"
    assert request["toolCall"] == {"toolCallId": "c1", "title": "Allow bash command once?"}
    assert [(o["optionId"], o["kind"]) for o in request["options"]] == [
        ("0", "allow_once"), ("1", "allow_always"), ("2", "reject_once"),
    ]
    assert permission_answer({"outcome": "selected", "optionId": "1"}, asked) == "Always allow"
    assert permission_answer({"outcome": "cancelled"}, asked) == "Deny"
    assert permission_answer({"outcome": "selected", "optionId": "9"}, asked) == "Deny"
    assert permission_answer(None, {"kind": "question", "default": "blue"}) == "blue"


def test_prompt_blocks_flatten_to_text() -> None:
    assert prompt_text([
        {"type": "text", "text": "Fix this"},
        {"type": "resource_link", "name": "a.py", "uri": "file:///a.py"},
        {"type": "resource", "resource": {"uri": "file:///b.py", "text": "print(1)"}},
        {"type": "image", "data": "...", "mimeType": "image/png"},
    ]) == "Fix this\n\nfile:///a.py\n\nfile:///b.py\nprint(1)"


class FakeHarness:
    def __init__(self) -> None:
        self.ops: list[Any] = []
        self.sink: Any = None
        self.accept = True

    def submit(self, op: Any) -> bool:
        self.ops.append(op)
        if isinstance(op, Answer):
            return self.sink.interaction.answer(op.request_id, op.value)
        return self.accept


class FakeAgent:
    """Emits a short run and asks one approval through the sink."""

    session_id = "session-acp"

    def __init__(self, sink: Any, behaviour: str = "approve") -> None:
        self.sink = sink
        self.behaviour = behaviour
        self.harness = FakeHarness()
        self.harness.sink = sink
        self.answers: list[str] = []
        self.prompts: list[str] = []

    async def run(self, prompt: str) -> None:
        self.prompts.append(prompt)
        if self.behaviour == "cancelled":
            raise HarnessCancelled("user_cancel")
        if self.behaviour == "limit":
            raise HarnessLimitExceeded("max_turns", 4, 4, "too many turns")
        if self.behaviour == "boom":
            raise RuntimeError("provider down")
        await self.sink.emit("tool_call_started", {"tool_call_id": "c1", "tool_name": "bash"})
        self.answers.append(await self.sink.interaction.request_user_input(
            question="Allow bash command once?", choices=["Allow once", "Deny"], kind="approval",
            metadata={"tool_name": "bash", "tool_call_id": "c1"},
        ))
        await self.sink.emit("text_delta", {"delta": "done"})


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch):
    sent: list[dict[str, Any]] = []
    agents: list[FakeAgent] = []
    state = SimpleNamespace(sent=sent, agents=agents, behaviour="approve")

    def build_agent(**kwargs: Any) -> FakeAgent:
        assert kwargs["client"] == "acp"
        agent = FakeAgent(kwargs["sink"], state.behaviour)
        agents.append(agent)
        return agent

    monkeypatch.setattr(acp, "write_message", sent.append)
    monkeypatch.setattr(acp, "load_provider_env", lambda _workspace: None)
    monkeypatch.setattr(acp, "build_agent", build_agent)
    return state


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def _open(server: acp.Server, tmp_path: Any) -> None:
    await server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}})
    await server.handle({"jsonrpc": "2.0", "id": 2, "method": "session/new",
                         "params": {"cwd": str(tmp_path), "mcpServers": []}})


def test_prompt_turn_streams_updates_asks_permission_and_ends(host, tmp_path) -> None:
    async def scenario() -> None:
        server = acp.Server()
        await _open(server, tmp_path)
        assert host.sent[0]["result"]["protocolVersion"] == 1
        assert host.sent[0]["result"]["agentCapabilities"]["loadSession"] is False
        assert host.sent[1] == {"jsonrpc": "2.0", "id": 2, "result": {"sessionId": "session-acp"}}

        await server.handle({"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": {
            "sessionId": "session-acp", "prompt": [{"type": "text", "text": "list files"}],
        }})
        await _settle()
        tool_call, ask = host.sent[2], host.sent[3]
        assert tool_call["method"] == "session/update"
        assert tool_call["params"]["update"]["sessionUpdate"] == "tool_call"
        assert ask["method"] == "session/request_permission"
        assert ask["params"]["toolCall"]["toolCallId"] == "c1"

        await server.handle({"jsonrpc": "2.0", "id": ask["id"],
                             "result": {"outcome": {"outcome": "selected", "optionId": "0"}}})
        await _settle()
        agent = host.agents[0]
        assert agent.prompts == ["list files"] and agent.answers == ["Allow once"]
        assert host.sent[4]["params"]["update"]["sessionUpdate"] == "agent_message_chunk"
        assert host.sent[5] == {"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}}

    asyncio.run(scenario())


@pytest.mark.parametrize(("behaviour", "stop"), [("cancelled", "cancelled"), ("limit", "max_turn_requests")])
def test_prompt_stop_reasons(host, tmp_path, behaviour: str, stop: str) -> None:
    host.behaviour = behaviour

    async def scenario() -> None:
        server = acp.Server()
        await _open(server, tmp_path)
        await server.handle({"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": {
            "sessionId": "session-acp", "prompt": [{"type": "text", "text": "go"}],
        }})
        await _settle()
        assert host.sent[-1] == {"jsonrpc": "2.0", "id": 3, "result": {"stopReason": stop}}

    asyncio.run(scenario())


def test_cancel_and_steer_become_harness_ops(host, tmp_path) -> None:
    async def scenario() -> None:
        server = acp.Server()
        await _open(server, tmp_path)
        await server.handle({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "session-acp"}})
        await server.handle({"jsonrpc": "2.0", "id": 4, "method": "_symphony/steer", "params": {
            "sessionId": "session-acp", "prompt": [{"type": "text", "text": "use metric units"}],
        }})
        assert host.agents[0].harness.ops == [Interrupt("user_cancel"), UserInput("use metric units")]
        assert host.sent[-1] == {"jsonrpc": "2.0", "id": 4, "result": {"accepted": True}}

    asyncio.run(scenario())


def test_bad_requests_get_json_rpc_errors(host, tmp_path) -> None:
    host.behaviour = "boom"

    async def scenario() -> list[int]:
        server = acp.Server()
        await server.handle({"jsonrpc": "2.0", "id": 1, "method": "session/unknown"})
        await server.handle({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": "relative"}})
        await server.handle({"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": {"sessionId": "nope"}})
        await _open(server, tmp_path)
        await server.handle({"jsonrpc": "2.0", "id": 5, "method": "session/prompt", "params": {
            "sessionId": "session-acp", "prompt": [{"type": "text", "text": "go"}],
        }})
        await _settle()
        return [message["error"]["code"] for message in host.sent if "error" in message]

    assert asyncio.run(scenario()) == [-32601, -32602, -32602, -32603]


def test_serve_reads_lines_until_stdin_closes(host, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acp.sys, "stdin", io.StringIO(
        'not json\n'
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1}}\n'
    ))
    assert asyncio.run(acp.serve()) == 0
    assert host.sent[0]["error"]["code"] == -32700
    assert host.sent[1]["result"]["agentInfo"]["name"] == "symphony"
