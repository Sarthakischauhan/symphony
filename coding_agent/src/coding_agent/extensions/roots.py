"""The one place that says where skills and plugins are read from, and in what order.

Order, first match wins: the workspace's ``.symphony`` and ``.agents`` (nearest
directory first, walking up to the git root), then the Symphony home
(``SYMPHONY_HOME`` or ``~/.symphony``), then ``~/.agents`` (shared with Codex,
Pi, OpenCode and Grok), then the skills bundled with Symphony.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from coding_agent.config import symphony_dir

Scope = Literal["project", "user", "agents", "bundled"]
BUNDLED_SKILLS = Path(__file__).resolve().parents[1] / "addons" / "skills" / "bundled_skills"
_PROJECT_DIRS = (".symphony", ".agents")


@dataclass(frozen=True)
class ExtensionRoot:
    """One place to look: a skills directory and, except for bundled, a plugins directory."""

    scope: Scope
    skills: Path
    plugins: Path | None

    @classmethod
    def under(cls, scope: Scope, base: Path) -> ExtensionRoot:
        return cls(scope, base / "skills", base / "plugins")


def _project_directories(workspace: Path) -> list[Path]:
    """The workspace and its parents up to and including the git root; just the workspace outside git."""
    chain = [workspace, *workspace.parents]
    for index, directory in enumerate(chain):
        if (directory / ".git").exists():
            return chain[: index + 1]
    return [workspace]


def extension_roots(workspace: str | Path) -> tuple[ExtensionRoot, ...]:
    """Every root for ``workspace`` in precedence order, without duplicates."""
    workspace = Path(workspace).expanduser().resolve()
    user = symphony_dir()
    shared = (Path.home() / ".agents").expanduser().resolve()
    roots = [
        ExtensionRoot.under("project", directory / name)
        for directory in _project_directories(workspace)
        for name in _PROJECT_DIRS
    ]
    roots += [ExtensionRoot.under("user", user), ExtensionRoot.under("agents", shared)]
    unique: list[ExtensionRoot] = []
    for root in roots:
        # A workspace at (or under) the home directory would list the user roots twice.
        if root.scope == "project" and root.skills.parent in (user, shared):
            continue
        if root.skills not in {item.skills for item in unique}:
            unique.append(root)
    unique.append(ExtensionRoot("bundled", BUNDLED_SKILLS, None))
    return tuple(unique)


__all__ = ["BUNDLED_SKILLS", "ExtensionRoot", "Scope", "extension_roots"]
