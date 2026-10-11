"""Harness hook that speaks on the same speech-to-speech socket.

``feed`` keeps nothing: streamed assistant text is not dictated. ``after_run``
speaks only the spoken-summary section, through the realtime socket that
already acknowledged the user. There is no second TTS connection.
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
        """Start the background stream. Returns an error string, or ``""``."""
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
            # Typed turns stay silent, but the socket stays up for the next
            # voice question. Closing it here made the following turn reopen.
            self.stream.hold()
            return
        from coding_agent.tui.composer.voice import spoken_summary

        text = spoken_summary(str(getattr(result, "output_text", "") or ""))
        # Same socket that heard the user. The spoken line is the summary,
        # not the chat answer, and no TTS socket is opened for it.
        if text:
            self.stream.hold()
            self.stream.say(text)
            return
        self.stream.hold()
        if self._open:
            self.stream.close()
        self._open = False
