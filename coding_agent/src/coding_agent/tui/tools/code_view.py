"""Code-style renderables for finished tool cards."""

from __future__ import annotations

import json
import re

from rich.console import Group
from rich.padding import Padding
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from coding_agent.tui.theme import SYMPHONY_CODE_THEME

MAX_CODE_LINES = 2000


def code_view(
    text: str,
    *,
    lexer: str = "text",
    limit: int = MAX_CODE_LINES,
    wrap: bool = False,
) -> object:
    """Render text as a numbered code view, truncating oversized results."""
    lines = str(text or "").splitlines()
    if not lines:
        return Text("No details yet.", style="#686868")
    hidden = max(0, len(lines) - limit)
    visible = "\n".join(lines[:limit])
    if hidden == 0:
        body: object = Syntax(
            visible,
            lexer,
            theme=SYMPHONY_CODE_THEME,
            line_numbers=True,
            word_wrap=wrap,
            background_color="#0d0d0d",
        )
    else:
        body = _numbered(visible, wrap=wrap)
    if hidden:
        return Group(body, Text(f"… {hidden} lines hidden", style="#555555"))
    return body


def _numbered(text: str, *, wrap: bool) -> Text:
    lines = text.splitlines() or [""]
    width = max(2, len(str(len(lines))))
    rendered = Text(no_wrap=not wrap, overflow="fold" if wrap else "crop")
    for number, line in enumerate(lines, start=1):
        rendered.append(f"{number:>{width}} │ ", style="#687e8b")
        rendered.append(line, style="#d0d0d0")
        if number != len(lines):
            rendered.append("\n")
    return rendered


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
DIFF_ADDED = "on #19301d"
DIFF_REMOVED = "on #321c20"


def diff_view(lines: list[str], *, wrap: bool = False) -> object:
    """A unified diff with the file's old and new line numbers and tinted rows.

    Each hunk header resets the counters, so the gutter shows where the edit
    sits in the file rather than its position in the diff.
    """
    if not lines:
        return Text("No changes.", style="#686868")
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(justify="right", style="#4f5b63", no_wrap=True)
    table.add_column(justify="right", style="#4f5b63", no_wrap=True)
    table.add_column(width=1, no_wrap=True)
    table.add_column(ratio=1, no_wrap=not wrap, overflow="fold" if wrap else "crop")
    old = new = 0
    for line in lines[:MAX_CODE_LINES]:
        hunk = _HUNK.match(line)
        if hunk:
            old, new = int(hunk.group(1)), int(hunk.group(2))
            table.add_row("", "", "", Text(line, style="#4f6a85"))
            continue
        sign, body = line[:1], line[1:]
        if sign == "+":
            table.add_row("", str(new), Text("+", style="#8fc49a"), Text(body, style="#cfe8d4"), style=DIFF_ADDED)
            new += 1
        elif sign == "-":
            table.add_row(str(old), "", Text("-", style="#df8b91"), Text(body, style="#f0c9cc"), style=DIFF_REMOVED)
            old += 1
        else:
            table.add_row(str(old), str(new), "", Text(body, style="#a8a8a8"))
            old += 1
            new += 1
    if len(lines) > MAX_CODE_LINES:
        return Group(table, Text(f"… {len(lines) - MAX_CODE_LINES} lines hidden", style="#555555"))
    return table


def _tinted(text: str, *, fg: str, bg: str | None, wrap: bool) -> object:
    """A diff cell whose tint fills the whole column, not just the text."""
    body = Text(text, style=fg, no_wrap=not wrap, overflow="fold" if wrap else "crop")
    return Padding(body, (0, 0), style=bg, expand=True) if bg else body


def split_diff_view(lines: list[str], *, wrap: bool = False) -> object:
    """The same diff side by side: the old lines on the left, the new on the right.

    Removed and added runs pair up row by row, so a changed line sits beside
    its replacement. Numbers are the file's own lines, from the hunk headers.
    """
    if not lines:
        return Text("No changes.", style="#686868")
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(justify="right", style="#4f5b63", no_wrap=True)
    table.add_column(ratio=1)
    table.add_column(width=1, style="#2a2a2a", no_wrap=True)
    table.add_column(justify="right", style="#4f5b63", no_wrap=True)
    table.add_column(ratio=1)
    removed: list[tuple[int, str]] = []
    added: list[tuple[int, str]] = []

    def flush() -> None:
        for index in range(max(len(removed), len(added))):
            left = removed[index] if index < len(removed) else None
            right = added[index] if index < len(added) else None
            table.add_row(
                str(left[0]) if left else "",
                _tinted(left[1], fg="#f0c9cc", bg=DIFF_REMOVED, wrap=wrap) if left else "",
                "│",
                str(right[0]) if right else "",
                _tinted(right[1], fg="#cfe8d4", bg=DIFF_ADDED, wrap=wrap) if right else "",
            )
        removed.clear()
        added.clear()

    old = new = 0
    for line in lines[:MAX_CODE_LINES]:
        hunk = _HUNK.match(line)
        if hunk:
            flush()
            old, new = int(hunk.group(1)), int(hunk.group(2))
            table.add_row("", Text(line, style="#4f6a85"), "│", "", "")
            continue
        sign, body = line[:1], line[1:]
        if sign == "-":
            removed.append((old, body))
            old += 1
        elif sign == "+":
            added.append((new, body))
            new += 1
        else:
            flush()
            context = Text(body, style="#a8a8a8", no_wrap=not wrap, overflow="fold" if wrap else "crop")
            table.add_row(str(old), context, "│", str(new), context.copy())
            old += 1
            new += 1
    flush()
    return table


def arguments_view(arguments: dict, raw: str = "", *, wrap: bool = False) -> object:
    """The call's arguments as the model sent them, as formatted JSON."""
    if arguments:
        return code_view(json.dumps(arguments, indent=2, ensure_ascii=False), lexer="json", wrap=wrap)
    if raw:
        return code_view(raw, lexer="json", wrap=wrap)
    return Text("No arguments.", style="#686868")
