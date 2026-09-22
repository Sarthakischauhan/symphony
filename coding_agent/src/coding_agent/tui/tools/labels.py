"""One-line labels, argument summaries, and result previews for tool cards."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from rich.markup import escape

from coding_agent.tui.transcript.messages import clip_text, compact_json

TOOL_LABELS = {
    "bash": ("Bash", "$"),
    "search": ("Search", "⌕"),
    "write_file": ("Write", "+"),
    "generate_image": ("Image", "└"),
    "patch": ("Update", "±"),
    "read_file": ("Read", "└"),
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
    if tool_name == "search":
        return str(args.get("query") or args.get("pattern") or compact_json(args))
    if tool_name in {"write_file", "patch", "generate_image", "read_file"}:
        path = str(args.get("path") or "")
        if path:
            return path
        return compact_json(args) or raw_arguments
    return compact_json(args) or raw_arguments


def header_command(reason: str, summary: str, limit: int) -> str:
    """Live-card detail: the file or command, not the activity reason."""
    del reason
    return summary


def tool_header_text(label: str, target: str, status: str) -> str:
    """Render markup with status color on the tool name and muted target."""
    color = {
        "preparing": "#d7a84b",
        "running": "#d7a84b",
        "done": "#72a57a",
        "failed": "#d66b73",
    }.get(status, "#9aa7b2")
    head = f"[bold {color}]{escape(label)}[/bold {color}]"
    if not target:
        return head
    return f"{head} [#9aa7b2]{escape(target)}[/#9aa7b2]"


def header_target(summary: str) -> str:
    """Show the protocol value beside the verb: path, command, or query."""
    text = summary.strip()
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
        match = re.search(r'"path"\s*:\s*"((?:\\.|[^"\\])*)"', raw_arguments or "")
        if match:
            path = json.loads(f'"{match.group(1)}"')
        else:
            return raw_arguments
    offset = int(arguments.get("offset") or 1)
    limit = int(arguments.get("limit") or 0)
    if offset == 1 and not limit:
        return str(path)
    end = offset + limit - 1 if limit else "…"
    return f"{path}  lines {offset}–{end}"


def read_file_result(result: str) -> str:
    if not result:
        return ""
    if result.startswith("error:"):
        return result
    if result.startswith("Read image ") or "[image:" in result:
        return result.splitlines()[0]
    count = len(result.splitlines())
    size = len(result.encode("utf-8"))
    return f"Read {count} lines ({size:,} bytes)"


def generate_image_result(result: str) -> str:
    if not result:
        return ""
    if result.startswith("error:"):
        return result
    return result.splitlines()[0]
