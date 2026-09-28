"""The stdio transport preserves approval questions and event frames."""

import asyncio
import json

from coding_agent.run import stdio


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
