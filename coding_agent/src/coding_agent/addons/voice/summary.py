"""Split the "## Spoken summary" section off a reply and clean it for TTS."""

from __future__ import annotations

# Spoken replies stay short so a long tool report is not read in full.
SPOKEN_REPLY_LIMIT = 600


_SPOKEN_SUMMARY = "## Spoken summary"


def split_spoken_summary(text: str) -> tuple[str, str]:
    """Separate the chat answer from the trailing spoken section.

    The heading is only for TTS. A heading that is still being typed stays
    out of the chat as well, so the customer never sees it appear.
    """
    lowered = text.lower()
    marker = lowered.rfind(_SPOKEN_SUMMARY.lower())
    if marker < 0:
        partial = _partial_heading(lowered)
        if partial:
            return text[: len(text) - partial].rstrip(), ""
        return text, ""
    return text[:marker].rstrip(), text[marker + len(_SPOKEN_SUMMARY):].strip()


def _partial_heading(lowered: str) -> int:
    """How many trailing characters are an unfinished ``## Spoken summary``."""
    heading = _SPOKEN_SUMMARY.lower()
    tail = lowered.rstrip()
    trimmed = len(lowered) - len(tail)
    for size in range(min(len(heading) - 1, len(tail)), 1, -1):
        if tail.endswith(heading[:size]):
            return size + trimmed
    return 0


class SpokenSummaryStream:
    """``split_spoken_summary(text)[0]`` for one reply that only grows.

    The presenter asks for the visible text on every streamed delta. Lowering
    and searching the whole reply each time made a reply O(n^2). This keeps
    the last heading position and searches only the characters added since
    the previous call, plus enough overlap for a heading split across deltas.
    A text shorter than the last one is a restarted reply and starts over.
    """

    _HEADING = _SPOKEN_SUMMARY.lower()

    def __init__(self) -> None:
        self._scanned = 0
        self._marker = -1
        self._before_marker = ""
        # ``str.lower`` can lengthen a character (U+0130). Positions in the
        # lowered window then stop matching the original text, so such a
        # reply falls back to the whole-text split.
        self._aligned = True

    def visible(self, text: str) -> str:
        if len(text) < self._scanned:
            self.__init__()
        added = text[self._scanned:]
        if self._aligned and len(added.lower()) != len(added):
            self._aligned = False
        if not self._aligned:
            self._scanned = len(text)
            return split_spoken_summary(text)[0]
        start = max(0, self._scanned - (len(self._HEADING) - 1))
        found = text[start:].lower().rfind(self._HEADING)
        self._scanned = len(text)
        if found >= 0:
            # Any match in the window ends past the old one, so it is the last.
            self._marker = start + found
            self._before_marker = text[: self._marker].rstrip()
        if self._marker >= 0:
            return self._before_marker
        partial = _partial_heading(self._tail(text).lower())
        if partial:
            return text[: len(text) - partial].rstrip()
        return text

    def _tail(self, text: str) -> str:
        """The trailing whitespace plus the heading-length run before it."""
        size = 32
        while True:
            window = text[-size:]
            stripped = window.rstrip()
            if stripped or size >= len(text):
                break
            size *= 2
        trailing = len(window) - len(stripped)
        return text[-(trailing + len(self._HEADING) - 1):]



def spoken_summary(text: str, *, limit: int = SPOKEN_REPLY_LIMIT) -> str:
    """The summary the model wrote into its final answer, ready for TTS.

    The section is part of the same response, not a later call. If the model
    left it out, nothing is spoken: reading the answer aloud would dictate
    the whole output.
    """
    _answer, section = split_spoken_summary(text)
    if not section:
        return ""
    return spoken_text(section, limit=limit)


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
