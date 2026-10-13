"""Merge a user-addon snapshot with the built-in tools and commands.

Built-in names always win. A user tool or command that reuses one, or
that another user addon already took, is dropped with a notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Collection

from core_harness import Tool
from core_harness.extensions import CommandSpec, ExtensionSnapshot

from coding_agent.commands.catalog import SLASH_COMMANDS, SlashCommand


@dataclass(frozen=True)
class AddonSurface:
    """What the agent actually exposes from one snapshot."""

    snapshot: ExtensionSnapshot
    tools: tuple[Tool, ...]
    commands: tuple[CommandSpec, ...]
    notices: tuple[str, ...]

    @property
    def tool_names(self) -> frozenset[str]:
        return frozenset(tool.name for tool in self.tools)

    @property
    def slash_commands(self) -> tuple[SlashCommand, ...]:
        return tuple(SlashCommand(item.name, item.description, item.argument) for item in self.commands)

    def command(self, name: str) -> CommandSpec | None:
        for item in self.commands:
            if item.name == name:
                return item
        return None


BUILTIN_COMMAND_NAMES: frozenset[str] = frozenset(
    {item.name for item in SLASH_COMMANDS} | {"exit", "extensions", "plugins", "skills"}
)


def build_surface(
    snapshot: ExtensionSnapshot,
    *,
    builtin_tool_names: Collection[str],
    builtin_command_names: Collection[str] = BUILTIN_COMMAND_NAMES,
) -> AddonSurface:
    notices = list(snapshot.notices)
    tools: list[Tool] = []
    commands: list[CommandSpec] = []
    taken_tools = set(builtin_tool_names)
    taken_commands = set(builtin_command_names)
    for addon in snapshot.loaded:
        for tool in addon.tools:
            if tool.name in taken_tools:
                notices.append(f"addon {addon.name!r}: tool {tool.name!r} is already taken and was not added")
                continue
            taken_tools.add(tool.name)
            tools.append(tool)
        for command in addon.commands:
            if command.name in taken_commands:
                notices.append(f"addon {addon.name!r}: /{command.name} is already taken and was not added")
                continue
            taken_commands.add(command.name)
            commands.append(command)
    return AddonSurface(snapshot, tuple(tools), tuple(commands), tuple(notices))


__all__ = ["BUILTIN_COMMAND_NAMES", "AddonSurface", "build_surface"]
