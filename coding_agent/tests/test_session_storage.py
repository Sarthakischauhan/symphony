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
        {"type": "image", "media_type": "image/png", "url": original.as_uri(), "filename": "original.png",
         "user_attached": True, "attached_path": str(original)},
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


def _lock_worker(root: str, started, acquired) -> None:
    started.set()
    store = JsonlPersistence(root)
    store._acquire_session("s")
    acquired.set()
    store._release_session("s")


def test_cross_process_lock_blocks_until_release(tmp_path: Path) -> None:
    import multiprocessing
    import time

    started = multiprocessing.Event()
    acquired = multiprocessing.Event()
    store = JsonlPersistence(tmp_path)
    store._acquire_session("s")
    process = multiprocessing.Process(target=_lock_worker, args=(str(tmp_path), started, acquired))
    process.start()
    try:
        assert started.wait(2)
        time.sleep(0.3)
        assert not acquired.is_set()
    finally:
        store._release_session("s")
    assert acquired.wait(2)
    process.join(3)
    assert process.exitcode == 0


def test_existing_transcript_is_not_replaced_by_older_flat_file(tmp_path: Path) -> None:
    import os

    legacy = tmp_path / "s.jsonl"
    user = {"type": "message", "role": "user", "content": "old", "seq": 1}
    extra = {"type": "message", "role": "assistant", "content": "kept", "seq": 2}
    legacy.write_text(json.dumps(user) + "\n", encoding="utf-8")
    directory = tmp_path / "s"
    directory.mkdir()
    transcript = directory / "transcript.jsonl"
    transcript.write_text(json.dumps(user) + "\n" + json.dumps(extra) + "\n", encoding="utf-8")
    (directory / "metadata.json").write_text(
        json.dumps({"version": 1, "session_id": "s"}) + "\n", encoding="utf-8"
    )
    os.utime(legacy, (1, 1))
    os.utime(transcript, (10, 10))

    async def run() -> None:
        messages = await JsonlPersistence(tmp_path).load_conversation(session_id="s")
        assert [message.content for message in messages] == ["old", "kept"]
        assert transcript.read_text(encoding="utf-8").count("kept") == 1

    asyncio.run(run())


def test_newer_flat_jsonl_appends_are_folded(tmp_path: Path) -> None:
    legacy = tmp_path / "s.jsonl"
    legacy.write_text(
        json.dumps({"type": "message", "role": "user", "content": "old", "seq": 1}) + "\n",
        encoding="utf-8",
    )

    async def run() -> None:
        assert (await JsonlPersistence(tmp_path).load_conversation(session_id="s"))[0].content == "old"
        with legacy.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"type": "message", "role": "assistant", "content": "from-old", "seq": 2}
            ) + "\n")
        messages = await JsonlPersistence(tmp_path).load_conversation(session_id="s")
        assert [message.content for message in messages] == ["old", "from-old"]

    asyncio.run(run())


def test_bundle_version_must_be_one(tmp_path: Path) -> None:
    async def run() -> None:
        store = JsonlPersistence(tmp_path)
        await store.save_conversation(session_id="s", messages=[Message(role="user", content="hi")])
        meta_path = store.session_dir("s") / "metadata.json"
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        payload["version"] = 2
        meta_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        fresh = JsonlPersistence(tmp_path)
        with pytest.raises(ValueError, match="version"):
            await fresh.load_conversation(session_id="s")
        payload.pop("version")
        meta_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="version"):
            await fresh.load_conversation(session_id="s")
        meta_path.unlink()
        with pytest.raises(ValueError, match="version"):
            await fresh.load_conversation(session_id="s")

    asyncio.run(run())


def test_skipped_legacy_lines_are_quarantined_without_job_pids(tmp_path: Path) -> None:
    import hashlib
    import os
    import subprocess

    from coding_agent.run.interrupted import stop_orphaned_jobs

    orphan = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        raw = (
            json.dumps({"type": "message", "role": "user", "content": "keep", "seq": 1}) + "\n"
            "{not-json\n"
            + json.dumps({
                "type": "checkpoint", "seq": 2, "session_id": "bad", "turn": 1, "status": "running",
                "metadata": {"background_jobs": {"job": orphan.pid}},
            }) + "\n"
        ).encode()
        (tmp_path / "bad.jsonl").write_bytes(raw)

        async def run() -> None:
            store = JsonlPersistence(tmp_path)
            loaded = await store.load_checkpoint(session_id="bad")
            assert loaded is not None
            assert "background_jobs" not in loaded.metadata
            assert stop_orphaned_jobs(loaded.metadata.get("background_jobs")) == []
            digest = hashlib.sha256(raw).hexdigest()
            meta = json.loads((store.session_dir("bad") / "metadata.json").read_text(encoding="utf-8"))
            assert meta["quarantine"]["sha256"] == digest
            assert (store.session_dir("bad") / "quarantine" / f"{digest}.jsonl").read_bytes() == raw
            assert (await store.load_conversation(session_id="bad"))[0].content == "keep"

        asyncio.run(run())
        os.kill(orphan.pid, 0)
    finally:
        orphan.kill()


def test_session_id_with_jsonl_suffix_lists(tmp_path: Path) -> None:
    async def run() -> None:
        store = JsonlPersistence(tmp_path)
        await store.save_conversation(session_id="foo.jsonl", messages=[Message(role="user", content="x")])
        assert [item.session_id for item in await store.list_sessions()] == ["foo.jsonl"]

    asyncio.run(run())


def test_images_reject_unattached_paths_mismatch_and_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import coding_agent.persistence.images as images

    monkeypatch.setattr(images, "MAX_IMAGE_BYTES", 16)
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"secret-image-bytes")
    huge = tmp_path / "huge.png"
    huge.write_bytes(b"0123456789abcdef-too-big")
    small = b"tiny-png-bytes!"
    assert len(small) <= 16

    async def run() -> None:
        store = JsonlPersistence(tmp_path / "sessions")
        await store.save_conversation(session_id="img", messages=[Message(role="user", content=[
            {"type": "text", "text": "see"},
            {"type": "image", "media_type": "image/png", "url": secret.as_uri()},
            {"type": "image", "media_type": "image/png", "user_attached": True, "attached_path": str(huge)},
            {"type": "image", "media_type": "image/png", "data": base64.b64encode(small).decode()},
        ])])
        directory = store.session_dir("img")
        blob = next((directory / "images").iterdir())
        transcript = (directory / "transcript.jsonl").read_text(encoding="utf-8")
        assert b"secret-image-bytes" not in transcript.encode()
        assert blob.read_bytes() == small
        await store.append_event(event_type="tool_execution_completed", payload={
            "session_id": "img", "run_id": "r", "seq": 2,
            "result": {"content": [{"type": "image", "archive_path": f"images/{blob.name}"}]},
        })
        blob.write_bytes(b"not-the-image!")
        reloaded = await JsonlPersistence(store.root).load_conversation(session_id="img")
        assert reloaded[0].content[0]["text"] == "see"
        archived = [part for part in reloaded[0].content if part.get("archive_path")]
        assert archived and archived[0].get("unavailable") == "mismatch"
        assert "data" not in archived[0]
        blob.unlink()
        missing = await JsonlPersistence(store.root).load_conversation(session_id="img")
        assert missing[0].content[0]["text"] == "see"
        assert missing[0].content[-1]["unavailable"] == "missing"
        events = await JsonlPersistence(store.root).load_events(session_id="img")
        assert events[0][1]["result"]["content"][0]["unavailable"] == "missing"
        checkpoint = await JsonlPersistence(store.root).load_checkpoint(session_id="img")
        assert checkpoint is None or checkpoint.messages[0].content[0]["text"] == "see"

    asyncio.run(run())
