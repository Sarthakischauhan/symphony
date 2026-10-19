"""The stdio transport preserves approval questions and event frames."""

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core_ai import ModelInfo
from coding_agent.protocols import stdio
from addon_fakes import no_user_addons


def test_interactive_input_is_correlated(monkeypatch):
    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    sink = stdio.StdioSink()

    async def scenario():
        pending = asyncio.create_task(sink.interaction.request_user_input(
            question="Allow bash?", choices=["Allow once", "Deny"], kind="approval",
        ))
        await asyncio.sleep(0)
        frame = frames.pop()
        assert frame["type"] == "input_requested"
        # Every host carries the question as the same event; the frame is the alias.
        event = frames.pop()
        assert event["type"] == "event" and event["event"] == "question_asked"
        assert event["payload"]["request_id"] == frame["request_id"]
        assert frame["kind"] == "approval"
        sink.interaction.pending[frame["request_id"]].set_result("Deny")
        assert await pending == "Deny"
        assert not sink.interaction.pending
        await sink.emit("text_delta", {"delta": "hello"})
        assert frames == [{"type": "event", "event": "text_delta", "payload": {"delta": "hello"}}]

    asyncio.run(scenario())


def test_frame_is_one_json_line(monkeypatch):
    output = []

    class Stdout:
        def write(self, value):
            output.append(value)

        def flush(self):
            pass

    monkeypatch.setattr(stdio.sys, "__stdout__", Stdout())
    stdio.write_frame({"type": "ready", "session_id": "abc"})
    assert json.loads("".join(output)) == {"type": "ready", "session_id": "abc"}
    assert "".join(output).endswith("\n")


def test_staged_image_is_inlined(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nexample")
    parts = stdio.user_content("Look at this", [str(image)])
    assert parts[0] == {"type": "text", "text": "Look at this"}
    assert parts[1]["type"] == "image"
    assert parts[1]["media_type"] == "image/png"
    assert parts[1]["filename"] == "image.png"


def test_model_list_request_includes_provider_and_context(monkeypatch):
    import core_ai

    class Registry:
        def namespaces(self):
            return ("openai",)

        def models(self):
            return [ModelInfo(id="gpt-test", provider="openai", api="responses", context_limit=128000)]

    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda _workspace: None)
    monkeypatch.setattr(core_ai, "default_model_id", lambda _registry: "openai:gpt-test")
    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(tools=[], 
        registry=Registry(), session_id="session-test",
        harness=SimpleNamespace(model_id="openai:gpt-test"),
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO(
        '{"type":"model/list","request_id":"catalog-1"}\n'
    ))
    assert asyncio.run(stdio.serve(Path("."), None, None)) == 0
    assert frames[0]["type"] == "ready"
    assert frames[1]["type"] == "models"
    assert frames[1]["request_id"] == "catalog-1"
    assert frames[1]["default"] == "openai:gpt-test"
    assert frames[1]["models"] == [{
        "id": "openai:gpt-test", "label": "gpt-test", "provider": "openai",
        "description": "openai", "context_limit": 128000, "reasoning_levels": [],
    }]


def test_command_catalog_is_the_tui_catalog(monkeypatch):
    from coding_agent.tui.commands.catalog import SLASH_COMMANDS

    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda _workspace: None)
    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(tools=[], 
        session_id="session-test", harness=SimpleNamespace(model_id="openai:gpt-test"),
        user_addons=no_user_addons(),
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO(
        '{"type":"command/list","request_id":"commands-1"}\n'
    ))
    assert asyncio.run(stdio.serve(Path("."), None, None)) == 0
    assert frames[1]["request_id"] == "commands-1"
    assert {item["name"] for item in frames[1]["commands"]} == {
        item.name for item in SLASH_COMMANDS
    }


def test_slash_command_does_not_call_the_model(monkeypatch):
    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda _workspace: None)
    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(tools=[], 
        session_id="session-test", harness=SimpleNamespace(model_id="openai:gpt-test"),
        user_addons=no_user_addons(),
        run=lambda *_args: (_ for _ in ()).throw(AssertionError("model was called")),
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO(
        '{"type":"run","prompt":"/help"}\n'
    ))
    assert asyncio.run(stdio.serve(Path("."), None, None)) == 0
    assert any(frame.get("event") == "text_delta" and "/model" in frame["payload"]["delta"] for frame in frames)


def test_protocol_catalog_includes_dynamic_argument_choices(monkeypatch, tmp_path):
    from coding_agent.protocols.stdio import commands
    monkeypatch.setattr(commands, "load_personalities", lambda: [
        SimpleNamespace(id="custom", name="Custom personality", description="Workspace choice")
    ])
    plans = tmp_path / ".symphony" / "plans"
    plans.mkdir(parents=True)
    (plans / "test_plan.md").write_text("# Test plan")
    catalog = {item["name"]: item for item in commands.catalog(tmp_path)}
    assert catalog["personality"]["options"] == [
        {"value": "custom", "label": "Custom personality", "description": "Workspace choice"}
    ]
    assert not {"mode", "plan", "plans"} & catalog.keys()


def test_personality_command_accepts_whitespace_and_applies_prompt(monkeypatch, tmp_path):
    from coding_agent.protocols.stdio import commands
    applied = []
    monkeypatch.setattr(commands, "load_personalities", lambda: [
        SimpleNamespace(id="precise", name="Precise", description="Careful")
    ])
    monkeypatch.setattr(commands, "ensure_spawn_settings", lambda workspace, **kwargs:
                        SimpleNamespace(personality=kwargs["overrides"]["personality"]))
    agent = SimpleNamespace(workspace=tmp_path, config=SimpleNamespace(personality="direct"),
                            apply_system_prompt=lambda: applied.append(True))
    assert "precise" in asyncio.run(commands.execute(agent, "/personality "))
    assert asyncio.run(commands.execute(agent, "/personality\tprecise")) == "Personality: Precise."
    assert agent.config.personality == "precise"
    assert applied == [True]


def test_command_attachments_are_rejected_without_inference(monkeypatch):
    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda workspace: None)
    monkeypatch.setattr(stdio, "build_agent", lambda **kwargs: SimpleNamespace(tools=[], 
        session_id="session-test", harness=SimpleNamespace(model_id="test"),
        user_addons=no_user_addons(),
        run=lambda *args: (_ for _ in ()).throw(AssertionError("model called")),
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO(
        '{"type":"run","prompt":"/personality ","attachments":["image.png"]}\n'
    ))
    asyncio.run(stdio.serve(Path("."), None, None))
    assert any(frame.get("type") == "error" and "attachments" in frame["message"] for frame in frames)
    assert any(frame.get("type") == "done" and frame["status"] == "errored" for frame in frames)


def test_reload_refreshes_live_agent_configuration(monkeypatch, tmp_path):
    from coding_agent.protocols.stdio import commands
    import coding_agent.config.credentials as credentials
    called = []
    monkeypatch.setattr(credentials, "load_provider_env", lambda workspace, **kwargs: called.append("env"))
    config = SimpleNamespace(personality="warm")
    monkeypatch.setattr(commands, "ensure_spawn_settings", lambda workspace: config)
    agent = SimpleNamespace(workspace=tmp_path, config=None, mode="plan",
                            apply_system_prompt=lambda: called.append("prompt"),
                            reload_user_addons=lambda: called.append("addons") or "no tool changes")
    reply = asyncio.run(commands.execute(agent, "/reload"))
    assert "Reloaded" in reply and "Addons: no tool changes" in reply
    assert agent.config is config
    assert agent.mode == "plan"
    assert called == ["env", "prompt", "addons"]


def test_answer_and_steer_commands_become_harness_ops(monkeypatch):
    from core_harness import Answer, UserInput

    ops = []
    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda _workspace: None)
    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(tools=[], 
        session_id="session-test",
        harness=SimpleNamespace(model_id="test", submit=lambda op: ops.append(op) or False),
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO(
        '{"type":"answer","request_id":"q-1","value":"Deny"}\n'
        '{"type":"steer","prompt":"use metric units"}\n'
        '{"type":"steer","prompt":" "}\n'
    ))
    assert asyncio.run(stdio.serve(Path("."), None, None)) == 0
    assert ops == [Answer("q-1", "Deny"), UserInput("use metric units")]
    assert [frame["message"] for frame in frames if frame["type"] == "error"] == [
        "answer rejected: no question is waiting on that id", "steer requires an active run", "prompt is required",
    ]


@pytest.mark.parametrize("command", ["/plan", "/plans", "/mode", "/mode plan"])
def test_removed_plan_commands_are_unknown(command):
    from coding_agent.protocols.stdio import commands
    agent = SimpleNamespace(user_addons=SimpleNamespace(run_command=AsyncMock(return_value=None)))
    with pytest.raises(ValueError, match="Unknown command"):
        asyncio.run(commands.execute(agent, command))


def _serve(monkeypatch, agent, lines, workspace=Path("."), client="zeron"):
    agent.tools = vars(agent).get("tools", [])  # serve binds widget fields to the agent's tools
    frames = []
    seen = {}
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda _workspace: None)
    monkeypatch.setattr(stdio, "build_agent", lambda **kwargs: seen.update(kwargs) or agent)
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO("".join(json.dumps(line) + "\n" for line in lines)))
    assert asyncio.run(stdio.serve(workspace, None, None, client=client)) == 0
    return frames, seen


def test_ready_carries_workspace_branch_and_client(monkeypatch, tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "feature/web", str(tmp_path)], check=True)
    agent = SimpleNamespace(session_id="s-1", harness=SimpleNamespace(model_id="openai:gpt-test"))
    frames, seen = _serve(monkeypatch, agent, [], workspace=tmp_path, client="web")
    ready = frames[0]
    assert ready["type"] == "ready" and ready["model"] == "openai:gpt-test"
    assert ready["workspace"] == str(tmp_path) and ready["branch"] == "feature/web"
    assert ready["client"] == "web" and seen["client"] == "web"


def test_cli_client_flag_reaches_serve(monkeypatch):
    from coding_agent.protocols.stdio import server

    calls = []

    async def fake_serve(workspace, model, session_id, *, unattended=False, client="zeron"):
        calls.append((session_id, client))
        return 0

    monkeypatch.setattr(server, "serve", fake_serve)
    monkeypatch.setattr(server.sys, "stdout", server.sys.stdout)
    assert server.main(["--session-id", "abc", "--client", "web"]) == 0
    assert calls == [("abc", "web")]
    with pytest.raises(SystemExit):
        server.main(["--client", "tui"])


def _web_store(tmp_path):
    from coding_agent.addons.persistence import JsonlPersistence
    from core_ai.types import Message

    store = JsonlPersistence(tmp_path / "sessions")
    store.client = "web"
    asyncio.run(store.save_conversation(session_id="web-1", messages=[Message(role="user", content="Web task")]))
    asyncio.run(store.append_event(event_type="usage", payload={"session_id": "web-1", "cumulative_tokens": 42}))
    other = JsonlPersistence(tmp_path / "sessions")
    other.client = "zeron"
    asyncio.run(other.save_conversation(session_id="zeron-1", messages=[Message(role="user", content="Zeron chat")]))
    return store


def test_session_list_and_history_frames(monkeypatch, tmp_path):
    store = _web_store(tmp_path)
    agent = SimpleNamespace(session_id="live", persistence=store, harness=SimpleNamespace(model_id="m"))
    frames, _ = _serve(monkeypatch, agent, [
        {"type": "session/list", "request_id": "list-1"},
        {"type": "session/history", "request_id": "hist-1", "session_id": "web-1"},
        {"type": "session/history", "request_id": "hist-2", "session_id": "../escape"},
        {"type": "session/list"},
    ])
    listing = frames[1]
    assert listing["type"] == "sessions" and listing["request_id"] == "list-1"
    # Only this client's sessions; Zeron chats in the shared store stay hidden.
    assert [item["session_id"] for item in listing["sessions"]] == ["web-1"]
    assert listing["sessions"][0]["first_message"] == "Web task"
    assert listing["sessions"][0]["active"] is False
    history = frames[2]
    assert history["type"] == "session_history" and history["request_id"] == "hist-1"
    assert history["messages"][0]["content"] == "Web task"
    assert any(kind == "usage" and payload["cumulative_tokens"] == 42 for kind, payload in history["events"])
    assert history["children"] == []
    assert frames[3]["type"] == "error" and frames[3]["request_id"] == "hist-2"
    assert frames[4] == {"type": "error", "message": "session/list requires request_id"}


def test_model_command_switches_the_live_harness(monkeypatch, tmp_path):
    from coding_agent.protocols.stdio import requests

    class Registry:
        def namespaces(self):
            return ("openai",)

        def models(self):
            return [
                ModelInfo(id="gpt-a", provider="openai", api="responses", context_limit=128000),
                ModelInfo(id="gpt-b", provider="openai", api="responses", context_limit=64000),
            ]

    saved = []
    monkeypatch.setattr(requests, "ensure_spawn_settings", lambda workspace, **kwargs: saved.append(kwargs) or "cfg")
    learning = SimpleNamespace(model_id="openai:gpt-a")
    agent = SimpleNamespace(
        session_id="live", registry=Registry(), workspace=tmp_path, config=None, learning_loop=learning,
        harness=SimpleNamespace(model_id="openai:gpt-a"),
    )
    frames, _ = _serve(monkeypatch, agent, [
        {"type": "model", "request_id": "m-1", "model": "openai:gpt-b"},
        {"type": "model", "request_id": "m-2", "model": "openai:missing"},
    ])
    assert frames[1] == {"type": "model_selected", "request_id": "m-1", "model": "openai:gpt-b", "context_limit": 64000}
    assert agent.harness.model_id == learning.model_id == "openai:gpt-b"
    assert saved[0]["overrides"] == {"last_model": "openai:gpt-b"} and agent.config == "cfg"
    assert frames[2]["type"] == "error" and frames[2]["request_id"] == "m-2"


def test_overlapping_run_is_rejected(monkeypatch):
    started = asyncio.Event()

    async def slow_run(_content):
        started.set()
        await asyncio.sleep(0.2)

    agent = SimpleNamespace(
        session_id="live", harness=SimpleNamespace(model_id="m", submit=lambda op: False),
        user_addons=no_user_addons(), run=slow_run,
    )
    frames, _ = _serve(monkeypatch, agent, [
        {"type": "run", "prompt": "first"},
        {"type": "run", "prompt": "second"},
        {"type": "model", "request_id": "m-1", "model": "x"},
    ])
    errors = [frame for frame in frames if frame["type"] == "error"]
    assert errors[0]["message"] == "run rejected: a run is already active"
    assert "active run" in errors[1]["message"] and errors[1]["request_id"] == "m-1"


def test_tool_execution_started_frame_carries_started_at(monkeypatch):
    """Capture the real stdout bytes of a harness tool call through StdioSink."""
    import time
    from typing import Any

    from core_ai.types import Message, StreamEvent
    from core_harness import CoreHarness, HarnessConfig, Tool

    class Scripted:
        def __init__(self) -> None:
            self.calls = 0

        async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
            del model_id, messages, tools
            self.calls += 1
            if self.calls == 1:
                yield StreamEvent(type="toolcall_start", content_index=0, tool_call_id="call-1", tool_name="echo")
                yield StreamEvent(type="toolcall_delta", content_index=0, delta='{"text": "hi"}')
            else:
                yield StreamEvent(type="text_delta", delta="ok")
            yield StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2)
            yield StreamEvent(type="done")

    def echo(text: str = "") -> str:
        return f"echo:{text}"

    wire: list[str] = []

    class Stdout:
        def write(self, value: str) -> None:
            wire.append(value)

        def flush(self) -> None:
            pass

    monkeypatch.setattr(stdio.sys, "__stdout__", Stdout())
    harness = CoreHarness(
        registry=Scripted(),  # type: ignore[arg-type]
        model_id="fake:stdio",
        system_prompt="test",
        config=HarnessConfig(max_turns=3),
        tools=[Tool(echo)],
        sink=stdio.StdioSink(),
    )
    before = time.time()
    asyncio.run(harness.run("go"))
    frames = [json.loads(line) for line in "".join(wire).splitlines()]
    started = [f for f in frames if f.get("event") == "tool_execution_started"]
    assert len(started) == 1
    payload = started[0]["payload"]
    # Epoch seconds (a float), stamped by the harness tool loop.
    assert isinstance(payload["started_at"], float)
    assert before <= payload["started_at"] <= time.time()
    assert payload["call_id"] == "call-1"
