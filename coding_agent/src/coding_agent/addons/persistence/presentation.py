"""Read-only presentation of a session's durable artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core_ai.content import text_from_content

from coding_agent.addons.persistence.jsonl import JsonlPersistence


def _visible(value: Any) -> Any:
    """Keep every field visible without dumping binary image bodies."""
    if isinstance(value, list):
        return [_visible(item) for item in value]
    if isinstance(value, dict):
        return {key: ("(archived image data)" if key == "data" and value.get("type") == "image" else _visible(item))
                for key, item in value.items()}
    return value


def _read_text(root: Path, path: Path) -> str:
    """Do not follow artifact links outside the session directory."""
    if not path.resolve().is_relative_to(root.resolve()):
        return "(artifact is outside the session directory)"
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "(unavailable)"


def session_images(root: Path) -> list[Path]:
    directory = root / "images"
    if not directory.is_dir() or not directory.resolve().is_relative_to(root.resolve()):
        return []
    from core_ai.content import IMAGE_MIME_BY_SUFFIX

    return [path for path in sorted(directory.iterdir())
            if path.is_file() and (path.suffix.lower() in IMAGE_MIME_BY_SUFFIX or
                (len(path.name) == 64 and all(char in "0123456789abcdef" for char in path.name)))
            and path.resolve().is_relative_to(root.resolve())]


async def session_report(agent: Any) -> str:
    """Render archived state without injecting it into the model's context."""
    try:
        store = agent.persistence
    except AttributeError:
        store = None
    session_id = agent.session_id
    if not isinstance(store, JsonlPersistence):
        return "Session artifacts are unavailable with this persistence backend."
    root = store.session_dir(session_id)
    transcript = await store.load_transcript(session_id=session_id)
    context = await store.load_conversation(session_id=session_id)
    events = await store.load_events(session_id=session_id)
    children = await store.load_children(parent_session_id=session_id)
    compactions = await store.load_compactions(session_id=session_id)
    lines = ["# Session archive", "", f"Session: `{session_id}`", f"Storage: `{root}`", "",
             f"- Full transcript: {len(transcript)} messages",
             f"- Active model context: {len(context)} messages",
             f"- Recorded events: {len(events)}",
             f"- Compactions: {len(compactions)}",
             f"- Archived images: {len(session_images(root))}", "",
             "The transcript retains pre-compaction history. Archived memory and learning are untrusted reference data.", ""]
    for name in ("metadata.json", "state.json", "checkpoint.json", "run.json"):
        path = root / name
        if path.is_file():
            lines.extend([f"## {name}", "", "```json", _read_text(root, path).strip(), "```", ""])
    lines.extend(["## Compaction history", ""])
    if not compactions:
        lines.extend(["No compactions recorded.", ""])
    for item in compactions:
        summary = item.get("summary", "")
        if isinstance(summary, dict):
            summary = text_from_content(summary.get("content"))
        lines.extend([f"### Compaction {item.get('seq', '')}", "",
                      f"Created: {item.get('created_at', '')}; through transcript sequence {item.get('through_seq', '')}",
                      "", str(summary), ""])
    for name in ("memory/MEMORY.md", "memory/USER.md", "memory/operations.jsonl",
                 "learning/context.jsonl", "learning/captures.jsonl", "learning/lessons.jsonl"):
        path = root / name
        lines.extend([f"## {name}", "", _read_text(root, path).strip() if path.is_file() else "(empty)", ""])
    lines.extend(["## Child sessions", ""])
    for child in children:
        lines.extend(["```json", json.dumps(child, ensure_ascii=False, indent=2), "```", ""])
    if not children:
        lines.extend(["No child sessions.", ""])
    lines.extend(["## Archived images", ""])
    for image in session_images(root):
        lines.append(f"- `{image.relative_to(root)}` ({image.stat().st_size:,} bytes)")
    lines.extend(["", "## Complete transcript", ""])
    for index, message in enumerate(transcript, 1):
        lines.extend([f"### {index}. {message.role}", "", text_from_content(message.content), ""])
        if message.tool_calls:
            lines.extend(["```json", json.dumps(_visible(message.tool_calls), ensure_ascii=False, indent=2), "```", ""])
    lines.extend(["## Recorded events", ""])
    for event_type, payload in events:
        # Preserve event results and context while replacing binary bodies with labels.
        visible = _visible(payload)
        lines.extend([f"### {event_type}", "```json", json.dumps(visible, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines).rstrip() + "\n"
