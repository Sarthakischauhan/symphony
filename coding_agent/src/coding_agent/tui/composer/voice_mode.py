"""Enter and leave voice mode without disturbing an in-flight turn.

Listening runs off the UI thread. The bar timer only advances the one-line
gradient, so the transcript is not relaid out while the user is talking.
"""

from __future__ import annotations

from typing import Any

from coding_agent.credentials import OFFLINE_HINT
from coding_agent.tui.composer.input import Composer, PromptInput, QueuedTurn
from coding_agent.tui.composer.voice import (
    GROK_VOICE_MODEL,
    GrokVoiceTranscriber,
    MicrophoneCapture,
    SWEEP_INTERVAL_S,
    UnavailableVoice,
    VoiceBar,
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
    """Hide the composer and listen for one utterance."""
    # A cancelled thread can still finish. Bind both dependencies and a unique
    # session token now, not when the worker eventually starts running.
    session = object()
    app._voice_session = session
    app._voice_active = True
    try:
        app._voice_capture = capture if capture is not None else MicrophoneCapture()
        app._voice_transcriber = transcriber if transcriber is not None else GrokVoiceTranscriber()
        composer = app.query_one("#composer", Composer)
        composer.display = False
        bar = app.query_one("#voice-bar", VoiceBar)
        bar.reset()
        bar.display = True
        app._voice_timer = app.set_interval(SWEEP_INTERVAL_S, bar.advance)
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
    go through ``call_from_thread`` so the bar and the composer are only
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
    # Leave the bar and the hidden composer in place. Restoring the composer
    # here and hiding it again when speech starts is the flicker.
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
    """Show the composer once. Used when voice mode ends without a turn."""
    timer = getattr(app, "_voice_timer", None)
    if timer is not None:
        timer.stop()
    app._voice_timer = None
    bar = app.query_one("#voice-bar", VoiceBar)
    bar.display = False
    bar.reset()
    composer = app.query_one("#composer", Composer)
    if not composer.display:
        composer.display = True
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
                    _set_voice_bar(app, speaking)
                    return
                app.call_from_thread(_set_voice_bar, app, speaking)

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
        _set_voice_bar(app, False)


def _set_voice_bar(app: Any, speaking: bool) -> None:
    """Sweep while the final answer is spoken, then show the composer once.

    The composer is not touched on the way up. Showing it only when speech
    ends means it cannot flicker against the bar during the run.
    """
    try:
        bar = app.query_one("#voice-bar", VoiceBar)
    except Exception:
        return
    timer = getattr(app, "_voice_timer", None)
    if speaking:
        if not bar.display:
            bar.display = True
        if timer is None:
            app._voice_timer = app.set_interval(SWEEP_INTERVAL_S, bar.advance)
        return
    # Speech ended. The composer stays hidden until this one transition.
    if timer is not None:
        timer.stop()
    app._voice_timer = None
    if bar.display:
        bar.display = False
        bar.reset()
    composer = app.query_one("#composer", Composer)
    if composer.display:
        return
    _restore_composer(app)
