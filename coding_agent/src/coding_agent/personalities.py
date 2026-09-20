"""Agent personality catalog and system-prompt segment composer.

Repo-root ``personalities.json`` is the catalog. ``CodingAgentConfig.personality``
defaults to ``"direct"`` so new sessions include that segment. ``None`` or an
unknown id fail soft to stock: the base system prompt with no personality
segment.

Personality is one named, swappable segment. ``compose_system_prompt`` inserts
or replaces only that segment; other ``**segments`` are extra named blocks
appended as-is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

PERSONALITY_BEGIN = "<personality>"
PERSONALITY_END = "</personality>"
DEFAULT_PERSONALITY = "direct"

_PERSONALITY_BLOCK = re.compile(
    rf"\n*{re.escape(PERSONALITY_BEGIN)}.*?{re.escape(PERSONALITY_END)}",
    flags=re.DOTALL,
)


@dataclass(frozen=True)
class Personality:
    id: str
    name: str
    system_addon: str


def discover_personalities_path() -> Path | None:
    """Walk from this module and cwd toward filesystem root for the catalog."""
    starts = (Path(__file__).resolve().parent, Path.cwd().resolve())
    seen: set[Path] = set()
    for start in starts:
        for directory in (start, *start.parents):
            if directory in seen:
                continue
            seen.add(directory)
            path = directory / "personalities.json"
            if path.is_file():
                return path
    return None


def load_personalities(path: Path | None = None) -> tuple[Personality, ...]:
    """Read the catalog. Missing or invalid files yield an empty catalog."""
    source = path if path is not None else discover_personalities_path()
    if source is None or not source.is_file():
        return ()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    rows = payload.get("personalities") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ()
    loaded: list[Personality] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        personality_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        addon = str(row.get("system_addon") or "").strip()
        if personality_id and name and addon:
            loaded.append(
                Personality(id=personality_id, name=name, system_addon=addon)
            )
    return tuple(loaded)


def get(
    personality_id: str | None,
    personalities: Iterable[Personality] | None = None,
) -> Personality | None:
    """Look up a catalog row. Blank or unknown ids return ``None`` (stock)."""
    if not personality_id or not str(personality_id).strip():
        return None
    catalog = (
        load_personalities() if personalities is None else tuple(personalities)
    )
    needle = str(personality_id).strip().lower()
    for item in catalog:
        if item.id.lower() == needle:
            return item
    return None


def compose_system_prompt(
    base: str,
    personality_id: str | None = None,
    **segments: str,
) -> str:
    """Compose ``base`` plus named segments.

    Personality is the one swappable catalog segment: looked up by id, inserted
    or replaced in place, and omitted when the id is ``None`` or unknown.
    Other ``**segments`` (plan, skills, …) are appended when non-empty.
    """
    found = get(personality_id)
    addon = found.system_addon if found is not None else None
    prompt = _replace_personality_segment(base, addon)
    extras = [
        text.strip()
        for name, text in segments.items()
        if name != "personality" and isinstance(text, str) and text.strip()
    ]
    if extras:
        prompt = f"{prompt.rstrip()}\n\n" + "\n\n".join(extras)
    return prompt.rstrip() + "\n"


def _replace_personality_segment(prompt: str, addon: str | None) -> str:
    replacement = f"\n\n{PERSONALITY_BEGIN}\n{addon.strip()}\n{PERSONALITY_END}" if addon else ""
    match = _PERSONALITY_BLOCK.search(prompt)
    if match:
        return (prompt[: match.start()] + replacement + prompt[match.end() :]).rstrip()
    if not addon:
        return prompt.rstrip()
    return f"{prompt.rstrip()}{replacement}"
