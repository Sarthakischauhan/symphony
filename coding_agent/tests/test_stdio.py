"""The stdio transport preserves approval questions and event frames."""

import asyncio
import json

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


def test_model_catalog_includes_provider_and_context(monkeypatch):
    import core_ai

    class Registry:
        def namespaces(self):
            return ("openai",)

        def models(self):
            return [ModelInfo(id="gpt-test", provider="openai", api="responses", context_limit=128000)]

    frames = []
    monkeypatch.setattr(stdio, "write_frame", frames.append)
    monkeypatch.setattr(stdio, "load_provider_env", lambda _workspace: None)
    monkeypatch.setattr(core_ai, "build_default_registry", Registry)
    monkeypatch.setattr(core_ai, "default_model_id", lambda _registry: "openai:gpt-test")
    assert stdio.main(["--models"]) == 0
    assert frames[0]["models"] == [{
        "id": "openai:gpt-test", "label": "gpt-test", "provider": "openai",
        "description": "openai", "context_limit": 128000, "reasoning_levels": [],
    }]
