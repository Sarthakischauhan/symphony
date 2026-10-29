"""One-line text for the approval add-on's ``auto_decision`` events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from coding_agent.tui.transcript.messages import clip_text

QUESTION_PREVIEW = 60


def _field(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def decision_text(payload: Mapping[str, Any]) -> str:
    """``auto-approved bash · unattended``, ``auto-denied bash · rule rm -rf *``,
    ``auto-skipped question · unattended · <question>``."""
    kind = _field(payload, "kind")
    if kind == "ask_user":
        question = clip_text(_field(payload, "question"), QUESTION_PREVIEW)
        return " · ".join(part for part in ("auto-skipped question", "unattended", question) if part)
    tool = _field(payload, "tool") or "tool"
    rule = _field(payload, "rule")
    decision = _field(payload, "decision")
    if decision == "allow":
        return f"auto-approved {tool}" + (f" · {rule}" if rule else "")
    if decision == "deny":
        return f"auto-denied {tool}" + (f" · rule {rule}" if rule else "")
    return f"auto decision · {tool}"


__all__ = ["decision_text"]
