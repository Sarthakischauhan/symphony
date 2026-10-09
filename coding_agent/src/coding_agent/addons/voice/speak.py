"""Speak the model's own text as it streams, not a canned line at the end.

One websocket to ``wss://api.x.ai/v1/tts`` stays open for the voice turn.
Completed sentences are sent as they arrive, and the MP3 frames that come back
are handed to the player immediately. Waiting for ``after_run`` and then
building one file is what made the reply feel late.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import shutil
import subprocess
import sys
import threading
from typing import Callable
from urllib.parse import urlencode

from coding_agent.tui.composer.voice import GROK_TTS_VOICE, grok_voice_credentials

TTS_URL = "wss://api.x.ai/v1/tts"
SpeakListener = Callable[[bool], None]


class StreamingSpeaker:
    """Background TTS socket. ``feed`` takes model text; ``finish`` ends it."""

    def __init__(self, *, on_speaking: SpeakListener | None = None) -> None:
        self._on_speaking = on_speaking
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="grok-tts", daemon=True)
        # call_soon_threadsafe queues callbacks even before run_until_complete starts.
        # One sender preserves delta/done ordering while the connection is pending.
        self._commands: asyncio.Queue[str | None] = asyncio.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._finished = False
        self._sent = ""
        self._pending = ""
        self._error = ""
        self._thread.start()

    def feed(self, text: str, *, force: bool = False) -> None:
        """Queue newly speakable text. ``force`` sends the current clause now."""
        with self._lock:
            if self._closed or self._finished or not text:
                return
            self._feed(text, force=force)

    def _feed(self, text: str, *, force: bool = False) -> None:
        fresh = text[len(self._sent):] if text.startswith(self._sent) else text
        self._pending += fresh
        self._sent = text
        speakable, rest = _split_ready(self._pending)
        if force and not speakable and self._pending.strip():
            speakable, rest = self._pending.strip(), ""
        self._pending = rest
        if speakable:
            self._submit(speakable)

    def finish(self, text: str = "") -> None:
        """Speak whatever remains, then close the socket after playback."""
        with self._lock:
            if self._closed or self._finished:
                return
            if text:
                self._feed(text)
            if self._pending.strip():
                self._submit(self._pending.strip())
                self._pending = ""
            self._finished = True
            self._submit(None)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._cancel)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)

    def _submit(self, text: str | None) -> None:
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(self._commands.put_nowait, text)

    def _cancel(self) -> None:
        task = getattr(self, "_task", None)
        if task is not None:
            task.cancel()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._task = self._loop.create_task(self._session())
            if self._closed:
                self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                self._loop.run_until_complete(self._task)
        finally:
            self._loop.close()

    async def _session(self) -> None:
        socket = None
        player = None
        tasks: list[asyncio.Task[None]] = []
        try:
            import websockets

            token, headers = grok_voice_credentials()
            query = urlencode({
                "voice": GROK_TTS_VOICE,
                "language": "en",
                "codec": "mp3",
                "optimize_streaming_latency": 1,
            })
            socket = await websockets.connect(
                f"{TTS_URL}?{query}",
                additional_headers={"Authorization": f"Bearer {token}", **headers},
                max_size=8 * 1024 * 1024,
            )
            player = self._player = _Mp3Stream(on_speaking=self._mark)
            tasks = [asyncio.create_task(self._listen(socket)), asyncio.create_task(self._send(socket))]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except ImportError:
            self._error = "Voice playback needs the websockets package."
        except Exception as exc:
            self._error = f"Voice playback failed · {exc}"
        finally:
            for task in tasks:
                task.cancel()
            if player is not None:
                with contextlib.suppress(Exception):
                    player.close()
            await asyncio.gather(*tasks, return_exceptions=True)
            if socket is not None:
                with contextlib.suppress(Exception):
                    await socket.close()
            with self._lock:
                self._closed = True
            # Startup failures and empty audio still need to release the voice UI.
            self._mark(False)

    async def _send(self, socket: object) -> None:
        while True:
            text = await self._commands.get()
            event = {"type": "text.done"} if text is None else {"type": "text.delta", "delta": text + " "}
            await socket.send(json.dumps(event))  # type: ignore[attr-defined]

    async def _listen(self, socket: object) -> None:
        player: _Mp3Stream = self._player
        async for raw in socket:  # type: ignore[attr-defined]
            if isinstance(raw, bytes):
                player.write(raw)
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = str(event.get("type") or "")
            if kind == "audio.delta":
                payload = event.get("delta") or event.get("audio") or ""
                if isinstance(payload, str) and payload:
                    player.write(base64.b64decode(payload))
            elif kind == "audio.done":
                break
            elif kind == "error":
                self._error = str(event.get("message") or "voice playback failed")
                return
        # Draining playback may block; keep the socket loop responsive to close().
        await asyncio.to_thread(player.finish)

    def _mark(self, speaking: bool) -> None:
        if self._on_speaking is not None:
            self._on_speaking(speaking)


def _split_ready(pending: str) -> tuple[str, str]:
    """Return text that ends on a sentence boundary, and the unfinished tail.

    The boundary is the punctuation itself. Waiting for the space after it held
    the whole sentence until the next word arrived.
    """
    cut = max(pending.rfind("."), pending.rfind("?"), pending.rfind("!"), pending.rfind("\n"))
    if cut < 0:
        return "", pending
    return pending[: cut + 1].strip(), pending[cut + 1:]


class _Mp3Stream:
    """Play MP3 bytes as they arrive. ffmpeg reads the stream; afplay cannot."""

    def __init__(self, *, on_speaking: SpeakListener) -> None:
        self._on_speaking = on_speaking
        self._process: subprocess.Popen[bytes] | None = None
        self._buffer = bytearray()

    def write(self, mp3: bytes) -> None:
        if not mp3:
            return
        if self._process is None:
            command = _mp3_stream_command()
            if command is None:
                self._buffer.extend(mp3)
                return
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._on_speaking(True)
        assert self._process.stdin is not None
        try:
            self._process.stdin.write(mp3)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            self.finish()

    def finish(self) -> None:
        process = self._process
        if process is None:
            if self._buffer:
                from coding_agent.tui.composer.voice import play_mp3

                audio = bytes(self._buffer)
                self._buffer.clear()
                self._on_speaking(True)
                try:
                    play_mp3(audio)
                finally:
                    self._on_speaking(False)
            return
        try:
            if process.stdin is not None:
                with contextlib.suppress(OSError):
                    process.stdin.close()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        finally:
            if self._process is process:
                self._process = None
            self._on_speaking(False)

    def close(self) -> None:
        process = self._process
        self._process = None
        self._buffer.clear()
        try:
            if process is not None:
                with contextlib.suppress(OSError):
                    process.kill()
                if process.stdin is not None:
                    with contextlib.suppress(OSError):
                        process.stdin.close()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=1)
        finally:
            self._on_speaking(False)


def _mp3_stream_command() -> list[str] | None:
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-"]
    if shutil.which("mpv"):
        return ["mpv", "--no-video", "--really-quiet", "-"]
    if sys.platform != "darwin":
        return None
    return None
