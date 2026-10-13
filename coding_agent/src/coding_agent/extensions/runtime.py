"""The live user-addon state of one agent.

Holds the current ``AddonSurface``, forwards sink events to addon
handlers, and runs the /reload swap: build the new snapshot, dispose the
old addons, then swap. A reload asked for during a run waits for the run
to end.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Collection, Mapping

from core_harness.extensions import AddonFailure, dispatch_event, dispose_addons

from coding_agent.extensions.bridge import AddonSurface, build_surface
from coding_agent.extensions.discovery import load_user_addons
from coding_agent.extensions.tool_changes import tool_change_notice

Loader = Callable[[Collection[str]], Any]


class UserAddonRuntime:
    def __init__(
        self,
        *,
        builtin_tool_names: Collection[str],
        reserved_names: Collection[str] = (),
        loader: Loader = load_user_addons,
    ) -> None:
        self.builtin_tool_names = frozenset(builtin_tool_names)
        self.reserved_names = frozenset(reserved_names)
        self.loader = loader
        self.surface: AddonSurface = self.build()
        self.hook_failures: tuple[AddonFailure, ...] = ()
        self.reload_pending = False

    def build(self) -> AddonSurface:
        return build_surface(self.loader(self.reserved_names), builtin_tool_names=self.builtin_tool_names)

    def on_event(self, event: str, payload: Mapping[str, Any]) -> None:
        """Sink listener. Never raises; failures are kept for /addons."""
        failures = dispatch_event(self.surface.snapshot, event, payload)
        if failures:
            self.hook_failures = (self.hook_failures + failures)[-20:]

    def dispose(self) -> tuple[AddonFailure, ...]:
        failures = dispose_addons(self.surface.snapshot.loaded)
        self.hook_failures = (self.hook_failures + failures)[-20:]
        return failures

    def swap(self, surface: AddonSurface) -> str:
        """Dispose the current addons, install ``surface`` and describe the tool change."""
        before = self.surface.tool_names
        self.dispose()
        self.surface = surface
        return tool_change_notice(before, surface.tool_names)

    async def run_command(self, name: str, argument: str) -> str | None:
        """Run an addon command. ``None`` when no addon owns ``name``."""
        command = self.surface.command(name)
        if command is None:
            return None
        try:
            reply = command.handler(argument)
            if inspect.isawaitable(reply):
                reply = await reply
        except Exception as exc:  # noqa: BLE001 - addon code is untrusted
            self.hook_failures = (self.hook_failures + (
                AddonFailure(command.name, "command", f"{type(exc).__name__}: {exc}"),
            ))[-20:]
            return f"/{name} failed · {type(exc).__name__}: {exc}"
        return str(reply)


__all__ = ["UserAddonRuntime"]
