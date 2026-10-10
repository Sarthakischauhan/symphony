"""Voice capture, xAI transcription, and audio playback helpers."""

from __future__ import annotations

import os
from typing import Any, Protocol

# Speech-to-text model. grok-voice-think-fast-2.0 is a realtime speech model and
# is not accepted by POST /v1/stt, which 404s on any other id. Transcribe 2.0
# is the documented STT model. The chat model is never switched.
GROK_VOICE_MODEL = "grok-voice-transcribe-2.0"
GROK_VOICE_FULL_ID = f"grok:{GROK_VOICE_MODEL}"
# Built-in TTS voice. eve is the API default.
GROK_TTS_VOICE = "eve"

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


class UnavailableVoice(RuntimeError):
    """Raised when the microphone or the Grok voice model cannot be reached."""


# The Grok CLI chat proxy only serves chat models. ``/chat/completions`` there
# is a 404, so voice audio goes to the xAI audio endpoint. The bearer is still
# the same device-login token a ``grok:`` model call uses.
XAI_AUDIO_BASE_URL = "https://api.x.ai/v1"


def grok_voice_credentials() -> tuple[str, dict[str, str]]:
    """Bearer and extra headers for one voice transcription.

    An ``XAI_API_KEY`` wins, same as model calls. Otherwise the stored xAI
    device login is reused. The chat-proxy base URL is not used: it has no
    audio route.
    """
    api_key = os.getenv("XAI_API_KEY", "").strip()
    if api_key:
        return api_key, {}
    from core_ai.oauth.runtime import oauth_runtime_for

    runtime = oauth_runtime_for("grok")
    if runtime is None or not runtime.api_key:
        raise UnavailableVoice(
            "Voice mode needs a Grok sign-in. Run /provider and choose xAI, or set XAI_API_KEY."
        )
    return runtime.api_key, dict(runtime.extra_headers)


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


# Spoken replies stay short so a long tool report is not read in full.
SPOKEN_REPLY_LIMIT = 600


_SPOKEN_SUMMARY = "## Spoken summary"


def spoken_summary(text: str, *, limit: int = SPOKEN_REPLY_LIMIT) -> str:
    """The summary the model wrote into its final answer, ready for TTS.

    The section is part of the same response, not a later call. If the model
    left it out, the opening of the answer is spoken instead.
    """
    section = ""
    marker = text.lower().rfind(_SPOKEN_SUMMARY.lower())
    if marker >= 0:
        section = text[marker + len(_SPOKEN_SUMMARY):].strip()
    return spoken_text(section or text, limit=limit)


def spoken_text(text: str, *, limit: int = SPOKEN_REPLY_LIMIT) -> str:
    """Plain text safe to send to TTS. Markup and fences are dropped."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    kept: list[str] = []
    in_fence = False
    for line in cleaned.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.strip():
            kept.append(line.strip())
    cleaned = " ".join(kept)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def synthesize_speech(text: str, *, voice_id: str = GROK_TTS_VOICE) -> bytes:
    """Turn a reply into MP3 bytes via POST /v1/tts. Empty text yields no audio."""
    spoken = spoken_text(text)
    if not spoken:
        return b""
    api_key, extra_headers = grok_voice_credentials()
    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **extra_headers,
    }
    response = httpx.post(
        f"{XAI_AUDIO_BASE_URL}/tts",
        headers=headers,
        json={"text": spoken, "voice_id": voice_id, "language": "en"},
        timeout=60.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip().splitlines()
        suffix = f" · {detail[0][:180]}" if detail else ""
        raise UnavailableVoice(
            f"Voice playback failed · {exc.response.status_code}{suffix}"
        ) from exc
    return response.content


def play_mp3(audio: bytes) -> None:
    """Play MP3 bytes on the default output. No extra audio package required."""
    if not audio:
        return
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
        handle.write(audio)
        path = handle.name
    try:
        player = _mp3_player(path)
        if player is None:
            raise UnavailableVoice("No audio player found to speak the reply.")
        subprocess.run(player, check=False, capture_output=True, timeout=120)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _mp3_player(path: str) -> list[str] | None:
    import shutil
    import sys

    if sys.platform == "darwin" and shutil.which("afplay"):
        return ["afplay", path]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
    if shutil.which("mpv"):
        return ["mpv", "--no-video", "--really-quiet", path]
    return None


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
    return sd


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


def record_wav(
    sd: Any,
    *,
    seconds: float = 8,
    sample_rate: int = 16_000,
    silence_seconds: float = 0.7,
) -> bytes:
    """Record mono 16-bit PCM until the speaker pauses, then wrap it in a WAV.

    A fixed sleep made every utterance wait the full ``seconds`` before it
    could be transcribed. Recording now ends after ``silence_seconds`` of quiet
    once speech has started, and ``seconds`` is only the safety cap.

    ``RawInputStream`` keeps the samples in a ``bytearray``. ``sd.rec`` would
    allocate a NumPy array and force that dependency on every user.
    """
    import audioop
    import io
    import time
    import wave

    captured = bytearray()
    heard_speech = False
    last_speech = time.monotonic()
    started = last_speech
    # int16 RMS. Normal speech sits well above this; a quiet room does not.
    speech_rms = 500

    def _on_audio(indata: bytes, frames: int, time_info: Any, status: Any) -> None:
        nonlocal heard_speech, last_speech
        del frames, time_info, status
        chunk = bytes(indata)
        captured.extend(chunk)
        if audioop.rms(chunk, 2) >= speech_rms:
            heard_speech = True
            last_speech = time.monotonic()

    try:
        stream = sd.RawInputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            callback=_on_audio,
        )
    except Exception as exc:  # PortAudio errors are not ImportError
        raise UnavailableVoice(f"Microphone unavailable · {exc}") from exc
    with stream:
        while time.monotonic() - started < seconds:
            time.sleep(0.05)
            if heard_speech and time.monotonic() - last_speech >= silence_seconds:
                break
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(captured)
    return buffer.getvalue()


class MicrophoneCapture:
    """Record one utterance from the default input device.

    Imported lazily so the TUI still starts on a machine without an audio
    extra installed. The first listen installs ``sounddevice`` into this
    interpreter; if that fails, the user gets the install command instead of
    a crash. Recording itself does not need NumPy.
    """

    def listen(self) -> bytes:
        return record_wav(_load_sounddevice())
