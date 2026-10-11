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
