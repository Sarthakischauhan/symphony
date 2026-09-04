"""Harness add-on that reflects on a completed run."""

from __future__ import annotations

from typing import Any, Callable, Optional

from core_harness.addons import Addon

from coding_agent.learning.loop import LearningLoop


class LearningAddon(Addon):
    """Schedule post-run reflection from the harness ``after_run`` hook.

    Children do not inherit this add-on. Plan-mode runs can skip review via
    ``should_review``.
    """

    name = "learning"

    def __init__(
        self,
        loop: LearningLoop,
        *,
        should_review: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.loop = loop
        self.should_review = should_review or (lambda: True)

    def fork_for_child(self, parent_harness: Any) -> None:
        del parent_harness
        return None

    async def after_run(self, **payload: Any) -> None:
        if not self.should_review():
            return
        result = payload.get("result")
        if result is None:
            return
        self.loop.schedule(
            str(payload.get("task") or ""),
            result,
            emit=payload.get("emit"),
        )
