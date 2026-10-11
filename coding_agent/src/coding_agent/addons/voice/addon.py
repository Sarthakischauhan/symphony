"""Harness hook that speaks the summary through TTS.

``feed`` keeps nothing: streamed assistant text is not dictated. The realtime
socket only listens and speaks the short acknowledgement, then closes.
``after_run`` speaks the spoken-summary section on a TTS socket, which stays
open until that audio finishes.
"""

from __future__ import annotations

from typing import Any

from core_harness.addons.addon import Addon

from coding_agent.addons.voice.speak import StreamingSpeaker
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
        self._speaker: StreamingSpeaker | None = None

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
        """Stop speech and the realtime socket. Waits up to ``timeout``."""
        self._armed = False
        speaker = self._speaker
        self._speaker = None
        if speaker is not None:
            speaker.close(timeout=timeout)
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
        # TTS, not another realtime socket. The realtime model speaks an
        # acknowledgement and then its response.done tears the connection
        # down, which was cutting this line off before it could be heard.
        # The TTS socket stays up until audio.done and plays the MP3 itself.
        speaker = StreamingSpeaker(on_speaking=getattr(self.stream, "_on_speaking", None))
        speaker.finish(text)
        self._speaker = speaker
