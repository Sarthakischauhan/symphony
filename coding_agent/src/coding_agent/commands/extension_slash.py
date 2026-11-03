"""``/skills`` and ``/plugins`` in a running session: the same parsers as the shell commands.

Fetching from git is slow and blocking, so the command runs in a worker thread. When it
changed something, the agent re-reads plugins and skills and refreshes its prompt.
"""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Protocol

from coding_agent.commands import plugins_cli, skills_cli
from coding_agent.commands.cli_support import Context, Outcome

COMMANDS = frozenset({"skills", "plugins"})


class Reloadable(Protocol):
    def reload_extensions(self) -> str: ...


async def run_extension_slash(command: str, argument: str, workspace: Path, agent: Reloadable | None) -> Outcome:
    """Run ``/skills ...`` or ``/plugins ...``; an empty argument lists."""
    runner = skills_cli.run if command == "skills" else plugins_cli.run
    try:
        argv = shlex.split(argument) or ["list"]
    except ValueError as exc:
        return Outcome(f"error: {exc}", ok=False)
    outcome = await asyncio.to_thread(runner, argv, Context(workspace, workspace))
    if outcome.changed and agent is not None:
        reloaded = agent.reload_extensions()
        return Outcome(f"{outcome.text}\n{reloaded}".rstrip(), changed=True)
    return outcome


__all__ = ["COMMANDS", "run_extension_slash"]
