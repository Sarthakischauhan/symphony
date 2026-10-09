"""Speaker regressions: no provider calls or real audio players."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from coding_agent.addons.voice import speak


class Socket:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.closed = False
        self.incoming: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, raw: str) -> None:
        event = json.loads(raw)
        self.events.append(event)
        if event["type"] == "text.done":
            self.incoming.put_nowait('{"type":"audio.done"}')

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed = True


def install_socket(monkeypatch, connect):
    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=connect))
    monkeypatch.setattr(speak, "grok_voice_credentials", lambda: ("fake", {}))
    player = Mock()
    monkeypatch.setattr(speak, "_Mp3Stream", lambda **kwargs: player)
    return player


def test_feed_and_finish_before_loop_starts(monkeypatch):
    gate = threading.Event()
    original_run = speak.StreamingSpeaker._run

    def delayed_run(self):
        assert gate.wait(2)
        original_run(self)

    monkeypatch.setattr(speak.StreamingSpeaker, "_run", delayed_run)
    socket = Socket()

    async def connect(*args, **kwargs):
        return socket

    player = install_socket(monkeypatch, connect)
    speaker = speak.StreamingSpeaker()
    try:
        speaker.feed("First.")
        speaker.feed("First. Tail")
        speaker.finish("First. Tail")
        speaker.finish()
        speaker.feed("ignored.")
        gate.set()
        speaker._thread.join(2)
        assert not speaker._thread.is_alive()
        assert socket.events == [
            {"type": "text.delta", "delta": "First. "},
            {"type": "text.delta", "delta": "Tail "},
            {"type": "text.done"},
        ]
        player.finish.assert_called_once()
        player.close.assert_called_once()
        assert socket.closed
    finally:
        gate.set()
        speaker.close()


def test_pending_connection_does_not_block_loop_or_lose_done(monkeypatch):
    connecting = threading.Event()
    release = threading.Event()
    socket = Socket()

    async def connect(*args, **kwargs):
        connecting.set()
        while not release.is_set():
            await asyncio.sleep(0.001)
        return socket

    install_socket(monkeypatch, connect)
    speaker = speak.StreamingSpeaker()
    try:
        assert connecting.wait(2)
        speaker.feed("Hello.")
        speaker.finish("Hello. Goodbye")
        heartbeat = threading.Event()
        speaker._loop.call_soon_threadsafe(heartbeat.set)
        assert heartbeat.wait(1), "sending text blocked connection's event loop"
        release.set()
        speaker._thread.join(2)
        assert [e["type"] for e in socket.events] == ["text.delta", "text.delta", "text.done"]
        assert socket.events[1]["delta"] == "Goodbye "
        assert not speaker._thread.is_alive()
    finally:
        release.set()
        speaker.close()


def test_close_cancels_pending_connection(monkeypatch):
    connecting = threading.Event()
    cancelled = threading.Event()

    async def connect(*args, **kwargs):
        connecting.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    install_socket(monkeypatch, connect)
    speaker = speak.StreamingSpeaker()
    assert connecting.wait(2)
    speaker.close()
    speaker.close()
    speaker.feed("too late.")
    speaker.finish()
    assert cancelled.is_set()
    assert not speaker._thread.is_alive()
    assert speaker._loop.is_closed()


def test_receive_failure_cleans_up_socket_and_player(monkeypatch):
    class BrokenSocket(Socket):
        async def __anext__(self):
            raise OSError("disconnected")

    socket = BrokenSocket()

    async def connect(*args, **kwargs):
        return socket

    player = install_socket(monkeypatch, connect)
    speaker = speak.StreamingSpeaker()
    speaker._thread.join(2)
    assert not speaker._thread.is_alive()
    assert "disconnected" in speaker._error
    assert socket.closed
    player.close.assert_called_once()


def test_player_finish_timeout_kills_and_reaps():
    marks = []
    player = speak._Mp3Stream(on_speaking=marks.append)
    process = Mock()
    process.wait.side_effect = [subprocess.TimeoutExpired("player", 30), 0]
    player._process = process
    player.finish()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2
    process.stdin.close.assert_called_once()
    assert player._process is None
    assert marks == [False]


def test_player_close_discards_buffer_and_reaps():
    player = speak._Mp3Stream(on_speaking=Mock())
    process = Mock()
    player._process = process
    player._buffer.extend(b"audio")
    player.close()
    process.kill.assert_called_once()
    process.wait.assert_called_once_with(timeout=1)
    process.stdin.close.assert_called_once()
    assert not player._buffer
    assert player._process is None


def test_fallback_failure_resets_speaking(monkeypatch):
    marks = []
    player = speak._Mp3Stream(on_speaking=marks.append)
    player._buffer.extend(b"mp3")
    monkeypatch.setattr("coding_agent.tui.composer.voice.play_mp3", Mock(side_effect=OSError("no audio")))
    with pytest.raises(OSError, match="no audio"):
        player.finish()
    assert marks == [True, False]
    assert not player._buffer


def test_close_connected_session_cleans_up(monkeypatch):
    socket = Socket()
    listening = threading.Event()

    class WaitingSocket(Socket):
        async def __anext__(self):
            listening.set()
            return await super().__anext__()

    socket = WaitingSocket()

    async def connect(*args, **kwargs):
        return socket

    player = install_socket(monkeypatch, connect)
    speaker = speak.StreamingSpeaker()
    assert listening.wait(2)
    speaker.close()
    assert not speaker._thread.is_alive()
    assert socket.closed
    player.close.assert_called_once()
    player.finish.assert_not_called()


def test_connection_failure_closes_loop(monkeypatch):
    async def connect(*args, **kwargs):
        await asyncio.sleep(0)
        raise OSError("offline")

    player = install_socket(monkeypatch, connect)
    speaker = speak.StreamingSpeaker()
    speaker.feed("queued.")
    speaker.finish()
    speaker._thread.join(2)
    speaker.close()
    assert not speaker._thread.is_alive()
    assert speaker._loop.is_closed()
    assert "offline" in speaker._error
    player.close.assert_not_called()
