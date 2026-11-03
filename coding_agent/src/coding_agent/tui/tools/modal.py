"""Details card for one finished tool call."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Group
from rich.text import Text
from textual.containers import Container, Horizontal
from textual.widgets import Input, Static

from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import CONTENT_MODAL_CSS
from coding_agent.tui.transcript.messages import SelectableStatic

if TYPE_CHECKING:
    from coding_agent.tui.tools.calls import ToolCallWidget

_FILE_TOKEN = re.compile(r"(?<!\S)([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)(?!\S)")
_CODE_SUFFIXES = {".py", ".js", ".ts", ".json", ".md", ".toml", ".yaml", ".yml", ".sh"}


class ToolCallModal(ModalBase[None]):
    """A snapshot of one finished tool call, opened from its transcript row.

    The card is rendered once when it opens. Live calls stay in the transcript
    and do not push updates into this modal, so a busy run cannot stall the UI
    by rebuilding a card on every chunk.
    """

    BINDINGS = [("slash", "focus_search", "Search"), ("w", "toggle_wrap", "Wrap"), ("y", "copy_detail", "Copy")]

    CSS = CONTENT_MODAL_CSS + """
    ToolCallModal { align: center middle; background: rgba(0, 0, 0, 0.52); }
    #tool-meta, #tool-command, #tool-detail { width: 100%; height: auto; background: #0d0d0d; }
    #tool-detail { padding: 1 2; }
    #tool-search { display: none; width: 100%; height: 1; }
    .jump-chip { width: auto; height: 1; margin-right: 1; color: #87b5b1; }
    """

    def __init__(self, tool: ToolCallWidget) -> None:
        super().__init__()
        self.tool = tool
        self._wrap = False

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="content-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            yield Static(self.tool.detail_title(), id="content-title", markup=False)
            yield Static(self._meta(), id="tool-meta", markup=False)
            command = self.tool._summary()
            if command:
                yield Static(command, id="tool-command", markup=False)
            chips = self._jump_targets()
            if chips:
                with Horizontal(id="tool-jumps"):
                    for path in chips:
                        yield Static(path, classes="jump-chip", markup=False)
            yield Input(placeholder="Search", id="tool-search")
            with ModalScroll(id="content-body", classes="modal-body"):
                yield SelectableStatic(self._body(), id="tool-detail", markup=False)
            yield Static("↑↓ scroll   ·   / search   ·   w wrap   ·   y copy   ·   Esc close", classes="modal-footer")

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

    def _body(self) -> object:
        rows = self.tool.detail_rows(wrap=self._wrap) or [Text("No details yet.", style="#686868")]
        return Group(*rows)

    def _meta(self) -> str:
        lines = len(self.tool.detail_plain().splitlines())
        timeout = self.tool.arguments.get("timeout")
        parts = [f"{lines} lines"]
        if timeout:
            parts.insert(0, f"timeout {timeout}s")
        return "  ·  ".join(parts)

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
