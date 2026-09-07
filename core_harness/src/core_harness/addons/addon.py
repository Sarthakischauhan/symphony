"""Attachable harness extensions.

Subclass :class:`Addon` and override hooks to opt in.
"""

from __future__ import annotations

from typing import Any, Optional


class Addon:
    """Harness extension. Hooks are no-ops until overridden.

    Inherit on spawn by implementing :meth:`fork_for_child`. The default
    returns ``None``, so children do not receive this instance.
    """

    name: str = ""

    def attach(self, harness: Any) -> None:
        """Mount this add-on onto a harness. Called once from ``register_addon``."""
        del harness
        return None

    def fork_for_child(self, parent_harness: Any) -> Optional[Addon]:
        """Return a child-specific instance, or ``None`` to skip inherit."""
        del parent_harness
        return None

    async def before_run(self, **payload: Any) -> None:
        del payload
        return None

    async def before_turn(self, **payload: Any) -> None:
        del payload
        return None

    async def before_tool(self, **payload: Any) -> Optional[str]:
        """Return a deny reason to skip the tool, or ``None`` to allow it."""
        del payload
        return None

    async def after_turn(self, **payload: Any) -> None:
        del payload
        return None

    async def after_run(self, **payload: Any) -> None:
        """Called after a successful run, before ``CoreHarness.run`` returns."""
        del payload
        return None

    async def on_tool(self, **payload: Any) -> None:
        del payload
        return None

    async def on_compact(self, **payload: Any) -> None:
        del payload
        return None


__all__ = ["Addon"]
