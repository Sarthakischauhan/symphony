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


def test_protocol_catalog_includes_dynamic_argument_choices(monkeypatch, tmp_path):
    from coding_agent.protocols import commands
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
    assert {item["value"] for item in catalog["mode"]["options"]} == {"build", "plan"}
    assert catalog["plans"]["options"][0]["value"] == ".symphony/plans/test_plan.md"


def test_personality_command_accepts_whitespace_and_applies_prompt(monkeypatch, tmp_path):
    from coding_agent.protocols import commands
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
    monkeypatch.setattr(stdio, "build_agent", lambda **kwargs: SimpleNamespace(
        session_id="session-test", harness=SimpleNamespace(model_id="test"),
        run=lambda *args: (_ for _ in ()).throw(AssertionError("model called")),
    ))
    monkeypatch.setattr(stdio.sys, "stdin", io.StringIO(
        '{"type":"run","prompt":"/personality ","attachments":["image.png"]}\n'
    ))
    asyncio.run(stdio.serve(Path("."), None, None))
    assert any(frame.get("type") == "error" and "attachments" in frame["message"] for frame in frames)
    assert any(frame.get("type") == "done" and frame["status"] == "errored" for frame in frames)


def test_reload_refreshes_live_agent_configuration(monkeypatch, tmp_path):
    from coding_agent.protocols import commands
    import coding_agent.credentials as credentials
    called = []
    monkeypatch.setattr(credentials, "load_provider_env", lambda workspace, **kwargs: called.append("env"))
    config = SimpleNamespace(personality="warm")
    monkeypatch.setattr(commands, "ensure_spawn_settings", lambda workspace: config)
    agent = SimpleNamespace(workspace=tmp_path, config=None, mode="plan",
                            apply_system_prompt=lambda: called.append("prompt"))
    assert "Reloaded" in asyncio.run(commands.execute(agent, "/reload"))
    assert agent.config is config
    assert agent.mode == "plan"
    assert called == ["env", "prompt"]
