"""The notice shown after /reload swaps user addons."""

from __future__ import annotations

from typing import Collection


def tool_change_notice(before: Collection[str], after: Collection[str]) -> str:
    added = len(set(after) - set(before))
    removed = len(set(before) - set(after))
    if not added and not removed:
        return "no tool changes"
    return f"tools changed (+{added}/-{removed}): prompt cache will rebuild"


__all__ = ["tool_change_notice"]
