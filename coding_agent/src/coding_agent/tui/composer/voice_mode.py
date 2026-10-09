"""Enter and leave voice mode without disturbing an in-flight turn.

Listening runs off the UI thread. A 0.5-second timer alternates the existing
composer border color without hiding or resizing the input.
"""

from __future__ import annotations

from typing import Any

from coding_agent.credentials import OFFLINE_HINT
from coding_agent.tui.composer.input import Composer, PromptInput, QueuedTurn
from coding_agent.tui.composer.voice import (
    GROK_VOICE_MODEL,
    GrokVoiceTranscriber,
    MicrophoneCapture,
    VOICE_BLINK_INTERVAL_S,
    UnavailableVoice,
    VoiceCapture,
    VoiceTranscriber,
)


def toggle_voice(app: Any) -> None:
    """Start voice mode, or stop it and restore the composer."""
    if getattr(app, "_voice_active", False):
        stop_voice(app, reason="toggled")
        return
    if getattr(app, "_busy", False):
        app.add_notice("Voice mode is unavailable while a turn is running.", "warning")
        return
    if getattr(app, "_agent", None) is None:
        app.add_notice(OFFLINE_HINT, "error")
        return
    start_voice(app)


def start_voice(
    app: Any,
    *,
    capture: VoiceCapture | None = None,
    transcriber: VoiceTranscriber | None = None,
) -> None:
    """Keep the composer visible and listen for one utterance."""
    # A cancelled thread can still finish. Bind both dependencies and a unique
    # session token now, not when the worker eventually starts running.
    session = object()
    app._voice_session = session
    app._voice_active = True
    try:
        app._voice_capture = capture if capture is not None else MicrophoneCapture()
        app._voice_transcriber = transcriber if transcriber is not None else GrokVoiceTranscriber()
        _set_voice_border(app, True)
        app.add_notice("Voice mode · listening with Grok Voice Think Fast. Ctrl+A or Esc to stop.")
        bound_capture = app._voice_capture
        bound_transcriber = app._voice_transcriber
        app.run_worker(
            lambda: _listen(app, bound_capture, bound_transcriber, session),
            exclusive=True, group="voice", thread=True,
        )
    except Exception as exc:
        _finish_voice(app, "", f"Voice mode failed · {exc}", session)


def stop_voice(app: Any, *, reason: str) -> None:
    """User cancelled. Close the stream and restore the composer once."""
    app._voice_active = False
    app._voice_session = None
    try:
        close_voice_addon(app)
    except Exception as exc:
        app.add_notice(f"Voice mode failed · {exc}", "error")
    finally:
        _restore_composer(app)
    if reason == "toggled":
        app.add_notice("Voice mode off.")


def _listen(
    app: Any, capture: VoiceCapture, transcriber: VoiceTranscriber, session: object,
) -> None:
    """Capture and transcribe away from the UI thread, then submit the text.

    Textual runs a ``thread=True`` worker as a plain function. Widget updates
    go through ``call_from_thread`` so the composer styles are only
    touched on the app thread.
    """
    try:
        audio = capture.listen()
        text = transcriber.transcribe(audio, model=GROK_VOICE_MODEL).strip()
    except UnavailableVoice as exc:
        app.call_from_thread(_finish_voice, app, "", str(exc), session)
        return
    except Exception as exc:  # noqa: BLE001 - surface any capture/API failure as a notice
        app.call_from_thread(_finish_voice, app, "", f"Voice mode failed · {exc}", session)
        return
    app.call_from_thread(_finish_voice, app, text.strip(), "", session)


def _finish_voice(app: Any, text: str, error: str, session: object) -> None:
    if not getattr(app, "_voice_active", False) or getattr(app, "_voice_session", None) is not session:
        return
    # Keep the border blinking through transcription, execution, and speech.
    app._voice_active = False
    app._voice_session = None
    if error:
        _restore_composer(app)
        app.add_notice(error, "error")
        return
    if not text:
        _restore_composer(app)
        app.add_notice("Voice mode heard nothing.", "warning")
        return
    try:
        submit_voice_turn(app, text)
    except Exception as exc:
        try:
            close_voice_addon(app)
        except Exception:
            pass
        _restore_composer(app)
        app.add_notice(f"Voice mode failed · {exc}", "error")


def _restore_composer(app: Any) -> None:
    """Clear voice styling and restore input focus after cancellation/error."""
    _set_voice_border(app, False)
    prompt = app.query_one("#prompt", PromptInput)
    prompt.disabled = False
    prompt.focus()
    app._set_status("")


def submit_voice_turn(app: Any, text: str) -> None:
    """Hand a transcript to the composer path and arm the voice hooks."""
    if app._agent is None:
        _restore_composer(app)
        app.add_notice(OFFLINE_HINT, "error")
        return
    error = ensure_voice_addon(app)
    if error:
        _restore_composer(app)
        app.add_notice(error, "error")
        return
    turn = QueuedTurn(text, text, (), ())
    if app._busy:
        app.queue_turn(turn)
        return
    app._start_turn(turn)


def ensure_voice_addon(app: Any) -> str:
    """Reuse the voice add-on and open/arm its resources for one voice turn."""
    from coding_agent.addons.voice import VoiceAddon

    agent = app._agent
    harness = getattr(agent, "harness", None)
    if harness is None:
        return ""
    existing = None
    try:
        existing = next((addon for addon in harness.addons if isinstance(addon, VoiceAddon)), None)
        if existing is None:
            def _speaking(speaking: bool) -> None:
                if getattr(app, "_thread_id", None) == __import__("threading").get_ident():
                    _set_voice_border(app, speaking)
                    return
                app.call_from_thread(_set_voice_border, app, speaking)

            existing = VoiceAddon(on_speaking=_speaking)
            harness.register_addon(existing)
        app._voice_addon = existing
        # Open before arming: an unsuccessful startup must not enable speech
        # for the next ordinary text turn.
        error = existing.open()
        if not error:
            existing.arm()
            return ""
    except Exception as exc:
        error = f"Voice mode failed · {exc}"
    app._voice_addon = None
    if existing is not None:
        try:
            existing.close()
        except Exception:
            pass  # Preserve the startup error; the UI must still be restored.
    return error


def feed_voice(app: Any, text: str) -> None:
    """Hand streamed assistant text to the voice add-on, when one is mounted."""
    addon = getattr(app, "_voice_addon", None)
    feed = getattr(addon, "feed", None)
    if callable(feed):
        feed(text)


def close_voice_addon(app: Any) -> None:
    addon = getattr(app, "_voice_addon", None)
    app._voice_addon = None
    try:
        if addon is not None:
            addon.close()
    finally:
        _set_voice_border(app, False)


def _advance_voice_border(app: Any) -> None:
    """Alternate colors while retaining the same border type and geometry."""
    composer = app.query_one("#composer", Composer)
    app._voice_border_light = not getattr(app, "_voice_border_light", True)
    composer.set_class(app._voice_border_light, "voice-light")
    composer.set_class(not app._voice_border_light, "voice-dark")


def _set_voice_border(app: Any, active: bool) -> None:
    """Start a single blink timer, or return border styling to the theme."""
    try:
        composer = app.query_one("#composer", Composer)
    except Exception:
        return
    timer = getattr(app, "_voice_timer", None)
    if active:
        if timer is None:
            app._voice_border_light = True
            composer.set_class(True, "voice-light")
            composer.set_class(False, "voice-dark")
            app._voice_timer = app.set_interval(
                VOICE_BLINK_INTERVAL_S, lambda: _advance_voice_border(app),
            )
        return
    # Realtime/TTS callbacks must not clear a newer capture's indicator.
    if getattr(app, "_voice_active", False):
        return
    if timer is not None:
        timer.stop()
    app._voice_timer = None
    composer.remove_class("voice-light", "voice-dark")
