"""Strings the caller already supplied in the goal. Jev may choose one; it cannot invent one."""

from __future__ import annotations

import re

_LEAD = re.compile(
    r"(?:search(?:\s+for)?|type|enter|query|look up|fill in)\s+(.+?)(?:\s+and\s+|\s+then\s+|[,.]|$)",
    re.IGNORECASE,
)
_QUOTED = re.compile(r'"([^"]{1,80})"|\'([^\']{1,80})\'')


def text_candidates(goal: str) -> list[str]:
    """The "search for …" phrase first, then quoted strings, at most eight."""
    found: list[str] = []
    for match in _QUOTED.finditer(goal):
        text = (match.group(1) or match.group(2) or "").strip()
        if text and text not in found:
            found.append(text)
    lead = _LEAD.search(goal)
    if lead:
        text = lead.group(1).strip(" \"'")
        if text and text not in found:
            found.insert(0, text)
    return found[:8]


__all__ = ["text_candidates"]
