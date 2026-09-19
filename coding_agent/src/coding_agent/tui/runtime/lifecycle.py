"""Idle-terminal run close for failed, cancelled, and limit-exceeded events."""

from __future__ import annotations

from typing import Any


def apply_idle_terminal(
    state: Any,
    view: Any,
    detail: str,
    thinking: str,
    *,
    collapse: bool = True,
    notice: str | None = None,
    tone: str = "info",
) -> None:
    """Park the run in idle and show the matching thinking + process close."""
    state.phase = "idle"
    state.detail = detail
    view.set_thinking(thinking)
    if notice:
        view.add_notice(notice, tone)
    view.finish_process(thinking, collapse=collapse)
