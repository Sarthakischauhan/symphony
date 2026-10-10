"""One background speech-to-speech socket for the life of a voice session.

The socket is ``wss://api.x.ai/v1/realtime`` with ``grok-voice-think-fast-2.0``,
the cheapest current Grok voice model. Mic audio goes in as PCM. Spoken audio
comes back as PCM and is played on the default output. ``close`` runs when the
app quits.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import shutil
import subprocess
import sys
import threading
from typing import Any, Callable
from urllib.parse import urlencode

from coding_agent.tui.composer.voice import GROK_TTS_VOICE, grok_voice_credentials

VOICE_REALTIME_MODEL = "grok-voice-think-fast-2.0"
REALTIME_URL = "wss://api.x.ai/v1/realtime"
SAMPLE_RATE = 24_000
# 40 ms of mono int16 per callback and per socket message: 25 sends a second.
MIC_BLOCK_FRAMES = SAMPLE_RATE * 40 // 1000
# Mic blocks waiting for the socket. Past this the oldest is dropped, so a
# slow link costs at most ~1.3 s of latency instead of growing without bound.
MIC_QUEUE_BLOCKS = 32
# The audio is base64 and needs no escaping, so the JSON is two fixed halves.
_APPEND_HEAD = '{"type": "input_audio_buffer.append", "audio": "'
_APPEND_TAIL = '"}'

SpeakListener = Callable[[bool], None]


class VoiceStream:
    """Background thread that owns the realtime socket and the microphone.

    ``start`` and ``close`` never block the caller (the Textual loop), and
    either may be called any number of times in any order. ``start`` after
    ``close`` begins a new session at once; its thread first waits for the
    previous one to release the socket and the microphone.
    """

    def __init__(self, *, on_speaking: SpeakListener | None = None) -> None:
        self._on_speaking = on_speaking
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Set when the current session's thread has exited.
        self._closed = threading.Event()
        self._error = ""
        self._speaking = False
        # The mic stays quiet while a coding run is in flight so the socket
        # does not talk over the agent. It opens again for the final answer.
        self._listen = threading.Event()
        self._listen.set()
        # One event per session, so closing an old session cannot stop a new one.
        self._closing = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._session_task: asyncio.Task[None] | None = None
        self._socket: Any = None
        self._stop: asyncio.Event | None = None

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def error(self) -> str:
        return self._error

    def start(self) -> None:
        with self._lifecycle_lock:
            previous = self._thread
            if previous is not None and previous.is_alive() and not self._closing.is_set():
                return
            closing = threading.Event()
            self._closing = closing
            self._closed.clear()
            self._error = ""
            thread = threading.Thread(
                target=self._run, args=(previous, closing), name="grok-voice", daemon=True,
            )
            self._thread = thread
            thread.start()
        # Do not wait here. The caller is the Textual loop, and a connect that
        # takes seconds freezes the cursor even though the terminal still
        # accepts keystrokes.

    def hold(self) -> None:
        """Stop sending mic audio. The socket stays open."""
        self._listen.clear()

    def resume(self) -> None:
        """Send mic audio again."""
        self._listen.set()

    def say(self, text: str) -> None:
        """Queue ``text`` on the open socket. The socket stays up to play it."""
        spoken = " ".join(text.split())
        loop = self._loop
        if not spoken or loop is None or self._closing.is_set():
            return

        def schedule() -> None:
            if self._socket is not None and not self._closing.is_set():
                asyncio.create_task(self._say(spoken[:600]))

        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(schedule)

    def close(self, *, timeout: float = 0.0) -> None:
        """Stop even a session that is still connecting; safe before start.

        Only queues cancellation, so the Textual loop never waits on the
        provider. ``timeout`` waits that long for the thread (app shutdown and
        tests). A worker callback never joins itself.
        """
        with self._lifecycle_lock:
            already_closing = self._closing.is_set()
            self._closing.set()
            thread = self._thread
            loop = self._loop
            if loop is not None and not already_closing:
                def cancel() -> None:
                    if self._session_task is not None:
                        self._session_task.cancel()
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(cancel)
        if timeout > 0 and thread is not None and threading.current_thread() is not thread:
            thread.join(timeout=timeout)
        with self._lifecycle_lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def _run(self, previous: threading.Thread | None, closing: threading.Event) -> None:
        # The previous session may still be closing its socket and mic. Wait
        # here, off the UI thread, so two sessions never hold the device.
        if previous is not None:
            previous.join()
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            self._session_task = loop.create_task(self._session())
            if closing.is_set():
                self._session_task.cancel()
            loop.run_until_complete(self._session_task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._error = f"Voice stream failed · {exc}"
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            self._socket = None
            self._session_task = None
            self._stop = None
            self._loop = None
            loop.close()
            if self._thread is threading.current_thread():
                self._closed.set()

    async def _session(self) -> None:
        try:
            import websockets
        except ImportError:
            self._error = "Voice mode needs the websockets package."
            return
        try:
            token, headers = grok_voice_credentials()
        except Exception as exc:  # UnavailableVoice or a credential read failure
            self._error = str(exc)
            return
        query = urlencode({"model": VOICE_REALTIME_MODEL})
        url = f"{REALTIME_URL}?{query}"
        try:
            socket = await websockets.connect(
                url,
                additional_headers={"Authorization": f"Bearer {token}", **headers},
                max_size=8 * 1024 * 1024,
                # The closing handshake must not hold the mic (and the next
                # session) for websockets' default 10 s.
                close_timeout=1,
            )
        except Exception as exc:
            self._error = f"Voice stream failed · {exc}"
            return
        self._socket = socket
        stop = self._stop = asyncio.Event()
        tasks: list[asyncio.Task[Any]] = []
        try:
            await socket.send(json.dumps(_session_update()))
            tasks = [
                asyncio.create_task(self._pump_mic(socket)),
                asyncio.create_task(self._pump_events(socket)),
                asyncio.create_task(stop.wait()),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._socket = None
            with contextlib.suppress(Exception):
                await socket.close()

    async def _say(self, text: str) -> None:
        socket = self._socket
        if socket is None:
            return
        try:
            await socket.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": f"Say this to the user: {text}"}],
                        },
                    }
                )
            )
            await socket.send(json.dumps({"type": "response.create"}))

        except Exception as exc:
            self._error = f"Voice stream failed · {exc}"
            if self._stop is not None:
                self._stop.set()

    async def _pump_mic(self, socket: Any) -> None:
        """Read PCM from the default input and append it to the voice buffer."""
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError("Voice mode needs the sounddevice package.") from exc
        except OSError as exc:  # The binding imports, then cannot load PortAudio.
            raise RuntimeError("Voice mode needs the PortAudio library.") from exc
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=MIC_QUEUE_BLOCKS)
        listen = self._listen

        def enqueue(chunk: bytes) -> None:
            # This runs on the event loop, where QueueFull actually occurs.
            if queue.full():
                queue.get_nowait()  # Keep recent audio instead of increasing latency.
            queue.put_nowait(chunk)

        def _callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            del frames, time_info, status
            # Held: drop the block here, without a copy or a loop wakeup.
            if not listen.is_set():
                return
            # Encoding reads PortAudio's reused buffer directly: one copy.
            chunk = base64.b64encode(indata)
            try:
                loop.call_soon_threadsafe(enqueue, chunk)
            except RuntimeError:
                return

        try:
            stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                callback=_callback,
                blocksize=MIC_BLOCK_FRAMES,
            )
        except Exception as exc:
            raise RuntimeError(f"Voice microphone failed · {exc}") from exc
        with stream:
            while True:
                chunk = await queue.get()
                if not listen.is_set():
                    continue
                await socket.send(_APPEND_HEAD + chunk.decode("ascii") + _APPEND_TAIL)

    async def _pump_events(self, socket: Any) -> None:
        player = _PcmPlayer(on_speaking=self._set_speaking)
        try:
            async for raw in socket:
                if isinstance(raw, bytes):
                    player.write(raw)
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = str(event.get("type") or "")
                if kind in {"response.output_audio.delta", "response.audio.delta"}:
                    audio = event.get("delta") or ""
                    if isinstance(audio, str) and audio:
                        player.write(base64.b64decode(audio))
                elif kind in {"response.done", "response.output_audio.done", "response.audio.done"}:
                    player.finish()
        finally:
            player.close()
            self._set_speaking(False)

    def _set_speaking(self, speaking: bool) -> None:
        if speaking == self._speaking:
            return
        self._speaking = speaking
        if self._on_speaking is not None:
            self._on_speaking(speaking)


def _session_update() -> dict[str, Any]:
    return {
        "type": "session.update",
        "session": {
            "voice": GROK_TTS_VOICE,
            "instructions": (
                "You are Symphony's voice. Speak while the user is talking only to "
                "acknowledge briefly. When asked to say a specific sentence, say that "
                "sentence and nothing else."
            ),
            "turn_detection": {"type": "server_vad"},
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}},
                "output": {"format": {"type": "audio/pcm", "rate": SAMPLE_RATE}},
            },
        },
    }


class _PcmPlayer:
    """Play 16-bit PCM by writing a WAV and handing it to afplay or ffplay.

    Streaming PCM into ffplay's stdin and then closing that stdin made ffplay
    exit before the buffer played, so the reply produced no sound. One file
    played after the response finishes does play, and it needs no NumPy.
    """

    def __init__(self, *, on_speaking: SpeakListener) -> None:
        self._on_speaking = on_speaking
        self._pcm = bytearray()
        self._player: subprocess.Popen[bytes] | None = None
        self._path: str | None = None
        self._lock = threading.RLock()
        self._closed = False

    def write(self, pcm: bytes) -> None:
        with self._lock:
            if not self._closed:
                self._pcm.extend(pcm)

    def finish(self) -> None:
        with self._lock:
            pcm = bytes(self._pcm)
            self._pcm.clear()
            # Providers can send both audio.done and response.done. The latter
            # must not mark still-playing audio as silent.
            if not pcm or self._closed:
                return
            self._stop_player()
            path = _write_wav(pcm)
            try:
                command = _wav_command(path)
                if command is None:
                    return
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._player = process
                self._path = path
                self._on_speaking(True)
                threading.Thread(target=self._wait, args=(process, path), daemon=True).start()
            finally:
                if self._path != path:
                    with contextlib.suppress(OSError):
                        os.remove(path)

    def _wait(self, process: subprocess.Popen[bytes], path: str) -> None:
        try:
            process.wait(timeout=120)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                process.kill()
            process.wait()
        finally:
            with self._lock:
                with contextlib.suppress(OSError):
                    os.remove(path)
                if self._player is process:
                    self._player = None
                    self._path = None
                    self._on_speaking(False)

    def _stop_player(self) -> None:
        process = self._player
        path = self._path
        self._player = None
        self._path = None
        if process is not None:
            with contextlib.suppress(OSError):
                process.kill()
            process.wait()
        if path is not None:
            with contextlib.suppress(OSError):
                os.remove(path)
        if process is not None:
            self._on_speaking(False)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._pcm.clear()
            self._stop_player()
            self._on_speaking(False)


def _write_wav(pcm: bytes) -> str:
    import tempfile
    import wave

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    path = handle.name
    handle.close()
    try:
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm)
        return path
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(path)
        raise


def _wav_command(path: str) -> list[str] | None:
    if sys.platform == "darwin" and shutil.which("afplay"):
        return ["afplay", path]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
    return None
