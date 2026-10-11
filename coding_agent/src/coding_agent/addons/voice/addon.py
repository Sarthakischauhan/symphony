"""Harness hook that speaks the summary on its own short realtime socket.

``feed`` keeps nothing: streamed assistant text is not dictated. The listen
socket closes after its acknowledgement. ``after_run`` opens a mic-less
socket, speaks only the spoken-summary section, and that socket closes when
the line has played. There is no TTS connection.
"""

from __future__ import annotations

from typing import Any

from core_harness.addons.addon import Addon

from coding_agent.addons.voice.stream import VoiceStream


class VoiceAddon(Addon):
    """Speak around a run without joining the chat model call."""

    name = "voice"

    def __init__(
        self,
        stream: VoiceStream | None = None,
        *,
        on_speaking: Any = None,
        on_transcript: Any = None,
        on_commit: Any = None,
    ) -> None:
        self.stream = stream or VoiceStream(
            on_speaking=on_speaking, on_transcript=on_transcript, on_commit=on_commit,
        )
        self._open = False
        self._started_speech = False
        self._armed = False

    def arm(self) -> None:
        """Opt in exactly one microphone-originated run; typed runs stay silent."""
        self._armed = True
        self._started_speech = False

    def fork_for_child(self, parent_harness: Any) -> None:
        return None

    def attach(self, harness: Any) -> None:
        del harness
        return None

    def open(self) -> str:
        """Start the background stream. Returns an error string, or ``""``.

        A finished utterance closes its own socket, so the next listen starts
        a new one instead of talking to a dead connection.
        """
        if self._open and not getattr(self.stream, "alive", True):
            self._open = False
        if not self._open:
            self.stream.start()
            self._open = True
        return self.stream.error

    def close(self, *, timeout: float = 0.0) -> None:
        """Stop the speech-to-speech socket. Waits up to ``timeout`` for its thread."""
        self._armed = False
        if self._open:
            self.stream.close(timeout=timeout)
        self._open = False

    def feed(self, text: str) -> None:
        """Keep the latest assistant text. Speech waits for the final answer."""
        del text
        return None

    async def before_run(self, **payload: Any) -> None:
        """Keep the mic quiet while the run goes. Do not speak a fixed line."""
        del payload
        if self._armed:
            self.stream.hold()

    async def after_run(self, **payload: Any) -> None:
        if not self._armed:
            return
        self._armed = False
        result = payload.get("result")
        # Only a question that arrived by voice is dictated. The flag lives on
        # the harness for the run and is copied onto its result.
        if not bool(getattr(result, "reply_aloud", False)):
            # A typed turn never speaks. The listen socket, if one is up,
            # hangs up with the acknowledgement and is not held open here.
            return
        from coding_agent.tui.composer.voice import spoken_summary

        text = spoken_summary(str(getattr(result, "output_text", "") or ""))
        if not text:
            return
        # The summary is its own short connection and does not open the mic.
        # The listen socket already closed after the acknowledgement. say()
        # queues the line first so a session that is still connecting speaks
        # it instead of dropping it. That socket closes when the audio ends.
        self.stream.say(text)
        if not getattr(self.stream, "alive", True):
            self._open = False
            self.stream.start(speak_only=True)
            self._open = True
