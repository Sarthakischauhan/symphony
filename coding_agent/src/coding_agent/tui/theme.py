"""Shared color tokens for Rich content embedded in the Textual UI."""

from __future__ import annotations

from pygments.style import Style
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
)
from rich.markdown import Markdown
from rich.syntax import PygmentsSyntaxTheme
from rich.theme import Theme


class SymphonyCodeStyle(Style):
    """Low-contrast syntax palette matched to Symphony's charcoal surface."""

    background_color = "#202020"
    highlight_color = "#343434"
    line_number_color = "#555555"
    line_number_background_color = "#202020"
    line_number_special_color = "#aaaaaa"
    line_number_special_background_color = "#343434"

    styles = {
        Text: "#d0d0d0",
        Text.Whitespace: "#4d4d4d",
        Comment: "italic #686868",
        Comment.Preproc: "#858585",
        Keyword: "#c39ac9",
        Keyword.Type: "#87b5b1",
        Operator: "#a8a8a8",
        Punctuation: "#929292",
        Name: "#d0d0d0",
        Name.Builtin: "#87b5b1",
        Name.Class: "bold #d6b879",
        Name.Decorator: "#c39ac9",
        Name.Exception: "#d88b91",
        Name.Function: "#8eafc2",
        Name.Namespace: "#d6b879",
        Name.Tag: "#d88b91",
        Name.Variable: "#d0d0d0",
        String: "#a7b582",
        String.Doc: "italic #7f916a",
        Number: "#d2a06f",
        Generic.Deleted: "#df8b91 bg:#352225",
        Generic.Inserted: "#8fc49a bg:#203026",
        Generic.Heading: "bold #d0d0d0",
        Generic.Subheading: "#a0a0a0",
        Error: "#f0a0a0 bg:#402326",
    }


SYMPHONY_CODE_THEME = PygmentsSyntaxTheme(SymphonyCodeStyle)

SYMPHONY_RICH_THEME = Theme(
    {
        "markdown.paragraph": "#d0d0d0",
        "markdown.text": "#d0d0d0",
        "markdown.h1": "bold #e6e6e6",
        "markdown.h2": "bold #b9c5d4",
        "markdown.h3": "bold #9fb1c2",
        "markdown.h4": "italic #a0a0a0",
        "markdown.h5": "italic #909090",
        "markdown.h6": "dim #888888",
        "markdown.block_quote": "#7f916a",
        "markdown.list": "#d0d0d0",
        "markdown.item.bullet": "bold #8eafc2",
        "markdown.item.number": "#8eafc2",
        "markdown.code": "bold #87b5b1",
        "markdown.link": "#8eafc2",
        "markdown.link_url": "underline #718da3",
        "markdown.table.border": "#4d626e",
        "markdown.table.header": "bold #b9c5d4",
        "markdown.kbd": "bold #d6b879",
    },
    inherit=True,
)


def themed_markdown(markup: str, **kwargs: object) -> Markdown:
    """Build Rich Markdown using Symphony's syntax theme (not Rich's monokai default)."""
    kwargs.setdefault("code_theme", SYMPHONY_CODE_THEME)
    kwargs.setdefault("inline_code_theme", SYMPHONY_CODE_THEME)
    return Markdown(markup, **kwargs)  # type: ignore[arg-type]
