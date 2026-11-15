"""``--sandbox``: run this ``symphony`` command again inside the macOS sandbox (Seatbelt).

The sandboxed process can write only the workspace, the Symphony home (sessions, config,
memories), ``~/.symphony/oauth`` (token refresh) and the temp directory. It reads the user's
home only for toolchains, Symphony's own install and keys, user-level skills (``~/.agents``)
and git config. ``--sandbox-github`` also lets it read the GitHub CLI's login (its config and
the keychain), so ``git push`` and ``gh pr create`` work; approval prompts still decide whether
they run. AppleEvents, LaunchServices, ``osascript``, ``open`` and ``launchctl`` are out of
reach either way.

The Symphony home is writable, so a sandboxed command can change ``config.json`` (approval
rules included) for later runs. Hosts that rely on approvals should point ``SYMPHONY_HOME`` at
a directory of their own and write its config before each launch.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import NoReturn, Sequence

from coding_agent.config.config import symphony_dir
from coding_agent.run.seatbelt import SandboxPolicy, sandbox_available

SANDBOX_FLAGS = ("--sandbox", "--sandbox-github")
# Set inside the sandbox, so a sandboxed process never wraps itself again.
SANDBOXED = "SYMPHONY_SANDBOXED"


def sandbox_policy(workspace: Path, *, github: bool, home: Path | None = None) -> SandboxPolicy:
    home = home or Path.home()
    readable = [
        home / ".symphony" / ".env",
        home / ".agents",
        home / ".gitconfig",
        home / ".config" / "git",
        Path(sys.prefix),
        Path(sys.base_prefix),
    ]
    if github:
        readable.append(home / ".config" / "gh")
    writable = (workspace, symphony_dir(), home / ".symphony" / "oauth", Path(tempfile.gettempdir()))
    return SandboxPolicy.confined(writable, tuple(readable), keychain=github, home=home)


def wants_sandbox(argv: Sequence[str]) -> bool:
    return any(flag in argv for flag in SANDBOX_FLAGS) and not os.environ.get(SANDBOXED)


def reexec_sandboxed(subcommand: str, argv: Sequence[str], workspace: Path) -> NoReturn:
    """Replace this process with `symphony <subcommand> <argv>` (flags removed) under the sandbox."""
    if not sandbox_available():
        print("error: --sandbox needs macOS (sandbox-exec)", file=sys.stderr)
        raise SystemExit(2)
    github = "--sandbox-github" in argv
    rest = [arg for arg in argv if arg not in SANDBOX_FLAGS]
    command = sandbox_policy(workspace, github=github).wrap([sys.executable, "-m", "coding_agent.cli", subcommand, *rest])
    os.execve(command[0], command, {**os.environ, SANDBOXED: "1"})


__all__ = ["SANDBOX_FLAGS", "reexec_sandboxed", "sandbox_policy", "wants_sandbox"]
