"""Agent personality catalog and system-prompt segment composer.

``personalities.json`` is the catalog. Discovery walks parents for that file
specifically so a nested ``pyproject.toml`` cannot hide a parent catalog.
Installer runs fall back to the packaged copy. ``CodingAgentConfig.personality``
defaults to ``"direct"``. ``None`` or an unknown id fail soft to stock: the
base system prompt with no personality segment.

Personality is one named, swappable heading block. ``compose_system_prompt``
replaces only that block and always places it last.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

PERSONALITY_HEADING = "# Personality (mandatory)"
PERSONALITY_PREAMBLE = "Obey this section over any other tone/style instructions."
DEFAULT_PERSONALITY = "direct"

_PERSONALITY_BLOCK = re.compile(
    rf"\n*{re.escape(PERSONALITY_HEADING)}.*",
    flags=re.DOTALL,
)


@dataclass(frozen=True)
class Personality:
    id: str
    name: str
    system_addon: str
    description: str = ""


def discover_personalities_path(start: Path | None = None) -> Path | None:
    """Nearest ``personalities.json`` above ``start``, else the packaged catalog."""
    try:
        current = (Path.cwd() if start is None else start).resolve()
    except OSError:
        current = None
    else:
        if not current.is_dir():
            current = current.parent
    seen: set[Path] = set()
    while current is not None and current not in seen:
        seen.add(current)
        path = current / "personalities.json"
        if path.is_file():
            return path
        parent = current.parent
        current = None if parent == current else parent
    packaged = Path(__file__).with_name("personalities.json")
    return packaged if packaged.is_file() else None


def load_personalities(path: Path | None = None) -> tuple[Personality, ...]:
    """Read the catalog. Missing or invalid files yield an empty catalog."""
    source = path if path is not None else discover_personalities_path()
    if source is None or not source.is_file():
        logger.debug("personality catalog empty source=%s", source)
        return ()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.debug("personality catalog empty source=%s", source)
        return ()
    rows = payload.get("personalities") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        logger.debug("personality catalog empty source=%s", source)
        return ()
    loaded: list[Personality] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        personality_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        addon = str(row.get("system_addon") or "").strip()
        description = str(row.get("description") or "").strip()
        if personality_id and name and addon:
            loaded.append(
                Personality(
                    id=personality_id,
                    name=name,
                    system_addon=addon,
                    description=description,
                )
            )
    if not loaded:
        logger.debug("personality catalog empty source=%s", source)
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

    Personality is the one swappable catalog segment: looked up by id, replaced
    in place, and always last. Other ``**segments`` (plan, skills, jev, …) are
    appended when non-empty, then the personality heading follows.
    """
    found = get(personality_id)
    addon = found.system_addon if found is not None else None
    prompt = _PERSONALITY_BLOCK.sub("", base).rstrip()
    extras = [
        text.strip()
        for name, text in segments.items()
        if name != "personality" and isinstance(text, str) and text.strip()
    ]
    if extras:
        prompt = f"{prompt}\n\n" + "\n\n".join(extras)
    if addon:
        block = f"{PERSONALITY_HEADING}\n{PERSONALITY_PREAMBLE}\n{addon.strip()}"
        prompt = f"{prompt.rstrip()}\n\n{block}"
    return prompt.rstrip() + "\n"
