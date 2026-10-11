"""Enter and leave voice mode without disturbing an in-flight turn.

Listening runs off the UI thread. A 0.5-second timer alternates the existing
composer border color without hiding or resizing the input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from coding_agent.config.credentials import OFFLINE_HINT
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


@dataclass(eq=False)
class VoiceSession:
    """One listening session. Its identity tells a stale worker it lost."""

    capture: VoiceCapture


def toggle_voice(app: Any) -> None:
    """Start voice mode, or stop listening and submit what was heard."""
    if getattr(app, "_voice_active", False):
        commit_voice(app)
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
    stream: Any = None,
) -> None:
    """Listen on the realtime socket until a 3 s pause or Enter.

    Partial transcripts are painted as they arrive. ``capture`` and
    ``transcriber`` remain for tests of the older utterance recorder; a live
    session does not record a clip and then upload it.
    """
    app._voice_active = True
    app._voice_parts = []
    app._voice_text = ""
    app._voice_finish = False
    try:
        _set_voice_border(app, True)
        app.add_notice(
            "Voice mode · listening. A 3 second pause or Enter runs it. Esc cancels.",
        )
        # An explicit or patched recorder is the local clip path (tests). A
        # live session passes neither and listens on the realtime socket.
        if capture is not None or transcriber is not None or _uses_clip_path():
            _start_clip_session(app, capture, transcriber)
            return
        error = ensure_voice_addon(
            app,
            stream=stream,
            on_transcript=lambda text: _on_live_transcript(app, text),
            on_commit=lambda: _on_live_commit(app),
        )
        if error:
            _abort_voice(app, error)
    except Exception as exc:
        _abort_voice(app, f"Voice mode failed · {exc}")


def _uses_clip_path() -> bool:
    """True when a test replaced the recorder, here or on the voice module.

    ``/voice`` calls this function. A patch of the names above is invisible
    to it unless the lookup happens at call time.
    """
    import coding_agent.tui.composer.voice as voice

    return (
        voice.MicrophoneCapture is not _CLIP_CAPTURE
        or voice.GrokVoiceTranscriber is not _CLIP_TRANSCRIBER
    )


_CLIP_CAPTURE = MicrophoneCapture
_CLIP_TRANSCRIBER = GrokVoiceTranscriber


def _on_live_transcript(app: Any, text: str) -> None:
    """Paint a transcript delta. Called from the socket thread.

    The final transcript can land after the commit decision. Keep it, but do
    not repaint the composer once the turn has taken the text.
    """
    app._voice_text = text
    if not getattr(app, "_voice_active", False) or getattr(app, "_voice_finish", False):
        return
    _post(app, _show_voice_transcript, app, text)


def _post(app: Any, callback: Any, *args: Any) -> None:
    """Run on the UI thread. A callback already there runs directly."""
    import threading

    if getattr(app, "_thread_id", None) == threading.get_ident():
        callback(*args)
        return
    app.call_from_thread(callback, *args)


def _on_live_commit(app: Any) -> None:
    """The utterance ended (3 s pause or Enter). Submit the latest transcript."""
    if getattr(app, "_voice_finish", False) or not getattr(app, "_voice_active", False):
        return
    app._voice_finish = True
    _post(app, _finish_live, app)


def _finish_live(app: Any) -> None:
    """Submit on the UI thread, reading the transcript after pending deltas."""
    if not getattr(app, "_voice_active", False):
        return
    text = str(getattr(app, "_voice_text", "") or "").strip()
    _finish_voice(app, text, "")


def _start_clip_session(
    app: Any, capture: VoiceCapture | None, transcriber: VoiceTranscriber | None,
) -> None:
    """Test path: one local recording, then the scripted transcript."""
    import coding_agent.tui.composer.voice as voice

    app._voice_capture = capture if capture is not None else voice.MicrophoneCapture()
    session = VoiceSession(app._voice_capture)
    app._voice_session = session
    app._voice_transcriber = transcriber if transcriber is not None else voice.GrokVoiceTranscriber()
    app.run_worker(
        lambda: _listen(app, app._voice_capture, app._voice_transcriber, session),
        exclusive=True, group="voice", thread=True,
    )


def _abort_voice(app: Any, error: str) -> None:
    app._voice_active = False
    app._voice_session = None
    try:
        close_voice_addon(app)
    except Exception:
        pass
    _restore_composer(app)
    app.add_notice(error, "error")


def commit_voice(app: Any) -> None:
    """Enter or Ctrl+A ends the utterance now instead of waiting out the pause."""
    if not getattr(app, "_voice_active", False) or getattr(app, "_voice_finish", False):
        return
    if getattr(app, "_voice_session", None) is not None:
        stop_voice(app, reason="done")
        return
    addon = getattr(app, "_voice_addon", None)
    commit = getattr(getattr(addon, "stream", None), "commit", None)
    if callable(commit):
        commit()
        return
    app._voice_finish = True
    _finish_voice(app, str(getattr(app, "_voice_text", "") or "").strip(), "")


def stop_voice(app: Any, *, reason: str) -> None:
    """Leave voice mode. ``done`` submits the transcript; anything else discards it."""
    session = getattr(app, "_voice_session", None)
    if reason == "done" and getattr(app, "_voice_active", False):
        # Submit the utterances already transcribed. The worker may be blocked
        # in another listen(); it must not append that clip after this.
        app._voice_finish = True
        parts = list(getattr(app, "_voice_parts", []) or [])
        text = " ".join(parts).strip() or str(getattr(app, "_voice_text", "") or "").strip()
        _finish_voice(app, text, "", session)
        return
    app._voice_active = False
    app._voice_session = None
    app._voice_parts = []
    app._voice_finish = False
    if session is not None:
        # Unblocks the worker's listen() and releases the microphone now,
        # not when the utterance cap runs out.
        session.capture.close()
    try:
        close_voice_addon(app)
    except Exception as exc:
        app.add_notice(f"Voice mode failed · {exc}", "error")
    finally:
        _restore_composer(app)
    if reason == "toggled":
        app.add_notice("Voice mode off.")
    del session


_DONE_WORDS = {"done", "done."}


def _is_done_phrase(text: str) -> bool:
    """True when the utterance is only the word that ends voice mode."""
    return text.strip().lower() in _DONE_WORDS


def _listen(
    app: Any, capture: VoiceCapture, transcriber: VoiceTranscriber, session: VoiceSession,
) -> None:
    """Keep capturing until the user says done or presses Ctrl+A.

    Textual runs a ``thread=True`` worker as a plain function. Widget updates
    go through ``call_from_thread`` so the composer styles are only
    touched on the app thread. Each ``listen`` returns one utterance; the
    loop continues so voice mode does not submit on the first pause.
    """
    parts: list[str] = []
    while getattr(app, "_voice_active", False) and getattr(app, "_voice_session", None) is session:
        try:
            audio = capture.listen()
            if audio is None:
                if app._voice_session is session:
                    app.call_from_thread(_finish_voice, app, " ".join(parts).strip(), "", session)
                return
            text = transcriber.transcribe(audio, model=GROK_VOICE_MODEL).strip()
        except UnavailableVoice as exc:
            app.call_from_thread(_finish_voice, app, "", str(exc), session)
            return
        except Exception as exc:  # noqa: BLE001 - surface any capture/API failure as a notice
            app.call_from_thread(_finish_voice, app, "", f"Voice mode failed · {exc}", session)
            return
        if not getattr(app, "_voice_active", False) or getattr(app, "_voice_session", None) is not session:
            return
        # Ctrl+A already submitted the remembered parts. Drop this clip.
        if getattr(app, "_voice_finish", False):
            return
        if text and not _is_done_phrase(text):
            parts.append(text)
            app.call_from_thread(_remember_voice_part, app, text, session)
        if _is_done_phrase(text):
            app.call_from_thread(_finish_voice, app, " ".join(parts).strip(), "", session)
            return


def _remember_voice_part(app: Any, text: str, session: VoiceSession) -> None:
    """Keep an utterance for Ctrl+A without starting the agent yet."""
    if not getattr(app, "_voice_active", False) or getattr(app, "_voice_session", None) is not session:
        return
    if getattr(app, "_voice_finish", False):
        return
    parts = getattr(app, "_voice_parts", None)
    if parts is None:
        parts = []
        app._voice_parts = parts
    parts.append(text)
    _show_voice_transcript(app, " ".join(parts))


def _finish_voice(app: Any, text: str, error: str, session: VoiceSession | None = None) -> None:
    if not getattr(app, "_voice_active", False):
        return
    if session is not None and getattr(app, "_voice_session", None) is not session:
        return
    # Keep the border blinking through execution and the spoken summary.
    app._voice_active = False
    app._voice_session = None
    if session is not None:
        # Ctrl+A may land while the worker is still inside listen().
        session.capture.close()
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


def _show_voice_transcript(app: Any, text: str) -> None:
    """Put the words heard so far into the composer. The turn has not started."""
    try:
        prompt = app.query_one("#prompt", PromptInput)
    except Exception:
        return
    prompt.disabled = False
    prompt.value = text
    prompt.cursor_position = len(text)


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
    # The transcript was shown while listening. Clear it before the turn
    # mounts its own copy in the conversation.
    _show_voice_transcript(app, "")
    turn = QueuedTurn(text, text, (), (), voice=True)
    # A turn already running keeps this one. It shows in the queue and starts
    # when the current run finishes, the same as a typed message would.
    if app._busy:
        app.queue_turn(turn)
        _restore_composer(app)
        return
    app._start_turn(turn)


def ensure_voice_addon(
    app: Any, *, stream: Any = None, on_transcript: Any = None, on_commit: Any = None,
) -> str:
    """Reuse the voice add-on and open its realtime socket for this listen."""
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

            existing = VoiceAddon(
                stream=stream,
                on_speaking=_speaking,
                on_transcript=on_transcript,
                on_commit=on_commit,
            )
            harness.register_addon(existing)
        # The addon outlives one listen. This session's callbacks replace the
        # previous one's, including when the stream was built before them.
        voice_stream = getattr(existing, "stream", None)
        if voice_stream is not None:
            if on_transcript is not None:
                voice_stream._on_transcript = on_transcript
            if on_commit is not None:
                voice_stream._on_commit = on_commit
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


def close_voice_addon(app: Any, *, timeout: float = 0.0) -> None:
    """Stop speech and the realtime socket without blocking the caller.

    ``timeout`` waits that long for the audio threads to exit; only app
    shutdown asks for it.
    """
    addon = getattr(app, "_voice_addon", None)
    app._voice_addon = None
    try:
        if addon is not None:
            addon.close(timeout=timeout)
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
