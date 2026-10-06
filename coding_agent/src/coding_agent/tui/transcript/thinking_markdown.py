"""Markdown for thinking text: muted block rendering and one-line previews.

Thinking is rendered into plain Rich ``Text`` (wrapped in a ``Group`` and
grids for lists) rather than Rich's ``Markdown`` renderable or Textual's
``Markdown`` widget. ``Text`` carries only emphasis (bold, italic, strike,
underline) and inherits the widget's CSS colour, so the muted thinking tone
comes from theme.toml instead of Rich's ``markdown.*`` palette. It also costs
one markdown-it parse per paint, with no child widgets to mount.

Thinking streams token by token, so ``render_thinking(..., streaming=True)``
first closes a dangling ``**``/``*``/backtick in the last paragraph: a
half-written ``**Tracing the`` renders bold instead of showing raw asterisks,
and the real closing marker replaces the synthetic one on the next chunk.

Streaming renders freeze every top-level block except the unfinished tail.
Later chunks reuse that frozen renderable and parse only the tail, matching
the stable-checkpoint approach used by Grok's streaming Markdown renderer.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.style import Style
from rich.table import Table
from rich.text import Text

PARSER = MarkdownIt("commonmark").enable("strikethrough")
FENCE_LINE = re.compile(r"^[ \t]{0,3}(?:```|~~~)", re.MULTILINE)
BULLETS = ("•", "◦", "▪")
QUOTE_BAR = "│"
RULE = "───"
CODE_BLOCK_INDENT = 2
PLAIN = Style()
BOLD = Style(bold=True)
ITALIC = Style(italic=True)
STRIKE = Style(strike=True)
LINK = Style(underline=True)
HEADING = Style(bold=True)
TOP_HEADING = Style(bold=True, underline=True)
BLOCK_SEPARATOR = " · "


def close_dangling_markers(source: str) -> str:
    """Close or drop emphasis/code markers left open by a partial stream.

    Only the last paragraph is scanned: earlier paragraphs are complete, and
    an open code fence is left alone because markdown-it already renders an
    unclosed fence up to the end of the text.
    """
    if len(FENCE_LINE.findall(source)) % 2:
        return source
    length = len(source)
    index = source.rfind("\n\n") + 1
    opened: list[tuple[str, int]] = []
    code_marker = ""
    code_at = -1
    while index < length:
        character = source[index]
        if character == "\\":
            index += 2
            continue
        if character in "`*":
            run = len(source[index:]) - len(source[index:].lstrip(character))
            if character == "`":
                if code_at < 0:
                    code_marker, code_at = source[index : index + run], index
                elif run == len(code_marker):
                    code_marker, code_at = "", -1
            elif code_at < 0:
                before = source[index - 1] if index else " "
                # A run at the very end is a marker still being typed: treat
                # it as an opener so the empty emphasis is dropped below.
                after = source[index + run] if index + run < length else character
                for marker in ("**",) * (run // 2) + ("*",) * (run % 2):
                    if opened and opened[-1][0] == marker and not before.isspace():
                        opened.pop()
                    elif not after.isspace():
                        opened.append((marker, index))
            index += run
            continue
        index += 1
    if code_at >= 0:
        opened.append((code_marker, code_at))
    closed = source
    for marker, position in reversed(opened):
        if closed[position + len(marker) :].strip():
            closed = closed.rstrip() + marker
        else:
            closed = closed[:position].rstrip()
    return closed


class StreamingThinkingRenderer:
    """Freeze stable top-level blocks and reparse only the unfinished tail."""

    def __init__(self) -> None:
        self._source = ""
        self._style: Style | None = None
        self._frozen = Group()
        self._frozen_end = 0
        self._scan_start = 0
        self._group: Group | None = None
        self._group_tail = ""

    def render(self, source: str, *, code_style: Style) -> RenderableType:
        if not source.startswith(self._source[: self._frozen_end]) or code_style != self._style:
            self._source = ""
            self._style = code_style
            self._frozen = Group()
            self._frozen_end = 0
            self._scan_start = 0
            self._group = None
            self._group_tail = ""
        self._source = source
        text = close_dangling_markers(source)
        frozen_end, self._scan_start = _stable_prefix_end(source, text, self._scan_start)
        if frozen_end < self._frozen_end:
            self._frozen = Group()
            self._frozen_end = 0
        if frozen_end > self._frozen_end:
            added = SyntaxTreeNode(PARSER.parse(source[self._frozen_end:frozen_end])).children
            rendered = render_blocks(added, code_style, depth=0, loose=True)
            if self._frozen.renderables and rendered:
                self._frozen.renderables.append(Text())
            self._frozen.renderables.extend(rendered)
            self._frozen_end = frozen_end
        tail = text[self._frozen_end :]
        if self._group is not None and tail == self._group_tail:
            return self._group
        tail_blocks = SyntaxTreeNode(PARSER.parse(tail)).children if tail.strip() else []
        rendered_tail = render_blocks(tail_blocks, code_style, depth=0, loose=True)
        blocks = list(self._frozen.renderables)
        if blocks and rendered_tail:
            blocks.append(Text())
        self._group_tail = tail
        self._group = Group(*blocks, *rendered_tail) if blocks or rendered_tail else Group(Text(" "))
        return self._group


def render_thinking(source: str, *, code_style: Style, streaming: bool) -> RenderableType:
    """Render thinking markdown as emphasis-only Text blocks in the widget's colour."""
    text = close_dangling_markers(source) if streaming else source
    root = SyntaxTreeNode(PARSER.parse(text))
    rendered = render_blocks(root.children, code_style, depth=0, loose=True)
    return Group(*rendered) if rendered else Text(" ")


def _stable_prefix_end(source: str, display_text: str, scan_start: int) -> tuple[int, int]:
    """Return the frozen byte end and where the next tail scan can resume.

    Nested blocks are not checkpoints because their container can continue.
    A display-only closing marker means the final paragraph is unfinished.
    ``scan_start`` advances with the stream, so each update scans only the
    newly closed tail rather than the whole thought.
    """
    if display_text != source or len(FENCE_LINE.findall(source)) % 2:
        return 0, 0
    start = _checkpoint_scan_start(source, scan_start)
    if start == 0:
        return 0, 0
    tokens = PARSER.parse(source[start:])
    closed = [token for token in tokens if token.level == 0 and token.map and token.nesting == 0]
    if len(closed) < 2:
        return start, start
    keep = len(closed) - 1 if _tail_can_extend(closed[-1]) else len(closed)
    if keep < 1:
        return start, start
    lines = source[start:].splitlines(keepends=True)
    frozen = start + sum(len(line) for line in lines[: closed[keep - 1].map[1]])
    # An open container must stay inside the next scan. Advancing past it made
    # every following block unfreezable.
    return frozen, start if keep < len(closed) else frozen


def _tail_can_extend(token: object) -> bool:
    """A following paragraph can continue these top-level containers."""
    return getattr(token, "type", "") in {
        "bullet_list_close",
        "ordered_list_close",
        "blockquote_close",
    }


def _checkpoint_scan_start(source: str, scan_start: int) -> int:
    """Return the newest paragraph boundary followed by another closed block."""
    cursor = scan_start
    start = scan_start
    while True:
        found = source.find("\n\n", cursor)
        if found < 0:
            return start
        nxt = found + 2
        if "\n\n" in source[nxt:]:
            start = nxt
        cursor = nxt


def render_blocks(
    nodes: list[SyntaxTreeNode], code_style: Style, *, depth: int, loose: bool
) -> list[RenderableType]:
    """Render sibling blocks, with a blank row between them when ``loose``."""
    rendered: list[RenderableType] = []
    for node in nodes:
        if rendered and loose:
            rendered.append(Text())
        rendered.append(render_block(node, code_style, depth=depth))
    return rendered


def render_block(node: SyntaxTreeNode, code_style: Style, *, depth: int) -> RenderableType:
    match node.type:
        case "paragraph":
            return render_inline(node.children, code_style, PLAIN)
        case "heading":
            style = TOP_HEADING if node.tag == "h1" else HEADING
            return render_inline(node.children, code_style, style)
        case "bullet_list" | "ordered_list":
            return render_list(node, code_style, depth=depth)
        case "blockquote":
            grid = Table.grid(expand=True, padding=0)
            grid.add_column(width=2, no_wrap=True)
            grid.add_column(ratio=1)
            body = render_blocks(node.children, code_style, depth=depth, loose=True)
            grid.add_row(Text(QUOTE_BAR), Group(*body))
            return grid
        case "fence" | "code_block":
            code = Text(node.content.rstrip("\n"), style=code_style)
            return Padding(code, (0, 0, 0, CODE_BLOCK_INDENT))
        case "hr":
            return Text(RULE)
        case _:
            return Text(node.content.rstrip("\n"))


def render_list(node: SyntaxTreeNode, code_style: Style, *, depth: int) -> Table:
    """A list as a grid so wrapped item text hangs under the item, not the marker."""
    if node.type == "ordered_list":
        start = int(node.attrs.get("start", 1))
        markers = [f"{start + offset}." for offset in range(len(node.children))]
    else:
        markers = [BULLETS[depth % len(BULLETS)]] * len(node.children)
    grid = Table.grid(expand=True, padding=0)
    grid.add_column(width=max(len(marker) for marker in markers) + 1, no_wrap=True)
    grid.add_column(ratio=1)
    for marker, item in zip(markers, node.children):
        loose = any(not child.hidden for child in item.children if child.type == "paragraph")
        body = render_blocks(item.children, code_style, depth=depth + 1, loose=loose)
        grid.add_row(Text(marker), Group(*body))
    return grid


def render_inline(nodes: list[SyntaxTreeNode], code_style: Style, style: Style) -> Text:
    """Render a block's inline children (markdown-it wraps them in one ``inline`` node)."""
    text = Text(style=style)
    for node in nodes:
        append_inline(text, node, code_style, PLAIN)
    return text


def append_inline(text: Text, node: SyntaxTreeNode, code_style: Style, style: Style) -> None:
    match node.type:
        case "inline":
            for child in node.children:
                append_inline(text, child, code_style, style)
        case "strong" | "em" | "s" | "link" | "image":
            emphasis = {"strong": BOLD, "em": ITALIC, "s": STRIKE}.get(node.type, LINK)
            for child in node.children:
                append_inline(text, child, code_style, style + emphasis)
        case "code_inline":
            text.append(node.content, style=style + code_style)
        case "softbreak" | "hardbreak":
            text.append("\n")
        case _:
            text.append(node.content, style=style)


def thinking_plain_text(source: str) -> str:
    """Thinking markdown as one line of plain text, every marker stripped.

    Blocks (headings, paragraphs, list items, code) are joined with `` · `` so
    a bold lead-in such as ``**Checking the caller**`` stays apart from the
    prose after it.
    """
    blocks = (" ".join(block.split()) for block in plain_blocks(SyntaxTreeNode(PARSER.parse(source))))
    return BLOCK_SEPARATOR.join(block for block in blocks if block)


def plain_blocks(node: SyntaxTreeNode) -> Iterator[str]:
    if node.type == "inline":
        yield "".join(plain_inline(child) for child in node.children)
    elif node.children:
        for child in node.children:
            yield from plain_blocks(child)
    else:
        yield node.content


def plain_inline(node: SyntaxTreeNode) -> str:
    if node.type in {"softbreak", "hardbreak"}:
        return " "
    if node.children:
        return "".join(plain_inline(child) for child in node.children)
    return node.content
