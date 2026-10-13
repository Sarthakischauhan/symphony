"""Code-style renderables for finished tool cards."""

from __future__ import annotations

from rich.console import Group
from rich.syntax import Syntax
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
