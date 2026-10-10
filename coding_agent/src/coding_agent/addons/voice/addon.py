"""Harness hook that speaks the model's own text while the run is going.

There is no canned line. ``feed`` is called with the assistant text as it
streams, and a TTS socket speaks each finished sentence immediately. ``after_run``
only flushes the tail and closes the mic socket.
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
    ) -> None:
        self.stream = stream or VoiceStream(on_speaking=on_speaking)
        self._open = False
        self._speaker: StreamingSpeaker | None = None
        self._started_speech = False
        self._armed = False
        self._playback: StreamingSpeaker | None = None

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

    def close(self) -> None:
        self._armed = False
        for speaker in (self._speaker, self._playback):
            if speaker is not None:
                speaker.close()
        self._speaker = None
        self._playback = None
        if self._open:
            self.stream.close()
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
            self.stream.hold()
            if self._open:
                self.stream.close()
            self._open = False
            return
        from coding_agent.tui.composer.voice import spoken_summary

        text = spoken_summary(str(getattr(result, "output_text", "") or ""))
        speaker = self._speaker
        self._speaker = None
        if text:
            if speaker is None:
                speaker = StreamingSpeaker(on_speaking=getattr(self.stream, "_on_speaking", None))
            speaker.finish(text)
        elif speaker is not None:
            speaker.close()
            speaker = None
        self._playback = speaker
        self.stream.hold()
        # The TTS tail must finish naturally. Explicit close cancels playback.
        if self._open:
            self.stream.close()
        self._open = False
