"""Details card for one finished tool call."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.content import Content
from textual.containers import Container, Horizontal
from textual.widgets import Input, Static

from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import CONTENT_MODAL_CSS
from coding_agent.tui.transcript.messages import SelectableStatic

if TYPE_CHECKING:
    from coding_agent.tui.tools.calls import ToolCallWidget

_FILE_TOKEN = re.compile(r"(?<!\S)([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)(?!\S)")
_CODE_SUFFIXES = {".py", ".js", ".ts", ".json", ".md", ".toml", ".yaml", ".yml", ".sh"}


TAB_META = "detail_view"


class DetailTabs(Static):
    """The drawer's view names. A click on one opens it.

    Clicks are read from a plain style key rather than an ``@click`` action,
    so Textual does not restyle the names as links.
    """

    def on_click(self, event: events.Click) -> None:
        index = event.style.meta.get(TAB_META)
        if isinstance(index, int) and isinstance(self.screen, ToolCallModal):
            event.stop()
            self.screen.action_show_view(index)


class ToolCallModal(ModalBase[None]):
    """A drawer with one finished tool call, opened from its transcript row.

    It docks to the right at full height, so the transcript stays in view.
    The header carries a status badge, the tool and its target, the request
    and its facts. Below it the call's views (Diff, Split, Output, Arguments,
    ...) switch with 1-9, Tab, or a click on their name.

    The drawer is rendered once when it opens. Live calls stay in the
    transcript and do not push updates into it, so a busy run cannot stall the
    UI by rebuilding it on every chunk.
    """

    BINDINGS = [
        ("slash", "focus_search", "Search"),
        ("w", "toggle_wrap", "Wrap"),
        ("y", "copy_detail", "Copy"),
        Binding("tab", "cycle_view(1)", "Next view", show=False, priority=True),
        Binding("shift+tab", "cycle_view(-1)", "Previous view", show=False, priority=True),
        *[Binding(str(number), f"show_view({number - 1})", show=False) for number in range(1, 10)],
    ]

    CSS = CONTENT_MODAL_CSS + """
    ToolCallModal { align: right top; background: rgba(0, 0, 0, 0.45); }
    ToolCallModal #content-pane {
        width: 76%;
        max-width: 160;
        height: 100%;
        padding: 0;
        border: none;
        border-left: outer #3d3d3d;
        background: #0b0b0b;
    }
    ToolCallModal #content-pane.status-done { border-left: outer #4f7a57; }
    ToolCallModal #content-pane.status-failed { border-left: outer #a8545b; }
    #detail-head { width: 100%; height: auto; padding: 1 2 0 2; background: #0b0b0b; }
    ToolCallModal #content-title { width: 1fr; height: auto; padding: 0; background: #0b0b0b; }
    ToolCallModal #modal-close { dock: none; width: auto; margin-left: 2; background: #0b0b0b; }
    /* What was asked: the command, the path or the query. */
    #tool-command { width: 100%; height: auto; padding: 1 2 0 2; color: #9a9a9a; background: #0b0b0b; }
    #tool-meta { width: 100%; height: auto; padding: 1 2 0 2; background: #0b0b0b; }
    #tool-jumps { height: 1; margin: 1 2 0 2; }
    .jump-chip { width: auto; height: 1; margin-right: 2; color: #87b5b1; }
    #detail-tabs {
        width: 100%;
        height: 2;
        margin-top: 1;
        padding: 0 2;
        border-bottom: solid #1f1f1f;
        background: #0b0b0b;
    }
    #tool-search { display: none; width: 100%; height: 1; margin: 1 2 0 2; }
    ToolCallModal #content-body { padding: 1 2 1 2; background: #0b0b0b; }
    #tool-detail { width: 100%; height: auto; background: #0b0b0b; }
    ToolCallModal .modal-footer {
        height: 2;
        padding: 1 2 0 2;
        border-top: solid #1f1f1f;
        background: #0b0b0b;
    }
    """

    def __init__(self, tool: ToolCallWidget) -> None:
        super().__init__()
        self.tool = tool
        self._wrap = False
        self._views = tool.detail_views()
        self._view = 0

    def compose(self):  # type: ignore[no-untyped-def]
        status = "failed" if self.tool.status == "failed" else "done"
        with Container(id="content-pane", classes=f"modal-pane status-{status}"):
            with Horizontal(id="detail-head"):
                yield Static(self._title(), id="content-title", markup=False)
                yield ModalCloseButton("Esc", id="modal-close")
            request = self.tool.detail_request()
            if request is not None:
                yield Static(request, id="tool-command", markup=False)
            facts = self._facts()
            if facts.plain:
                yield Static(facts, id="tool-meta", markup=False)
            chips = self._jump_targets()
            if chips:
                with Horizontal(id="tool-jumps"):
                    for path in chips:
                        yield Static(path, classes="jump-chip", markup=False)
            yield DetailTabs(self._tabs(), id="detail-tabs", markup=False)
            yield Input(placeholder="Search", id="tool-search")
            with ModalScroll(id="content-body", classes="modal-body"):
                yield SelectableStatic(self._body(), id="tool-detail", markup=False)
            yield Static(self._footer(), classes="modal-footer", markup=False)

    def on_mount(self) -> None:
        self.query_one(ModalScroll).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "tool-search":
            return
        query = event.value.strip().lower()
        body = self.query_one("#tool-detail", Static)
        if not query:
            body.update(self._body())
            return
        lines = self.tool.detail_plain().splitlines()
        matches = [line for line in lines if query in line.lower()]
        body.update(Text("\n".join(matches) or "No matches.", style="#d0d0d0"))

    def action_focus_search(self) -> None:
        search = self.query_one("#tool-search", Input)
        search.display = True
        search.focus()

    def action_toggle_wrap(self) -> None:
        self._wrap = not self._wrap
        self.query_one("#tool-detail", Static).update(self._body())

    def action_copy_detail(self) -> None:
        self.app.copy_to_clipboard(self.tool.detail_plain())
        self.app.notify("Copied tool details.")

    def action_show_view(self, index: int) -> None:
        if not 0 <= index < len(self._views) or index == self._view:
            return
        self._view = index
        self.query_one("#detail-tabs", Static).update(self._tabs())
        self.query_one("#tool-detail", Static).update(self._body())
        self.query_one(ModalScroll).scroll_home(animate=False)

    def action_cycle_view(self, step: int) -> None:
        self.action_show_view((self._view + step) % len(self._views))

    @property
    def view_name(self) -> str:
        return self._views[self._view][0]

    def _body(self) -> object:
        _name, rows = self._views[self._view]
        return Group(*(rows(self._wrap) or [Text("No details yet.", style="#686868")]))

    def _title(self) -> Content:
        """A status badge, then the tool and its target."""
        failed = self.tool.status == "failed"
        badge = (" FAILED " if failed else " DONE ", f"bold #0b0b0b on {'#d66b73' if failed else '#72a57a'}")
        return Content.assemble(badge, "  ", self.tool.detail_title())

    def _facts(self) -> Text:
        text = Text()
        for index, (fact, colour) in enumerate(self.tool.detail_facts()):
            if index:
                text.append("   ", style="#3d3d3d")
            text.append(fact, style=colour)
        return text

    def _tabs(self) -> Text:
        """The views as tabs: the open one lit, each with its number key; a click opens it."""
        text = Text()
        for index, (name, _rows) in enumerate(self._views):
            click = Style(meta={TAB_META: index})
            if index:
                text.append("  ")
            if index == self._view:
                text.append(f" {index + 1} {name} ", style=Style(color="#0b0b0b", bgcolor="#d0d0d0", bold=True) + click)
            else:
                text.append(f" {index + 1} ", style=Style(color="#5f5f5f") + click)
                text.append(f"{name} ", style=Style(color="#9a9a9a") + click)
        return text

    @staticmethod
    def _footer() -> Text:
        """Key hints as keycaps."""
        text = Text()
        for index, (key, action) in enumerate(
            (("Tab", "view"), ("↑↓", "scroll"), ("/", "search"), ("w", "wrap"), ("y", "copy"), ("Esc", "close"))
        ):
            if index:
                text.append("   ")
            text.append(f" {key} ", style="bold #d0d0d0 on #262626")
            text.append(f" {action}", style="#6e6e6e")
        return text

    def _jump_targets(self) -> tuple[str, ...]:
        workspace = self.tool.workspace
        if workspace is None:
            return ()
        candidates = [str(self.tool.arguments.get("path") or "")]
        candidates.extend(_FILE_TOKEN.findall(self.tool._summary()))
        found: list[str] = []
        root = workspace.resolve()
        for candidate in candidates:
            path = Path(candidate)
            if path.suffix.lower() not in _CODE_SUFFIXES or path.is_absolute():
                continue
            if (root / path).is_file() and candidate not in found:
                found.append(candidate)
            if len(found) == 4:
                break
        return tuple(found)
