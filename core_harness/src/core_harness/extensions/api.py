"""The surface an addon's ``setup(api)`` receives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, Union

from core_harness.extensions.events import AddonEvent, EventHandler
from core_harness.tools import Tool

ToolSpec = Tool
"""Addon tools are ordinary harness ``Tool`` objects."""

CommandHandler = Callable[[str], Union[str, Awaitable[str]]]
"""Receives the text after ``/name`` and returns the reply to show."""


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    handler: CommandHandler
    argument: str = ""


class ExtensionAPI(Protocol):
    def register_tool(self, tool: ToolSpec) -> None: ...

    def register_command(self, command: CommandSpec) -> None: ...

    def on(self, event: Union[str, AddonEvent], handler: EventHandler) -> Callable[[], None]:
        """Subscribe to one event. Returns a callable that unsubscribes."""
        ...


__all__ = ["CommandHandler", "CommandSpec", "ExtensionAPI", "ToolSpec"]
