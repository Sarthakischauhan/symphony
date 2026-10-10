"""Active sessions stay out of the resume picker until their process exits."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from coding_agent.addons.persistence.active import (
    active_session_ids,
    list_active,
    register_active,
    release_active,
)
from coding_agent.tui.screens.resume import load_session_options


def test_register_and_release_round_trip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("coding_agent.addons.persistence.active.active_dir", lambda: tmp_path)
    record = register_active("session-1", workspace="/work", kind="tui", model_id="openai:test", pid=os.getpid())

    assert record.session_id == "session-1"
    assert (tmp_path / f"{os.getpid()}.json").is_file()
    assert active_session_ids() == {"session-1"}

    release_active()
    assert active_session_ids() == set()
    assert not (tmp_path / f"{os.getpid()}.json").exists()


def test_dead_process_is_pruned(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("coding_agent.addons.persistence.active.active_dir", lambda: tmp_path)
    register_active("gone", workspace="/work", kind="run", pid=999_999_999)
    monkeypatch.setattr("coding_agent.resources.usage.process_alive", lambda pid: False)

    assert list_active() == []
    assert not (tmp_path / "999999999.json").exists()


def test_resume_hides_active_sessions(monkeypatch) -> None:
    class Persistence:
        async def list_sessions(self):
            return [
                _session("open-1", "still running"),
                _session("closed-1", "finished work"),
            ]

    monkeypatch.setattr(
        "coding_agent.tui.screens.resume.active_session_ids",
        lambda: {"open-1"},
    )
    options = asyncio.run(load_session_options(Persistence()))
    assert [option.session_id for option in options] == ["closed-1"]

    everything = asyncio.run(load_session_options(Persistence(), closed_only=False))
    assert [option.session_id for option in everything] == ["open-1", "closed-1"]


def test_tui_sessions_move_out_of_the_shared_directory(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    shared = home / ".symphony" / "sessions"
    monkeypatch.setattr(Path, "home", lambda: home)
    from coding_agent.addons.persistence.jsonl import sessions_dir

    tagged = shared / "tui-chat"
    tagged.mkdir(parents=True)
    (tagged / "metadata.json").write_text(json.dumps({"version": 1, "client": "tui"}))
    (tagged / "transcript.jsonl").write_text("{}\n")
    foreign = shared / "zeron-chat"
    foreign.mkdir()
    (foreign / "metadata.json").write_text(json.dumps({"version": 1, "client": "zeron"}))
    plain = shared / "old-chat"
    plain.mkdir()
    (plain / "metadata.json").write_text(json.dumps({"version": 1}))

    target = sessions_dir(client="tui")

    assert target == home / ".symphony" / "tui" / "sessions"
    assert (target / "tui-chat" / "transcript.jsonl").is_file()
    assert not (shared / "tui-chat").exists()
    assert (shared / "zeron-chat").is_dir()
    assert (shared / "old-chat").is_dir()


class _session:  # noqa: N801 - tiny stand-in for SessionSummary
    def __init__(self, session_id: str, first_message: str, client: str = "") -> None:
        self.session_id = session_id
        self.updated_at = "2026-08-12T16:00:00+00:00"
        self.message_count = 2
        self.first_message = first_message
        self.client = client
