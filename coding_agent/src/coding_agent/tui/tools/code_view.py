"""Code-style renderables for finished tool cards."""

from __future__ import annotations

import re

from rich.console import Group
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
