"""Enter and leave voice mode without disturbing an in-flight turn.

Listening runs off the UI thread. A 0.5-second timer alternates the existing
composer border color without hiding or resizing the input.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional

from core_harness import CoreHarness

from coding_agent.addons.voice.credentials import UnavailableVoice
from coding_agent.config.credentials import OFFLINE_HINT
from coding_agent.tui.composer.input import Composer, PromptInput, QueuedTurn
from coding_agent.tui.composer.voice import (
    GROK_VOICE_MODEL,
    GrokVoiceTranscriber,
    MicrophoneCapture,
    VOICE_BLINK_INTERVAL_S,
    VoiceCapture,
    VoiceTranscriber,
)

if TYPE_CHECKING:
    from coding_agent.tui.app import CodingAgentApp


@dataclass(eq=False)
class VoiceSession:
    """One listening session. Its identity tells a stale worker it lost."""

    capture: VoiceCapture


def toggle_voice(app: CodingAgentApp) -> None:
    """Start voice mode, or stop listening and submit what was heard."""
    if app._voice_active:
        commit_voice(app)
        return
    if app._agent is None and not _uses_clip_path():
        app.add_notice(OFFLINE_HINT, "error")
        return
    start_voice(app)


def start_voice(
    app: CodingAgentApp,
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


def _on_live_transcript(app: CodingAgentApp, text: str) -> None:
    """Paint a transcript delta. Called from the socket thread.

    The final transcript can land after the commit decision. Keep it, but do
    not repaint the composer once the turn has taken the text.
    """
    app._voice_text = text
    if not app._voice_active or app._voice_finish:
        return
    _post(app, _show_voice_transcript, app, text)


def _post(app: CodingAgentApp, callback: Callable[..., None], *args: Any) -> None:
    """Run on the UI thread. A callback already there runs directly."""
    if app._thread_id == threading.get_ident():
        callback(*args)
        return
    app.call_from_thread(callback, *args)


def _on_live_commit(app: CodingAgentApp) -> None:
    """The utterance ended (3 s pause or Enter). Submit the latest transcript."""
    if app._voice_finish or not app._voice_active:
        return
    app._voice_finish = True
    _post(app, _finish_live, app)


def _finish_live(app: CodingAgentApp) -> None:
    """Submit on the UI thread, reading the transcript after pending deltas."""
    if not app._voice_active:
        return
    _finish_voice(app, app._voice_text.strip(), "")


def _start_clip_session(
    app: CodingAgentApp, capture: VoiceCapture | None, transcriber: VoiceTranscriber | None,
) -> None:
    """Test path: one local recording, then the scripted transcript."""
    import coding_agent.tui.composer.voice as voice

    live_capture = capture if capture is not None else voice.MicrophoneCapture()
    live_transcriber = transcriber if transcriber is not None else voice.GrokVoiceTranscriber()
    app._voice_capture = live_capture
    session = VoiceSession(live_capture)
    app._voice_session = session
    app._voice_transcriber = live_transcriber
    app.run_worker(
        lambda: _listen(app, live_capture, live_transcriber, session),
        exclusive=True, group="voice", thread=True,
    )


def _abort_voice(app: CodingAgentApp, error: str) -> None:
    app._voice_active = False
    app._voice_session = None
    try:
        close_voice_addon(app)
    except Exception:
        pass
    _restore_composer(app)
    app.add_notice(error, "error")


def commit_voice(app: CodingAgentApp) -> None:
    """Enter or Ctrl+A ends the utterance now instead of waiting out the pause."""
    if not app._voice_active or app._voice_finish:
        return
    if app._voice_session is not None:
        stop_voice(app, reason="done")
        return
    addon = app._voice_addon
    if addon is not None:
        # Explicit Enter submits locally immediately; the transport callback
        # may arrive later, after its listen socket has already closed.
        from coding_agent.tui.composer.input import PromptInput

        transcript = app._voice_text.strip()
        try:
            transcript = app.query_one("#prompt", PromptInput).text.strip() or transcript
        except Exception:
            pass
        app._voice_finish = True
        _finish_voice(app, transcript, "")
        addon.stream.commit()
        return
    app._voice_finish = True
    _finish_voice(app, app._voice_text.strip(), "")


def stop_voice(app: CodingAgentApp, *, reason: str) -> None:
    """Leave voice mode. ``done`` submits the transcript; anything else discards it."""
    session = app._voice_session
    if reason == "done" and app._voice_active:
        # Submit the utterances already transcribed. The worker may be blocked
        # in another listen(); it must not append that clip after this.
        app._voice_finish = True
        text = " ".join(app._voice_parts).strip() or app._voice_text.strip()
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
    app: CodingAgentApp, capture: VoiceCapture, transcriber: VoiceTranscriber, session: VoiceSession,
) -> None:
    """Keep capturing until the user says done or presses Ctrl+A.

    Textual runs a ``thread=True`` worker as a plain function. Widget updates
    go through ``call_from_thread`` so the composer styles are only
    touched on the app thread. Each ``listen`` returns one utterance; the
    loop continues so voice mode does not submit on the first pause.
    """
    parts: list[str] = []
    while app._voice_active and app._voice_session is session:
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
        if not app._voice_active or app._voice_session is not session:
            return
        # Ctrl+A already submitted the remembered parts. Drop this clip.
        if app._voice_finish:
            return
        if text and not _is_done_phrase(text):
            parts.append(text)
            app.call_from_thread(_remember_voice_part, app, text, session)
        if _is_done_phrase(text):
            app.call_from_thread(_finish_voice, app, " ".join(parts).strip(), "", session)
            return


def _remember_voice_part(app: CodingAgentApp, text: str, session: VoiceSession) -> None:
    """Keep an utterance for Ctrl+A without starting the agent yet."""
    if not app._voice_active or app._voice_session is not session:
        return
    if app._voice_finish:
        return
    app._voice_parts.append(text)
    _show_voice_transcript(app, " ".join(app._voice_parts))


def _finish_voice(app: CodingAgentApp, text: str, error: str, session: VoiceSession | None = None) -> None:
    if not app._voice_active:
        return
    if session is not None and app._voice_session is not session:
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


def _show_voice_transcript(app: CodingAgentApp, text: str) -> None:
    """Put the words heard so far into the composer. The turn has not started."""
    try:
        prompt = app.query_one("#prompt", PromptInput)
    except Exception:
        return
    prompt.disabled = False
    prompt.value = text
    prompt.cursor_position = len(text)


def _restore_composer(app: CodingAgentApp) -> None:
    """Clear voice styling and restore input focus after cancellation/error."""
    _set_voice_border(app, False)
    prompt = app.query_one("#prompt", PromptInput)
    prompt.disabled = False
    prompt.focus()
    app._set_status("")


def submit_voice_turn(app: CodingAgentApp, text: str) -> None:
    """Hand a transcript to the composer path and arm the voice hooks."""
    if app._agent is None:
        _restore_composer(app)
        app.add_notice(OFFLINE_HINT, "error")
        return
    harness: Optional[CoreHarness] = app._agent.harness
    if app._voice_addon is not None and harness is None:
        error = ""
    else:
        error = ensure_voice_addon(app)
    if error:
        _restore_composer(app)
        app.add_notice(error, "error")
        return
    # A live voice turn reuses the existing addon/stream; only arm it for the
    # run. Do not reopen the stream (which closes test/host transports).
    if app._voice_addon is not None:
        app._voice_addon.arm()
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
    app: CodingAgentApp, *, stream: Any = None, on_transcript: Any = None, on_commit: Any = None,
) -> str:
    """Reuse the voice add-on and open its realtime socket for this listen."""
    from coding_agent.addons.voice import VoiceAddon

    harness: Optional[CoreHarness] = app._agent.harness if app._agent is not None else None
    if harness is None:
        if stream is None:
            return ""
        if on_transcript is not None:
            stream._on_transcript = on_transcript
        if on_commit is not None:
            stream._on_commit = on_commit
        # Allow an explicitly injected stream for host integrations and tests
        # that provide their own voice transport without a harness.
        existing = VoiceAddon(
            stream=stream,
            on_transcript=on_transcript,
            on_commit=on_commit,
        )
        app._voice_addon = existing
        error = existing.open()
        if not error:
            existing.arm()
            return ""
        app._voice_addon = None
        existing.close()
        return error
    existing = None
    try:
        existing = next((addon for addon in harness.addons if isinstance(addon, VoiceAddon)), None)
        if existing is None:
            def _speaking(speaking: bool) -> None:
                if app._thread_id == threading.get_ident():
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
        if on_transcript is not None:
            existing.stream._on_transcript = on_transcript
        if on_commit is not None:
            existing.stream._on_commit = on_commit
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


def feed_voice(app: CodingAgentApp, text: str) -> None:
    """Hand streamed assistant text to the voice add-on, when one is mounted."""
    if app._voice_addon is not None:
        app._voice_addon.feed(text)


def close_voice_addon(app: CodingAgentApp, *, timeout: float = 0.0) -> None:
    """Stop speech and the realtime socket without blocking the caller.

    ``timeout`` waits that long for the audio threads to exit; only app
    shutdown asks for it.
    """
    addon = app._voice_addon
    app._voice_addon = None
    try:
        if addon is not None:
            addon.close(timeout=timeout)
    finally:
        _set_voice_border(app, False)


def _advance_voice_border(app: CodingAgentApp) -> None:
    """Alternate colors while retaining the same border type and geometry."""
    composer = app.query_one("#composer", Composer)
    app._voice_border_light = not app._voice_border_light
    composer.set_class(app._voice_border_light, "voice-light")
    composer.set_class(not app._voice_border_light, "voice-dark")


def _set_voice_border(app: CodingAgentApp, active: bool) -> None:
    """Start a single blink timer, or return border styling to the theme."""
    try:
        composer = app.query_one("#composer", Composer)
    except Exception:
        return
    timer = app._voice_timer
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
    if app._voice_active:
        return
    if timer is not None:
        timer.stop()
    app._voice_timer = None
    composer.remove_class("voice-light", "voice-dark")
