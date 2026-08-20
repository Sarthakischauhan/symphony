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


# The palette is kept in one place so Rich content and Textual CSS can be
# changed together.  These are the semantic tokens from the Symphony dark
# theme (rather than terminal colour names, which vary by terminal).
SYMPHONY_COLORS = {
    "background": "#0A0A0A",
    "foreground": "#EDEDED",
    "comment": "#737373",
    "keyword": "#db6767",
    "type_keywords": "#db6767",
    "string": "#799e7c",
    "function": "#6374d0",
    "variable": "#EDEDED",
    "number": "#d08a61",
    "operator": "#6b6b6b",
    "punctuation": "#525252",
    "type": "#cda059",
    "tag": "#5a9a95",
    "attribute": "#8ca0cc",
    "constant": "#d08a61",
    "surface": "#171717",
    "overlay": "#262626",
    "subtext": "#A3A3A3",
}


class SymphonyCodeStyle(Style):
    """Syntax palette for the active Symphony dark theme."""

    background_color = SYMPHONY_COLORS["background"]
    highlight_color = SYMPHONY_COLORS["overlay"]
    line_number_color = SYMPHONY_COLORS["comment"]
    line_number_background_color = SYMPHONY_COLORS["background"]
    line_number_special_color = SYMPHONY_COLORS["foreground"]
    line_number_special_background_color = SYMPHONY_COLORS["overlay"]

    styles = {
        Text: SYMPHONY_COLORS["foreground"],
        Text.Whitespace: SYMPHONY_COLORS["punctuation"],
        Comment: "italic " + SYMPHONY_COLORS["comment"],
        Comment.Preproc: SYMPHONY_COLORS["comment"],
        Keyword: SYMPHONY_COLORS["keyword"],
        Keyword.Type: SYMPHONY_COLORS["type_keywords"],
        Operator: SYMPHONY_COLORS["operator"],
        Punctuation: SYMPHONY_COLORS["punctuation"],
        Name: SYMPHONY_COLORS["variable"],
        Name.Builtin: SYMPHONY_COLORS["constant"],
        Name.Class: "bold " + SYMPHONY_COLORS["type"],
        Name.Decorator: SYMPHONY_COLORS["attribute"],
        Name.Exception: SYMPHONY_COLORS["keyword"],
        Name.Function: SYMPHONY_COLORS["function"],
        Name.Namespace: SYMPHONY_COLORS["type"],
        Name.Tag: SYMPHONY_COLORS["tag"],
        Name.Variable: SYMPHONY_COLORS["variable"],
        String: SYMPHONY_COLORS["string"],
        String.Doc: "italic " + SYMPHONY_COLORS["comment"],
        Number: SYMPHONY_COLORS["number"],
        Generic.Deleted: SYMPHONY_COLORS["keyword"] + " bg:" + SYMPHONY_COLORS["overlay"],
        Generic.Inserted: SYMPHONY_COLORS["string"] + " bg:" + SYMPHONY_COLORS["surface"],
        Generic.Heading: "bold " + SYMPHONY_COLORS["foreground"],
        Generic.Subheading: SYMPHONY_COLORS["subtext"],
        Error: SYMPHONY_COLORS["keyword"] + " bg:" + SYMPHONY_COLORS["overlay"],
    }


SYMPHONY_CODE_THEME = PygmentsSyntaxTheme(SymphonyCodeStyle)

SYMPHONY_RICH_THEME = Theme(
    {
        "markdown.paragraph": SYMPHONY_COLORS["foreground"],
        "markdown.text": SYMPHONY_COLORS["foreground"],
        "markdown.h1": "bold " + SYMPHONY_COLORS["foreground"],
        "markdown.h2": "bold " + SYMPHONY_COLORS["attribute"],
        "markdown.h3": "bold " + SYMPHONY_COLORS["tag"],
        "markdown.h4": "italic " + SYMPHONY_COLORS["subtext"],
        "markdown.h5": "italic " + SYMPHONY_COLORS["comment"],
        "markdown.h6": "dim " + SYMPHONY_COLORS["comment"],
        "markdown.block_quote": SYMPHONY_COLORS["string"],
        "markdown.list": SYMPHONY_COLORS["foreground"],
        "markdown.item.bullet": "bold " + SYMPHONY_COLORS["function"],
        "markdown.item.number": SYMPHONY_COLORS["function"],
        "markdown.code": "bold " + SYMPHONY_COLORS["tag"],
        "markdown.link": SYMPHONY_COLORS["function"],
        "markdown.link_url": "underline " + SYMPHONY_COLORS["attribute"],
        "markdown.table.border": SYMPHONY_COLORS["punctuation"],
        "markdown.table.header": "bold " + SYMPHONY_COLORS["attribute"],
        "markdown.kbd": "bold " + SYMPHONY_COLORS["type"],
    },
    inherit=True,
)


def themed_markdown(markup: str, **kwargs: object) -> Markdown:
    """Build Rich Markdown using Symphony's syntax theme (not Rich's monokai default)."""
    kwargs.setdefault("code_theme", SYMPHONY_CODE_THEME)
    kwargs.setdefault("inline_code_theme", SYMPHONY_CODE_THEME)
    return Markdown(markup, **kwargs)  # type: ignore[arg-type]
