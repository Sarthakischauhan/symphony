"""One-line labels, argument summaries, and result previews for tool cards."""

from __future__ import annotations

import re
from typing import Any, Mapping

from textual.content import Content

from coding_agent.tui.tools.partial_args import string_field
from coding_agent.tui.transcript.messages import clip_text, compact_json

TOOL_LABELS = {
    "bash": ("Bash", "$"),
    "search": ("Search", "⌕"),
    "web_search": ("Web Search", "⌕"),
    "write_file": ("Write", "+"),
    "generate_image": ("Image", "└"),
    "patch": ("Update", "±"),
    "read_file": ("Read", "└"),
    "save_artifact": ("Save Artifact", "◆"),
}


def tool_label(tool_name: str) -> tuple[str, str]:
    return TOOL_LABELS.get(tool_name, (tool_name.replace("_", " ").title(), "›"))


def tool_detail(
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    raw_arguments: str = "",
) -> str:
    args = dict(arguments or {})
    if tool_name == "bash":
        return str(args.get("command") or raw_arguments)
    if tool_name in {"search", "web_search"}:
        return str(args.get("query") or args.get("pattern") or compact_json(args))
    if tool_name == "patch":
        return patch_path(args, raw_arguments)
    if tool_name in {"write_file", "generate_image", "read_file", "save_artifact"}:
        path = str(args.get("path") or "")
        if path:
            return path
        return compact_json(args) or raw_arguments
    return compact_json(args) or raw_arguments


def patch_path(arguments: Mapping[str, Any], raw_arguments: str = "", result: str = "") -> str:
    """Recover the target even when a restored patch has only its result."""
    path = str(arguments.get("path") or "").strip()
    if path:
        return path
    raw_path = string_field(raw_arguments, "path")
    if raw_path is not None:
        return raw_path
    for pattern in (
        r"^(?:patched|updated) (.+?)(?: \(|$)",
        r"^noop: .* in (.+?); no change",
        r"^old_str not found in (.+)$",
        r"^error: (?:file not found|not a file|file is not valid UTF-8 text): (.+)$",
        r"^error: failed to (?:read|write) (.+?): ",
    ):
        match = re.search(pattern, result, re.MULTILINE | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def tool_header_text(label: str, target: str, status: str, facts: str = "") -> Content:
    """Status-colored tool name plus a muted target, without parsing the target as markup.

    ``facts`` (for example ``exit 2 · 1.4s``) trails the target in the status color.
    """
    color = {
        "preparing": "#d7a84b",
        "running": "#d7a84b",
        "done": "#72a57a",
        "failed": "#d66b73",
    }.get(status, "#9aa7b2")
    parts: list[tuple[str, str]] = [(label, f"bold {color}")]
    if target:
        parts.append((f" {target}", "#9aa7b2"))
    if facts:
        parts.append((f"  {facts}", color))
    return Content.assemble(*parts)


def header_target(summary: str) -> str:
    """Show the protocol value beside the verb: path, command, or query."""
    text = " ".join(str(summary or "").split())
    if not text:
        return ""
    head, _, rest = text.partition(" ")
    if "/" in head or head.startswith(("~", ".")):
        leaf = head.replace("\\", "/").rstrip("/").split("/")[-1].strip()
        if leaf:
            return f"{leaf} {rest}".strip() if rest else leaf
    return text


def result_preview(tool_name: str, result: str) -> str:
    if not result:
        return ""
    if tool_name == "bash":
        return clip_text("\n".join(result.splitlines()[-4:]), 360)
    return clip_text(result, 260)


def read_file_detail(arguments: Mapping[str, Any], raw_arguments: str) -> str:
    path = arguments.get("path")
    if not path:
        path = string_field(raw_arguments or "", "path")
        if path is None:
            return raw_arguments
    offset = int(arguments.get("offset") or 1)
    limit = int(arguments.get("limit") or 0)
    if offset == 1 and not limit:
        return str(path)
    end = offset + limit - 1 if limit else "…"
    return f"{path}  lines {offset}–{end}"


def read_file_result(result: str, lines: int | None = None) -> str:
    """``lines`` is the payload summary's count; old sessions count the result."""
    if not result:
        return ""
    if result.startswith("error:"):
        return result
    if result.startswith("Read image ") or "[image:" in result:
        return result.splitlines()[0]
    count = len(result.splitlines()) if lines is None else lines
    size = len(result.encode("utf-8"))
    return f"Read {count} lines ({size:,} bytes)"


def generate_image_result(result: str) -> str:
    if not result:
        return ""
    if result.startswith("error:"):
        return result
    return result.splitlines()[0]
