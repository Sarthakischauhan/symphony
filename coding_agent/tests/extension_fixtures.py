"""Shared builders for the plugin, marketplace and skill tests: plain trees and real git repositories."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

PSTACK = Path(__file__).parent / "fixtures" / "pstack"


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_skill(directory: Path, name: str, description: str = "Does the thing.", extra: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    document = directory / "SKILL.md"
    document.write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n\nBody of {name}.\n", encoding="utf-8")
    return document


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return done.stdout.strip()


def commit_all(repo: Path, message: str = "commit") -> str:
    """Make ``repo`` a git repository if it is not one, commit everything, return the commit sha."""
    if not (repo / ".git").exists():
        git(repo, "init", "--quiet", "--initial-branch=main")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def plugin_tree(root: Path, name: str = "demo", *, version: str = "1.0.0", skills: tuple[str, ...] = ("alpha",)) -> Path:
    """A minimal Claude-format plugin: ``.claude-plugin/plugin.json`` plus skills."""
    write_json(root / ".claude-plugin" / "plugin.json", {"name": name, "version": version, "description": f"{name} plugin"})
    for skill in skills:
        write_skill(root / "skills" / skill, skill, f"{skill} from {name}.")
    return root


def addon_plugin_tree(root: Path, name: str = "coded") -> Path:
    """A plugin with skills and an addon registering a command, declared under ``extensions.symphony``."""
    plugin_tree(root, name)
    write_json(
        root / ".claude-plugin" / "plugin.json",
        {"name": name, "version": "1.0.0", "extensions": {"symphony": {"addons": "addons"}}},
    )
    addon = root / "addons" / "hello"
    addon.mkdir(parents=True)
    (addon / "addon.py").write_text(
        "from core_harness.extensions import CommandSpec\n\n"
        "def setup(api):\n"
        "    api.register_command(CommandSpec('hello', 'say hello', lambda argument: 'hello ' + argument))\n",
        encoding="utf-8",
    )
    return root


def claude_marketplace(root: Path, name: str = "market", plugins: tuple[str, ...] = ("demo",)) -> Path:
    """A Claude-format marketplace whose plugins live under ``plugins/<name>``."""
    entries = []
    for plugin in plugins:
        plugin_tree(root / "plugins" / plugin, plugin)
        entries.append({"name": plugin, "source": f"./plugins/{plugin}", "version": "1.0.0"})
    write_json(root / ".claude-plugin" / "marketplace.json", {"name": name, "plugins": entries})
    return root
