"""The concrete ``ExtensionAPI`` handed to one addon's ``setup``."""

from __future__ import annotations

from typing import Callable, Union

from core_harness.extensions.api import CommandSpec, ToolSpec
from core_harness.extensions.events import ADDON_EVENTS, AddonEvent, EventHandler
from core_harness.extensions.registry import Subscription
from core_harness.events import normalize_event_type
from core_harness.tools import Tool


class AddonRecorder:
    """Collects one addon's registrations; ``loader`` freezes them afterwards."""

    def __init__(self) -> None:
        self.tools: list[ToolSpec] = []
        self.commands: list[CommandSpec] = []
        self.subscriptions: list[Subscription] = []

    def register_tool(self, tool: ToolSpec) -> None:
        if not isinstance(tool, Tool) or not tool.name:
            raise TypeError("register_tool needs a named core_harness Tool")
        if any(existing.name == tool.name for existing in self.tools):
            raise ValueError(f"duplicate tool name: {tool.name!r}")
        self.tools.append(tool)

    def register_command(self, command: CommandSpec) -> None:
        if not isinstance(command, CommandSpec) or not command.name or not callable(command.handler):
            raise TypeError("register_command needs a CommandSpec with a callable handler")
        if any(existing.name == command.name for existing in self.commands):
            raise ValueError(f"duplicate command name: {command.name!r}")
        self.commands.append(command)

    def on(self, event: Union[str, AddonEvent], handler: EventHandler) -> Callable[[], None]:
        name = normalize_event_type(event)
        if name not in ADDON_EVENTS:
            raise ValueError(f"unknown event: {name!r}")
        if not callable(handler):
            raise TypeError("event handler must be callable")
        subscription = Subscription(name, handler)
        self.subscriptions.append(subscription)
        return subscription.cancel


__all__ = ["AddonRecorder"]
