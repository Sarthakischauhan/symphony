"""Plain-text body of the /addons command (TUI and stdio)."""

from __future__ import annotations

from core_harness.extensions import AddonFailure

from coding_agent.extensions.bridge import AddonSurface


def addons_report(surface: AddonSurface, hook_failures: tuple[AddonFailure, ...] = ()) -> str:
    exposed_tools = surface.tool_names
    exposed_commands = {item.name for item in surface.commands}
    lines = ["Loaded addons:"]
    for addon in surface.snapshot.loaded:
        tools = ", ".join(tool.name for tool in addon.tools if tool.name in exposed_tools) or "none"
        commands = ", ".join(
            f"/{item.name}" for item in addon.commands if item.name in exposed_commands
        ) or "none"
        lines.append(f"  {addon.name} {addon.version} · tools: {tools} · commands: {commands}")
    if not surface.snapshot.loaded:
        lines.append("  none")
    failures = surface.snapshot.failed + hook_failures
    lines.append("Failed addons:")
    lines.extend(f"  {item.name} · {item.phase} · {item.error}" for item in failures)
    if not failures:
        lines.append("  none")
    if surface.notices:
        lines.append("Notices:")
        lines.extend(f"  {notice}" for notice in surface.notices)
    return "\n".join(lines)


__all__ = ["addons_report"]
