"""Session product tags survive restart and cannot bypass bundle validation."""
import asyncio
import json

import pytest
from core_ai.types import Message

from coding_agent.addons.persistence import JsonlPersistence


def test_session_client_is_preserved_across_products(tmp_path):
    async def run():
        store = JsonlPersistence(tmp_path)
        store.client = "zeron"
        messages = [Message(role="user", content="a Zeron question")]
        await store.save_conversation(session_id="chat", messages=messages)
        tui = JsonlPersistence(tmp_path)
        tui.client = "tui"
        await tui.save_conversation(session_id="chat", messages=messages)
        sessions = await tui.list_sessions()
        assert sessions[0].client == "zeron"
    asyncio.run(run())


def test_stamping_client_does_not_repair_invalid_bundle(tmp_path):
    store = JsonlPersistence(tmp_path)
    store.client = "tui"
    directory = store.session_dir("broken")
    directory.mkdir()
    metadata = {"version": 99, "session_id": "broken"}
    (directory / "metadata.json").write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="unsupported session bundle version"):
        asyncio.run(store.save_conversation(session_id="broken", messages=[]))
    assert json.loads((directory / "metadata.json").read_text()) == metadata
