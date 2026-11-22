"""Named, explicitly selected coding-agent profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from coding_agent.config.config import symphony_dir


@dataclass(frozen=True)
class AgentProfile:
    name: str
    model: str = ""
    instructions: str = ""
    tools: tuple[str, ...] | None = None


def load_agent_profile(workspace: str | Path, name: str) -> AgentProfile:
    """Load a project profile before a user profile; reject paths and unknown fields."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
        raise ValueError("invalid agent profile name")
    roots = (Path(workspace) / ".symphony" / "agents", symphony_dir() / "agents")
    path = next((p for root in roots for p in (root / f"{name}.yaml", root / f"{name}.yml") if p.is_file()), None)
    if path is None:
        raise ValueError(f"agent profile not found: {name}")
    try:
        if path.stat().st_size > 65536:
            raise ValueError("profile exceeds 64 KiB")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read agent profile {path}: {exc}") from exc
    if not isinstance(data, dict) or set(data) - {"name", "model", "instructions", "tools"}:
        raise ValueError(f"invalid agent profile fields in {path}")
    if data.get("name", name) != name:
        raise ValueError(f"agent profile name must match filename: {path}")
    model, instructions, tools = data.get("model", ""), data.get("instructions", ""), data.get("tools")
    if not isinstance(model, str) or not isinstance(instructions, str):
        raise ValueError(f"profile model and instructions must be strings: {path}")
    if tools is not None and (not isinstance(tools, list) or any(not isinstance(t, str) or not t for t in tools)):
        raise ValueError(f"profile tools must be a list of tool names: {path}")
    return AgentProfile(name, model.strip(), instructions.strip(), None if tools is None else tuple(tools))
