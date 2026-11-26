"""Immutable record of what the loaded addons registered."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Callable, Optional

from core_harness.extensions.api import CommandSpec, ToolSpec
from core_harness.extensions.events import EventHandler


@dataclass(eq=False)
class Subscription:
    """One ``api.on`` registration. ``active`` turns off when unsubscribed."""

    event: str
    handler: EventHandler
    active: bool = True

    def cancel(self) -> None:
        self.active = False


@dataclass(frozen=True)
class LoadedAddon:
    name: str
    version: str
    root: Path
    tools: tuple[ToolSpec, ...] = ()
    commands: tuple[CommandSpec, ...] = ()
    subscriptions: tuple[Subscription, ...] = ()
    dispose: Optional[Callable[[], object]] = None


@dataclass(frozen=True)
class AddonFailure:
    """Why one addon was skipped. ``phase`` is manifest, import, setup, register, hook or dispose."""

    name: str
    phase: str
    error: str


@dataclass(frozen=True)
class ExtensionSnapshot:
    loaded: tuple[LoadedAddon, ...] = ()
    failed: tuple[AddonFailure, ...] = ()
    notices: tuple[str, ...] = field(default=())

    @property
    def tools(self) -> tuple[ToolSpec, ...]:
        return tuple(tool for addon in self.loaded for tool in addon.tools)

    @property
    def commands(self) -> tuple[CommandSpec, ...]:
        return tuple(command for addon in self.loaded for command in addon.commands)

    @cached_property
    def _subscriptions_by_event(self) -> dict[str, list[tuple[str, Subscription]]]:
        by_event: dict[str, list[tuple[str, Subscription]]] = {}
        for addon in self.loaded:
            for subscription in addon.subscriptions:
                by_event.setdefault(subscription.event, []).append((addon.name, subscription))
        return by_event

    @property
    def tool_names(self) -> frozenset[str]:
        return frozenset(tool.name for tool in self.tools)


EMPTY_SNAPSHOT = ExtensionSnapshot()

__all__ = ["EMPTY_SNAPSHOT", "AddonFailure", "ExtensionSnapshot", "LoadedAddon", "Subscription"]
