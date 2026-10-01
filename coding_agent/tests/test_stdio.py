"""The stdio transport preserves approval questions and event frames."""

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

from core_ai import ModelInfo
from coding_agent.protocols import stdio


def test_interactive_input_is_correlated(monkeypatch):
    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    sink = stdio.StdioSink()

    async def scenario():
        pending = asyncio.create_task(sink.request_user_input(
            question="Allow bash?", choices=["Allow once", "Deny"], kind="approval",
        ))
        await asyncio.sleep(0)
        frame = frames.pop()
        assert frame["type"] == "input_requested"
        assert frame["kind"] == "approval"
        sink.pending[frame["request_id"]].set_result("Deny")
        assert await pending == "Deny"
        assert not sink.pending
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
    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(
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
    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(
        session_id="session-test", harness=SimpleNamespace(model_id="openai:gpt-test"),
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
    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(
        session_id="session-test", harness=SimpleNamespace(model_id="openai:gpt-test"),
        run=lambda *_args: (_ for _ in ()).throw(AssertionError("model was called")),
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO(
        '{"type":"run","prompt":"/help"}\n'
    ))
    assert asyncio.run(stdio.serve(Path("."), None, None)) == 0
    assert any(frame.get("event") == "text_delta" and "/model" in frame["payload"]["delta"] for frame in frames)


def test_mode_command_survives_a_new_stdio_process(monkeypatch, tmp_path):
    from coding_agent.protocols import commands

    monkeypatch.setattr(commands, "symphony_dir", lambda: tmp_path)

    class Agent:
        session_id = "0876c78a-9f47-4bd5-a495-a8e912c3757c"
        mode = "build"
        harness = SimpleNamespace(reasoning_effort=None)

        def set_mode(self, mode):
            self.mode = mode

    first = Agent()
    assert asyncio.run(commands.execute(first, "/mode plan")) == "Switched to plan mode."
    second = Agent()
    commands.load_state(second)
    assert second.mode == "plan"


def test_context_usage_payload_uses_sent_tokens_not_a_missing_window():
    assert stdio.context_usage_payload(SimpleNamespace(sent_tokens=20, context_limit=100)) == {
        "tokens": 20, "window": 100,
    }
    assert stdio.context_usage_payload(SimpleNamespace(sent_tokens=0, context_limit=None)) == {
        "tokens": 0,
    }
    assert stdio.context_usage_payload(SimpleNamespace(sent_tokens=4, context_limit=0)) == {
        "tokens": 4,
    }
    assert stdio.context_usage_payload(SimpleNamespace(sent_tokens=-1, context_limit=10)) is None
    assert stdio.context_usage_payload(SimpleNamespace(sent_tokens=True, context_limit=10)) is None
    assert stdio.command_changes_prompt("/compact")
    assert stdio.command_changes_prompt("/personality precise")
    assert stdio.command_changes_prompt("/reload")
    assert not stdio.command_changes_prompt("/help")
    assert not stdio.command_changes_prompt("hello")


def test_model_turn_emits_context_usage(monkeypatch):
    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda _workspace: None)

    async def run(_content):
        return None

    async def context_report():
        return SimpleNamespace(sent_tokens=1500, context_limit=32000)

    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(
        session_id="session-test",
        harness=SimpleNamespace(model_id="openai:gpt-test"),
        run=run,
        context_report=context_report,
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO('{"type":"run","prompt":"hello"}\n'))
    assert asyncio.run(stdio.serve(Path("."), None, None)) == 0
    usage = [frame for frame in frames if frame.get("event") == "context_usage"]
    assert usage == [{
        "type": "event", "event": "context_usage",
        "payload": {"tokens": 1500, "window": 32000},
    }]
    assert frames[-1] == {"type": "done", "status": "completed"}


def test_unusable_context_report_emits_nothing(monkeypatch):
    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda _workspace: None)

    async def run(_content):
        return None

    async def context_report():
        raise RuntimeError("not ready")

    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(
        session_id="session-test",
        harness=SimpleNamespace(model_id="openai:gpt-test"),
        run=run,
        context_report=context_report,
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO('{"type":"run","prompt":"hello"}\n'))
    assert asyncio.run(stdio.serve(Path("."), None, None)) == 0
    assert not any(frame.get("event") == "context_usage" for frame in frames)
    assert frames[-1] == {"type": "done", "status": "completed"}


def test_prompt_changing_commands_emit_context_usage(monkeypatch):
    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda _workspace: None)

    async def execute(_agent, task):
        return f"ran {task}"

    async def context_report():
        return SimpleNamespace(sent_tokens=40, context_limit=80)

    monkeypatch.setattr(stdio, "execute_command", execute)
    monkeypatch.setattr(stdio, "build_agent", lambda **_kwargs: SimpleNamespace(
        session_id="session-test",
        harness=SimpleNamespace(model_id="openai:gpt-test"),
        context_report=context_report,
        run=lambda *_args: (_ for _ in ()).throw(AssertionError("model was called")),
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO(
        '{"type":"run","prompt":"/status"}\n'
    ))
    assert asyncio.run(stdio.serve(Path("."), None, None)) == 0
    assert not any(frame.get("event") == "context_usage" for frame in frames)
    frames.clear()
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO(
        '{"type":"run","prompt":"/personality precise"}\n'
    ))
    assert asyncio.run(stdio.serve(Path("."), None, None)) == 0
    usage = [frame for frame in frames if frame.get("event") == "context_usage"]
    assert usage == [{
        "type": "event", "event": "context_usage",
        "payload": {"tokens": 40, "window": 80},
    }]


def test_persisted_model_turns_each_emit_context_usage(monkeypatch):
    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)

    class Harness:
        async def _persist_state(self, **_kwargs):
            return "saved"

    async def context_report():
        return SimpleNamespace(sent_tokens=9, context_limit=None)

    agent = SimpleNamespace(harness=Harness(), context_report=context_report)
    assert stdio.report_context_after_turns(agent)

    async def scenario():
        await agent.harness._persist_state(turn=0)
        await agent.harness._persist_state(turn=1)

    asyncio.run(scenario())
    assert frames == [
        {"type": "event", "event": "context_usage", "payload": {"tokens": 9}},
        {"type": "event", "event": "context_usage", "payload": {"tokens": 9}},
    ]
