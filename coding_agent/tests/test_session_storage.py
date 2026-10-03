"""Directory storage, migration and image artifact regressions."""
import asyncio
import base64
import json
from pathlib import Path

import pytest
from core_ai.content import to_anthropic_blocks, to_openai_chat_content
from core_ai.types import Message
from core_harness import Checkpoint
from core_harness.context import COMPACTED_CONTEXT_MARK

from coding_agent.persistence import JsonlPersistence


def test_directory_layout_compactions_checkpoint_and_stable_replay(tmp_path: Path) -> None:
    async def run() -> None:
        store = JsonlPersistence(tmp_path)
        history = [Message(role="system", content="sys"), Message(role="user", content="task"),
                   *[Message(role="assistant", content=str(i)) for i in range(5)]]
        compacted = [history[0], Message(role="user", content=f"{COMPACTED_CONTEXT_MARK}\nsummary")]
        await store.save_conversation(session_id="s", messages=history)
        await store.save_conversation(session_id="s", messages=compacted)
        await store.save_checkpoint(checkpoint=Checkpoint(session_id="s", turn=2, messages=compacted,
                                                         status="completed", metadata={"goal": "test"}))
        directory = store.session_dir("s")
        before = (directory / "transcript.jsonl").read_bytes()
        restarted = JsonlPersistence(tmp_path)
        resumed = await restarted.load_conversation(session_id="s")
        for _ in range(3):
            await restarted.save_conversation(session_id="s", messages=resumed)
        assert (directory / "transcript.jsonl").read_bytes() == before
        assert json.loads((directory / "metadata.json").read_text())["version"] == 1
        assert json.loads((directory / "checkpoint.json").read_text())["metadata"]["goal"] == "test"
        compactions = await restarted.load_compactions("s")
        assert len(compactions) == 1
        assert json.loads((directory / "compactions" / f"{compactions[0]['seq']}.json").read_text()) == compactions[0]
        assert await restarted.load_transcript(session_id="s") == history
        assert (await restarted.load_checkpoint(session_id="s")).messages == resumed
    asyncio.run(run())


@pytest.mark.parametrize("session_id", [".", "..", "../other", "a/b", "a\\b", "/absolute", "a\n", ""])
def test_invalid_ids(tmp_path: Path, session_id: str) -> None:
    store = JsonlPersistence(tmp_path)
    with pytest.raises(ValueError):
        store.session_dir(session_id)
    with pytest.raises(ValueError):
        asyncio.run(store.load_conversation(session_id=session_id))


def test_legacy_migration_is_non_destructive_and_lists_both_formats(tmp_path: Path) -> None:
    flat = tmp_path / "legacy.jsonl"
    original = json.dumps({"type": "message", "role": "user", "content": "legacy", "seq": 1}) + "\n"
    flat.write_text(original)
    async def run() -> None:
        store = JsonlPersistence(tmp_path)
        await store.save_conversation(session_id="new", messages=[Message(role="user", content="new")])
        assert {s.session_id for s in await store.list_sessions()} == {"legacy", "new"}
        assert (await store.load_conversation(session_id="legacy"))[0].content == "legacy"
        assert flat.read_text() == original
        await store.save_conversation(session_id="legacy", messages=[Message(role="user", content="legacy"),
                                                                    Message(role="assistant", content="reply")])
        restarted = JsonlPersistence(tmp_path)
        assert len(await restarted.load_conversation(session_id="legacy")) == 2
        assert len(await restarted.list_sessions()) == 2
    asyncio.run(run())


def test_images_archived_deduplicated_and_hydrated_for_events_and_model(tmp_path: Path) -> None:
    raw = b"\x89PNG\r\n\x1a\nexample"
    encoded = base64.b64encode(raw).decode()
    original = tmp_path / "original.png"
    original.write_bytes(raw)
    parts = [
        {"type": "image", "media_type": "image/png", "url": original.as_uri(), "filename": "original.png"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": encoded}},
        {"inlineData": {"mimeType": "image/png", "data": encoded}},
    ]
    async def run() -> None:
        store = JsonlPersistence(tmp_path / "sessions")
        await store.save_conversation(session_id="images", messages=[Message(role="user", content=parts)])
        await store.append_event(event_type="tool_execution_completed", payload={
            "session_id": "images", "run_id": "r", "seq": 2, "result": {"content": parts}})
        original.unlink()
        directory = store.session_dir("images")
        assert len(list((directory / "images").iterdir())) == 1
        disk = (directory / "transcript.jsonl").read_text()
        assert encoded not in disk
        assert "archive_path" in disk
        restarted = JsonlPersistence(store.root)
        loaded = await restarted.load_conversation(session_id="images")
        for part in loaded[0].content:
            assert part["data"] == encoded
            assert Path(part["url"].removeprefix("file://")).read_bytes() == raw
        assert len(to_anthropic_blocks(loaded[0].content)) == 4
        assert len(to_openai_chat_content(loaded[0].content)) == 4
        events = await restarted.load_events(session_id="images")
        assert events[0][1]["result"]["content"][0]["data"] == encoded
        before = (directory / "transcript.jsonl").read_bytes()
        await restarted.save_conversation(session_id="images", messages=loaded)
        assert (directory / "transcript.jsonl").read_bytes() == before
    asyncio.run(run())


def test_session_symlink_rejected(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        JsonlPersistence(root).session_dir("escape")
