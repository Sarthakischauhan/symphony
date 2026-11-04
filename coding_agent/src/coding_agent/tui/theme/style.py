"""Rich glue for tokens loaded from theme.toml: syntax highlighting and markdown styles.

Both objects are created once and updated in place by ``restyle``, because widgets
hold references to them. Colors are Rich colors (hex or terminal ANSI names).
"""

from __future__ import annotations

from typing import Mapping

from pygments.token import (
    Comment,
    Error,
    Generic,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
    _TokenType,
)
from rich.markdown import Markdown
from rich.style import Style
from rich.syntax import SyntaxTheme
from rich.theme import Theme

from coding_agent.tui.theme.load import SYMPHONY_COLORS


def syntax_styles(colors: Mapping[str, str]) -> dict[_TokenType, Style]:
    """Pygments token -> Rich style for a palette. Added and removed lines use the diff backgrounds."""
    added = colors.get("diff_added", colors["surface"])
    removed = colors.get("diff_removed", colors["overlay"])
    parse = Style.parse
    return {
        Text: parse(colors["foreground"]),
        Text.Whitespace: parse(colors["punctuation"]),
        Comment: parse("italic " + colors["comment"]),
        Comment.Preproc: parse(colors["comment"]),
        Keyword: parse(colors["keyword"]),
        Keyword.Type: parse(colors["type_keywords"]),
        Operator: parse(colors["operator"]),
        Punctuation: parse(colors["punctuation"]),
        Name: parse(colors["variable"]),
        Name.Builtin: parse(colors["constant"]),
        Name.Class: parse("bold " + colors["type"]),
        Name.Decorator: parse(colors["attribute"]),
        Name.Exception: parse(colors["keyword"]),
        Name.Function: parse(colors["function"]),
        Name.Namespace: parse(colors["type"]),
        Name.Tag: parse(colors["tag"]),
        Name.Variable: parse(colors["variable"]),
        String: parse(colors["string"]),
        String.Doc: parse("italic " + colors["comment"]),
        Number: parse(colors["number"]),
        Generic.Deleted: parse(colors["keyword"] + " on " + removed),
        Generic.Inserted: parse(colors["string"] + " on " + added),
        Generic.Heading: parse("bold " + colors["foreground"]),
        Generic.Subheading: parse(colors["subtext"]),
        Error: parse(colors["keyword"] + " on " + colors["overlay"]),
    }


class PaletteSyntaxTheme(SyntaxTheme):
    """Rich syntax theme over a palette. ``update`` swaps the palette without replacing the object."""

    def __init__(self, colors: Mapping[str, str]) -> None:
        self._styles: dict[_TokenType, Style] = {}
        self._background = Style()
        self.update(colors)

    def update(self, colors: Mapping[str, str]) -> None:
        self._styles = syntax_styles(colors)
        self._background = Style.parse("on " + colors["background"])

    def get_style_for_token(self, token_type: _TokenType) -> Style:
        """The style of the closest ancestor token that has one; plain text otherwise."""
        token: _TokenType | None = token_type
        while token is not None:
            style = self._styles.get(token)
            if style is not None:
                return style
            token = token.parent
        return self._styles[Text]

    def get_background_style(self) -> Style:
        return self._background


def markdown_styles(colors: Mapping[str, str]) -> dict[str, str]:
    """Rich style names Markdown renders with, for a palette."""
    return {
        "markdown.paragraph": colors["foreground"],
        "markdown.text": colors["foreground"],
        "markdown.h1": "bold " + colors["foreground"],
        "markdown.h2": "bold " + colors["attribute"],
        "markdown.h3": "bold " + colors["tag"],
        "markdown.h4": "italic " + colors["subtext"],
        "markdown.h5": "italic " + colors["comment"],
        "markdown.h6": "dim " + colors["comment"],
        "markdown.block_quote": colors["string"],
        "markdown.list": colors["foreground"],
        "markdown.item.bullet": "bold " + colors["function"],
        "markdown.item.number": colors["function"],
        "markdown.code": "bold " + colors["tag"],
        "markdown.link": colors["function"],
        "markdown.link_url": "underline " + colors["attribute"],
        "markdown.table.border": colors["punctuation"],
        "markdown.table.header": "bold " + colors["attribute"],
        "markdown.kbd": "bold " + colors["type"],
    }


SYMPHONY_CODE_THEME = PaletteSyntaxTheme(SYMPHONY_COLORS)
SYMPHONY_RICH_THEME = Theme(markdown_styles(SYMPHONY_COLORS), inherit=True)


def restyle() -> None:
    """Point the syntax and Markdown styles at the colors now in ``SYMPHONY_COLORS``."""
    SYMPHONY_CODE_THEME.update(SYMPHONY_COLORS)
    SYMPHONY_RICH_THEME.styles.update({name: Style.parse(text) for name, text in markdown_styles(SYMPHONY_COLORS).items()})


def themed_markdown(markup: str, **kwargs: object) -> Markdown:
    """Build Rich Markdown using Symphony's syntax theme (not Rich's monokai default)."""
    kwargs.setdefault("code_theme", SYMPHONY_CODE_THEME)
    kwargs.setdefault("inline_code_theme", SYMPHONY_CODE_THEME)
    return Markdown(markup, **kwargs)  # type: ignore[arg-type]
