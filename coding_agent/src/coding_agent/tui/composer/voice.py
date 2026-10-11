"""Voice capture and xAI transcription for the TUI composer.

Credentials, the spoken-summary split, and MP3 playback belong to the voice
add-on (``coding_agent.addons.voice``); this module imports them from there.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from coding_agent.addons.voice.credentials import (
    XAI_AUDIO_BASE_URL,
    UnavailableVoice,
    grok_voice_credentials,
)

# Speech-to-text model. The realtime alias is not accepted by POST /v1/stt.
# Transcribe 2.0 is the STT model xAI documents as the default. The chat
# model is never switched.
GROK_VOICE_MODEL = "grok-voice-transcribe-2.0"
GROK_VOICE_FULL_ID = f"grok:{GROK_VOICE_MODEL}"

# Alternate the composer border every half second.
VOICE_BLINK_INTERVAL_S = 0.5
VOICE_LIGHT_PURPLE = "#D7C4FB"
VOICE_DARK_PURPLE = "#A371F7"


class VoiceTranscriber(Protocol):
    """Turns one captured utterance into text. Tests inject a fake."""

    def transcribe(self, audio: bytes, *, model: str) -> str: ...


class VoiceCapture(Protocol):
    """Records one utterance. ``None`` means the microphone stopped."""

    def listen(self) -> bytes | None: ...

    def close(self) -> None:
        """Release the microphone; a blocked ``listen`` returns ``None`` soon after."""


def transcript_text(body: dict[str, Any]) -> str:
    """Read a transcript from either the audio API or a chat completion."""
    text = body.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    return content.strip() if isinstance(content, str) else ""


class GrokVoiceTranscriber:
    """Transcribe one utterance with grok-voice-transcribe-2.0.

    The WAV is posted once to ``/stt``. Nothing stays open between utterances.
    Auth is the Grok OAuth session when there is no API key.
    """

    def transcribe(self, audio: bytes, *, model: str = GROK_VOICE_MODEL) -> str:
        if not audio:
            return ""
        api_key, extra_headers = grok_voice_credentials()
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - httpx is a core dependency
            raise UnavailableVoice("Voice mode needs httpx.") from exc

        headers = {"Authorization": f"Bearer {api_key}", **extra_headers}
        # Model fields must precede the file. xAI ignores fields that follow it.
        response = httpx.post(
            f"{XAI_AUDIO_BASE_URL}/stt",
            headers=headers,
            data={"model": model, "language": "en"},
            files={"file": ("utterance.wav", audio, "audio/wav")},
            timeout=30.0,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip().splitlines()
            suffix = f" · {detail[0][:180]}" if detail else ""
            raise UnavailableVoice(
                f"Voice transcription failed · {exc.response.status_code}{suffix}"
            ) from exc
        return transcript_text(response.json())


def _load_sounddevice() -> Any:
    """Import PortAudio, installing the voice extra once if it is missing."""
    try:
        import sounddevice as sd
    except ImportError:
        _install_voice_extra()
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise UnavailableVoice(
                "Voice mode could not install the microphone package. "
                "Run: uv sync --package symphony-code --extra voice"
            ) from exc
        except OSError as exc:
            raise UnavailableVoice(_NO_PORTAUDIO) from exc
    except OSError as exc:
        # sounddevice imports, then cannot find libportaudio. pip cannot fix that.
        raise UnavailableVoice(_NO_PORTAUDIO) from exc
    return sd


_NO_PORTAUDIO = (
    "Voice mode needs the PortAudio library. "
    "Install it (brew install portaudio, or apt install libportaudio2)."
)


def _install_voice_extra() -> None:
    """Install ``sounddevice`` into the interpreter running the TUI."""
    import shutil
    import subprocess
    import sys

    commands: list[list[str]] = []
    uv = shutil.which("uv")
    if uv:
        commands.append([uv, "pip", "install", "sounddevice>=0.5.1", "--python", sys.executable])
    commands.append([sys.executable, "-m", "pip", "install", "sounddevice>=0.5.1"])
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0:
            return


# 32 ms per callback (512 frames at 16 kHz): a finer end-of-speech check than
# the old 50 ms poll, ~31 wakeups a second, and not left to the host's choice.
CAPTURE_BLOCK_MS = 32
# int16 RMS. Normal speech sits well above this; a quiet room does not.
SPEECH_RMS = 500


def record_wav(
    sd: Any,
    *,
    seconds: float = 8,
    sample_rate: int = 16_000,
    silence_seconds: float = 0.7,
    stop: threading.Event | None = None,
) -> bytes:
    """Record mono 16-bit PCM until the speaker pauses, then wrap it in a WAV.

    Recording ends after ``silence_seconds`` of quiet once speech has started;
    ``seconds`` is only the safety cap. The PortAudio callback decides that
    from the frames it has counted and sets an event, so this thread blocks on
    the event instead of waking to poll. Setting ``stop`` ends it early.

    ``RawInputStream`` keeps the samples in a ``bytearray``. ``sd.rec`` would
    allocate a NumPy array and force that dependency on every user.
    """
    import io
    import warnings
    import wave

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from audioop import rms  # Removed in Python 3.13.
    except ImportError:
        rms = _pcm16_rms

    ended = stop if stop is not None else threading.Event()
    captured = bytearray()
    heard_speech = False
    quiet_frames = 0
    silence_frames = int(silence_seconds * sample_rate)

    def _on_audio(indata: Any, frames: int, time_info: Any, status: Any) -> None:
        nonlocal heard_speech, quiet_frames
        del time_info, status
        if ended.is_set():
            return
        # PortAudio reuses ``indata``; this extend is the only copy.
        captured.extend(indata)
        if rms(indata, 2) >= SPEECH_RMS:
            heard_speech = True
            quiet_frames = 0
        else:
            quiet_frames += frames
        if heard_speech and quiet_frames >= silence_frames:
            ended.set()

    try:
        stream = sd.RawInputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            callback=_on_audio,
            blocksize=sample_rate * CAPTURE_BLOCK_MS // 1000,
        )
    except Exception as exc:  # PortAudio errors are not ImportError
        raise UnavailableVoice(f"Microphone unavailable · {exc}") from exc
    with stream:
        ended.wait(seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(captured)
    return buffer.getvalue()


def _pcm16_rms(pcm: Any, width: int) -> int:
    """``audioop.rms`` for mono int16, for Pythons that no longer ship audioop."""
    del width
    samples = memoryview(pcm).cast("B").cast("h")
    if not samples:
        return 0
    return int((sum(sample * sample for sample in samples) / len(samples)) ** 0.5)


class MicrophoneCapture:
    """Record utterances from the default input device until ``close``.

    Imported lazily so the TUI still starts on a machine without an audio
    extra installed. The first listen installs ``sounddevice`` into this
    interpreter; if that fails, the user gets the install command instead of
    a crash. Recording itself does not need NumPy.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closed = False
        self._recording: threading.Event | None = None

    def listen(self) -> bytes | None:
        sd = _load_sounddevice()
        stop = threading.Event()
        with self._lock:
            if self._closed:
                return None
            self._recording = stop
        try:
            audio = record_wav(sd, stop=stop)
        finally:
            with self._lock:
                self._recording = None
        return None if self._closed else audio

    def close(self) -> None:
        """Idempotent and non-blocking, so the UI thread may call it."""
        with self._lock:
            self._closed = True
            if self._recording is not None:
                self._recording.set()
