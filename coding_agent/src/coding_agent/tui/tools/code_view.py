"""Code-style renderables for finished tool cards.

Every colour comes from the active theme: token colours from
``SYMPHONY_CODE_THEME`` and the rest (gutter, hunk headers, diff tints) from
``SYMPHONY_COLORS``. Both are updated in place when the theme changes, so a
view built after a switch, or rebuilt by ``ToolCallModal.restyle``, uses the
new palette.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from rich.console import Group
from rich.padding import Padding
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from coding_agent.tui.theme import SYMPHONY_CODE_THEME, SYMPHONY_COLORS

MAX_CODE_LINES = 2000


def colour(token: str) -> str:
    """A colour of the active theme. ``diff_added`` and ``diff_removed`` are
    optional in a theme, so they fall back to its panel colours."""
    fallback = {"diff_added": "surface", "diff_removed": "overlay"}
    return SYMPHONY_COLORS.get(token) or SYMPHONY_COLORS[fallback.get(token, "foreground")]


def note(text: str) -> Text:
    """A dim line under a view: a truncation notice, or an empty result."""
    return Text(text, style=colour("muted"))


def highlighted(lines: list[str], lexer: str, *, wrap: bool = False) -> list[Text]:
    """Each line coloured by the theme's syntax styles, without a background,
    so a diff row's tint shows through. Highlighted as one block so a string
    or comment spanning lines keeps its colour."""
    if not lines:
        return []
    syntax = Syntax("", lexer or "text", theme=SYMPHONY_CODE_THEME)
    block = syntax.highlight("\n".join(lines))
    rows = list(block.split("\n", allow_blank=True))[: len(lines)]
    for row in rows:
        row.style = Style.null()
        row.no_wrap = not wrap
        row.overflow = "fold" if wrap else "crop"
    return rows


def code_view(
    text: str,
    *,
    lexer: str = "text",
    limit: int = MAX_CODE_LINES,
    wrap: bool = False,
    start_line: int = 1,
) -> object:
    """Render text as a highlighted, numbered code view, truncating oversized results.

    ``start_line`` is the number the gutter starts at, so a read from line 40
    is numbered from 40.
    """
    lines = str(text or "").splitlines()
    if not lines:
        return note("No details yet.")
    hidden = max(0, len(lines) - limit)
    body = Syntax(
        "\n".join(lines[:limit]),
        lexer or "text",
        theme=SYMPHONY_CODE_THEME,
        line_numbers=True,
        start_line=start_line,
        word_wrap=wrap,
    )
    if hidden:
        return Group(body, note(f"… {hidden} lines hidden"))
    return body


_READ_LINE = re.compile(r"^ *(\d+)\|")


def strip_line_numbers(text: str) -> tuple[int, str, str]:
    """Split read_file's ``N|line`` text into (first line number, source, note).

    The tool numbers every line for the model; the code view draws its own
    gutter, so the numbers come off here. A trailing line that is not numbered
    (the truncation notice) is returned as the note. Text that is not numbered
    this way comes back whole, starting at line 1.
    """
    lines = text.split("\n")
    first = _READ_LINE.match(lines[0]) if lines else None
    if first is None:
        return 1, text, ""
    start = expected = int(first.group(1))
    source: list[str] = []
    for index, line in enumerate(lines):
        match = _READ_LINE.match(line)
        if match is None or int(match.group(1)) != expected:
            note = "\n".join(lines[index:]).strip()
            return start, "\n".join(source), note
        source.append(line[match.end():])
        expected += 1
    return start, "\n".join(source), ""


def lexer_for_path(path: str, code: str = "") -> str:
    """The Pygments lexer for a file name, or ``text`` when there is none."""
    from pygments.lexers import get_lexer_for_filename
    from pygments.util import ClassNotFound

    name = Path(path.strip()).name
    if not name:
        return "text"
    try:
        lexer = get_lexer_for_filename(name, code)
    except ClassNotFound:
        return "text"
    return lexer.aliases[0] if lexer.aliases else "text"


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def diff_view(lines: list[str], *, wrap: bool = False, lexer: str = "text") -> object:
    """A unified diff with the file's old and new line numbers and tinted rows.

    Each hunk header resets the counters, so the gutter shows where the edit
    sits in the file rather than its position in the diff. The code itself is
    highlighted for ``lexer``.
    """
    if not lines:
        return note("No changes.")
    shown = lines[:MAX_CODE_LINES]
    bodies = iter(highlighted([line[1:] for line in shown if not _HUNK.match(line)], lexer, wrap=wrap))
    gutter = colour("punctuation")
    added, removed = Style(bgcolor=colour("diff_added")), Style(bgcolor=colour("diff_removed"))
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(justify="right", style=gutter, no_wrap=True)
    table.add_column(justify="right", style=gutter, no_wrap=True)
    table.add_column(width=1, no_wrap=True)
    table.add_column(ratio=1, no_wrap=not wrap, overflow="fold" if wrap else "crop")
    old = new = 0
    for line in shown:
        hunk = _HUNK.match(line)
        if hunk:
            old, new = int(hunk.group(1)), int(hunk.group(2))
            table.add_row("", "", "", Text(line, style=colour("attribute")))
            continue
        sign, body = line[:1], next(bodies)
        if sign == "+":
            table.add_row("", str(new), Text("+", style=colour("string")), body, style=added)
            new += 1
        elif sign == "-":
            table.add_row(str(old), "", Text("-", style=colour("keyword")), body, style=removed)
            old += 1
        else:
            table.add_row(str(old), str(new), "", body)
            old += 1
            new += 1
    if len(lines) > MAX_CODE_LINES:
        return Group(table, note(f"… {len(lines) - MAX_CODE_LINES} lines hidden"))
    return table


def _tinted(body: Text, tint: str) -> object:
    """A diff cell whose tint fills the whole column, not just the text."""
    return Padding(body, (0, 0), style=Style(bgcolor=tint), expand=True)


def split_diff_view(lines: list[str], *, wrap: bool = False, lexer: str = "text") -> object:
    """The same diff side by side: the old lines on the left, the new on the right.

    Removed and added runs pair up row by row, so a changed line sits beside
    its replacement. Numbers are the file's own lines, from the hunk headers.
    """
    if not lines:
        return note("No changes.")
    shown = lines[:MAX_CODE_LINES]
    bodies = iter(highlighted([line[1:] for line in shown if not _HUNK.match(line)], lexer, wrap=wrap))
    gutter = colour("punctuation")
    added, removed = colour("diff_added"), colour("diff_removed")
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(justify="right", style=gutter, no_wrap=True)
    table.add_column(ratio=1)
    table.add_column(width=1, style=colour("edge"), no_wrap=True)
    table.add_column(justify="right", style=gutter, no_wrap=True)
    table.add_column(ratio=1)
    old_run: list[tuple[int, Text]] = []
    new_run: list[tuple[int, Text]] = []

    def flush() -> None:
        for index in range(max(len(old_run), len(new_run))):
            left = old_run[index] if index < len(old_run) else None
            right = new_run[index] if index < len(new_run) else None
            table.add_row(
                str(left[0]) if left else "",
                _tinted(left[1], removed) if left else "",
                "│",
                str(right[0]) if right else "",
                _tinted(right[1], added) if right else "",
            )
        old_run.clear()
        new_run.clear()

    old = new = 0
    for line in shown:
        hunk = _HUNK.match(line)
        if hunk:
            flush()
            old, new = int(hunk.group(1)), int(hunk.group(2))
            table.add_row("", Text(line, style=colour("attribute")), "│", "", "")
            continue
        sign, body = line[:1], next(bodies)
        if sign == "-":
            old_run.append((old, body))
            old += 1
        elif sign == "+":
            new_run.append((new, body))
            new += 1
        else:
            flush()
            table.add_row(str(old), body, "│", str(new), body.copy())
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
    return note("No arguments.")
