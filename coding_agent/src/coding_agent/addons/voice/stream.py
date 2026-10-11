"""One background speech-to-speech socket for one voice listen.

The socket is ``wss://api.x.ai/v1/realtime`` with ``grok-voice-think-fast-2.0``.
Mic audio goes in as PCM. On commit the model speaks one short acknowledgement
and the socket closes, so it is not billed through the coding run. The spoken
summary is a second, mic-less connection that closes once that line has played.
``close`` runs when the app quits.
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

# The speech-to-speech model. Pinned: the "latest" alias is not what the
# account is billed or served as, and a pin does not drift under a user.
VOICE_REALTIME_MODEL = "grok-voice-think-fast-2.0"
REALTIME_URL = "wss://api.x.ai/v1/realtime"
SAMPLE_RATE = 24_000
# 40 ms of mono int16 per callback and per socket message: 25 sends a second.
MIC_BLOCK_FRAMES = SAMPLE_RATE * 40 // 1000
# Mic blocks waiting for the socket. Past this the oldest is dropped, so a
# slow link costs at most ~1.3 s of latency instead of growing without bound.
MIC_QUEUE_BLOCKS = 32
# Quiet this long after speech, and the utterance is committed. Enter commits
# sooner. The pause is counted from audio blocks, not from a UI timer.
PAUSE_COMMIT_S = 3.0
PAUSE_COMMIT_BLOCKS = int(PAUSE_COMMIT_S * 1000 / 40)
# int16 RMS. Normal speech sits well above this; a quiet room does not.
SPEECH_RMS = 500
# The audio is base64 and needs no escaping, so the JSON is two fixed halves.
_APPEND_HEAD = '{"type": "input_audio_buffer.append", "audio": "'
_APPEND_TAIL = '"}'
_COMMIT = '{"type": "input_audio_buffer.commit"}'
# Commit alone does not make the model speak. This asks for the one line
# the session instructions allow: a short acknowledgement, not the answer.
_ACK = (
    '{"type": "response.create", "response": {"instructions": '
    '"Reply with one short acknowledgement of what the user just asked. '
    'One sentence. Do not answer, explain, or give steps."}}'
)

SpeakListener = Callable[[bool], None]
TranscriptListener = Callable[[str], None]


class VoiceStream:
    """Background thread that owns the realtime socket and the microphone.

    ``start`` and ``close`` never block the caller (the Textual loop), and
    either may be called any number of times in any order. ``start`` after
    ``close`` begins a new session at once; its thread first waits for the
    previous one to release the socket and the microphone.
    """

    def __init__(
        self,
        *,
        on_speaking: SpeakListener | None = None,
        on_transcript: TranscriptListener | None = None,
        on_commit: Callable[[], None] | None = None,
    ) -> None:
        self._on_speaking = on_speaking
        self._on_transcript = on_transcript
        self._on_commit = on_commit
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
        # Set from the UI thread (Enter). The mic callback consumes it.
        self._commit_now = False
        self._committed = False
        self._transcript = ""
        self._commit_sent = False
        # A summary spoken before this session has connected.
        self._pending_say = ""
        # A summary-only session never opens the microphone.
        self._speak_only = False
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

    @property
    def alive(self) -> bool:
        """True while this session's socket thread is still running."""
        thread = self._thread
        return thread is not None and thread.is_alive() and not self._closing.is_set()

    def start(self, *, speak_only: bool = False) -> None:
        with self._lifecycle_lock:
            previous = self._thread
            if previous is not None and previous.is_alive() and not self._closing.is_set():
                return
            closing = threading.Event()
            self._closing = closing
            self._closed.clear()
            self._error = ""
            self._commit_now = False
            self._committed = False
            self._transcript = ""
            self._commit_sent = False
            # A summary may already be queued by say() before this session exists.
            self._speak_only = speak_only
            if speak_only:
                self._listen.clear()
            else:
                self._pending_say = ""
                self._listen.set()
            thread = threading.Thread(
                target=self._run, args=(previous, closing), name="grok-voice", daemon=True,
            )
            self._thread = thread
            thread.start()
        # Do not wait here. The caller is the Textual loop, and a connect that
        # takes seconds freezes the cursor even though the terminal still
        # accepts keystrokes.

    def hold(self) -> None:
        """Stop sending mic audio. The socket stays open until speech ends."""
        self._listen.clear()

    def resume(self) -> None:
        """Send mic audio again, including after an utterance already committed."""
        self._committed = False
        self._commit_sent = False
        self._commit_now = False
        self._transcript = ""
        self._listen.set()

    def commit(self) -> None:
        """End the utterance now. Enter lands here; a 3 s pause does too.

        The flag is read on the audio callback, so this never touches the
        socket or waits, and the UI thread stays free.
        """
        self._commit_now = True

    def say(self, text: str) -> None:
        """Speak ``text`` on this socket once it is connected.

        Called before the socket exists, the line waits and is sent from the
        session itself. It is never dropped on the floor.
        """
        spoken = " ".join(text.split())[:600]
        if not spoken or self._closing.is_set():
            return
        self._pending_say = spoken
        loop = self._loop
        if loop is None:
            return

        def schedule() -> None:
            if self._socket is not None and not self._closing.is_set() and self._pending_say:
                pending = self._pending_say
                self._pending_say = ""
                asyncio.create_task(self._say(pending))

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
            pending = self._pending_say
            if pending:
                self._pending_say = ""
                await self._say(pending)
            tasks = [
                asyncio.create_task(self._pump_events(socket)),
                asyncio.create_task(stop.wait()),
            ]
            # A summary connection has no microphone. Opening one would capture
            # the room (and the speaker) for a line that is already text.
            if not self._speak_only:
                tasks.insert(0, asyncio.create_task(self._pump_mic(socket)))
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
        """Speak ``text`` on this same socket. It is not the chat answer.

        The words are a separate spoken line. The coding transcript stays
        whatever the chat model wrote.
        """
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
                            "content": [{
                                "type": "input_text",
                                "text": f"Say this to the user, verbatim, and nothing else: {text}",
                            }],
                        },
                    }
                )
            )
            await socket.send(json.dumps({
                "type": "response.create",
                "response": {"instructions": f"Say exactly: {text}"},
            }))

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
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=MIC_QUEUE_BLOCKS)
        listen = self._listen
        quiet_blocks = 0
        heard_speech = False

        def enqueue(chunk: bytes | None) -> None:
            # This runs on the event loop, where QueueFull actually occurs.
            # A commit marker is never dropped: it is what ends the utterance.
            if chunk is None:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(None)
                return
            if queue.full():
                dropped = queue.get_nowait()  # Keep recent audio, not the commit.
                if dropped is None:
                    queue.get_nowait()
                    queue.put_nowait(None)
            queue.put_nowait(chunk)

        def _callback(indata: Any, frames: int, time_info: Any, status: Any) -> None:
            nonlocal quiet_blocks, heard_speech
            del frames, time_info, status
            # Held or already committed: drop the block, no copy, no wakeup.
            # resume() clears the committed flag, so the next utterance can
            # be gathered without opening another microphone.
            if not listen.is_set() or self._committed:
                return
            if self._commit_now:
                self._commit_now = False
                self._committed = True
                try:
                    loop.call_soon_threadsafe(enqueue, None)
                except RuntimeError:
                    return
                return
            # RMS reads the reused buffer; encoding is the one copy.
            if _pcm16_rms(indata) >= SPEECH_RMS:
                heard_speech = True
                quiet_blocks = 0
            elif heard_speech:
                quiet_blocks += 1
            chunk = base64.b64encode(indata)
            try:
                loop.call_soon_threadsafe(enqueue, chunk)
            except RuntimeError:
                return
            if heard_speech and quiet_blocks >= PAUSE_COMMIT_BLOCKS and not self._committed:
                self._committed = True
                try:
                    loop.call_soon_threadsafe(enqueue, None)
                except RuntimeError:
                    self._committed = False
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
                if chunk is None:
                    await socket.send(_COMMIT)
                    await socket.send(_ACK)
                    # The mic stays open. Further blocks are dropped until the
                    # next listen calls resume(), so one commit does not kill
                    # the session and the next voice turn still has a socket.
                    self._listen.clear()
                    self._finish_commit()
                    continue
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
                if kind in {
                    "conversation.item.input_audio_transcription.delta",
                    "conversation.item.input_audio_transcription.completed",
                }:
                    self._take_transcript(event, final=kind.endswith("completed"))
                elif kind in {"response.output_audio.delta", "response.audio.delta"}:
                    audio = event.get("delta") or ""
                    if isinstance(audio, str) and audio:
                        player.write(base64.b64decode(audio))
                elif kind in {"response.output_audio.done", "response.audio.done", "response.done"}:
                    # Play once. Some sessions send audio.done and then
                    # response.done; some send only response.done. The second
                    # call finds an empty buffer and does not cut the WAV.
                    # Hang up only after playback has started. The socket
                    # close that follows must not be what stops the sound.
                    if player.finish() and self._stop is not None:
                        self._stop.set()
        finally:
            # release() drops only audio that never got a done event. Playback
            # that just started keeps running; close() would kill afplay and
            # delete the WAV before the summary could be heard.
            player.release()

    def _take_transcript(self, event: dict[str, Any], *, final: bool) -> None:
        """Publish the words heard so far. Deltas arrive while the user speaks."""
        text = event.get("delta") or event.get("transcript") or event.get("text") or ""
        if not isinstance(text, str) or not text:
            return
        if final or not self._transcript:
            self._transcript = text
        elif text.startswith(self._transcript):
            self._transcript = text
        else:
            self._transcript = (self._transcript + text).strip()
        if self._on_transcript is not None:
            self._on_transcript(self._transcript)

    def _finish_commit(self) -> None:
        """The utterance is on the wire. Hand it to the caller once."""
        if self._commit_sent or self._on_commit is None:
            return
        self._commit_sent = True
        self._on_commit()

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
                "You are Symphony's voice. Speak only a brief acknowledgement of what "
                "the user just said. Do not answer the task, give steps, or continue "
                "the conversation. When asked to say a specific sentence, say that "
                "sentence and nothing else."
            ),
            # The client commits after a 3 s pause or Enter. Server VAD would
            # cut the utterance on its own, shorter, silence.
            "turn_detection": None,
            "input_audio_transcription": {"model": VOICE_REALTIME_MODEL},
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

    def finish(self) -> bool:
        """Start playback of the audio gathered so far. True once it is playing."""
        with self._lock:
            # audio.done and response.done can both arrive. Play whatever has
            # arrived, once; the second call sees an empty buffer and leaves
            # the player that is already running alone.
            pcm = bytes(self._pcm)
            self._pcm.clear()
            if self._player is not None:
                return True
            if not pcm or self._closed:
                return False
            self._stop_player()
            path = _write_wav(pcm)
            try:
                command = _wav_command(path)
                if command is None:
                    return False
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._player = process
                self._path = path
                self._on_speaking(True)
                threading.Thread(target=self._wait, args=(process, path), daemon=True).start()
            finally:
                if self._path != path:
                    with contextlib.suppress(OSError):
                        os.remove(path)
            return self._player is not None

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

    def release(self) -> None:
        """Drop audio that was never finished. Leave a playing WAV alone.

        The socket closing is not the user cancelling. Killing the player here
        is what made the spoken summary silent: finish() had just started
        afplay, and this deleted its file.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._pcm.clear()

    def close(self) -> None:
        with self._lock:
            if self._closed and self._player is None:
                return
            self._closed = True
            self._pcm.clear()
            self._stop_player()
            self._on_speaking(False)


def _pcm16_rms(pcm: Any) -> int:
    """RMS of one mono int16 block. No audioop and no NumPy: both cost an import."""
    samples = memoryview(pcm).cast("B").cast("h")
    count = len(samples)
    if not count:
        return 0
    total = 0
    for sample in samples:
        total += sample * sample
    return int((total / count) ** 0.5)


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
