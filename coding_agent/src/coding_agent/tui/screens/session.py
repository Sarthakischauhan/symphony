"""Inspector for all durable session artifacts, including archived images."""

from __future__ import annotations

from pathlib import Path

from textual.containers import Container
from textual.widgets import Static

from coding_agent.persistence.presentation import session_images
from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import CONTENT_MODAL_CSS
from coding_agent.tui.tools.images import ImageAttachment, render_half_block


class SessionModal(ModalBase[None]):
    CSS = CONTENT_MODAL_CSS

    def __init__(self, report: str, root: Path | None = None) -> None:
        super().__init__()
        self.report = report
        self.root = root

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="content-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            yield Static("Session archive", id="content-title")
            with ModalScroll(id="content-body", classes="modal-body"):
                yield Static(self.report, markup=False)
                for index, path in enumerate(session_images(self.root) if self.root else [], 1):
                    yield Static(f"Image {index} · {path.name}", markup=False)
                    try:
                        image = ImageAttachment.from_path(path, f"[Image {index}]")
                        yield Static(render_half_block(image.decoded()))
                    except OSError:
                        yield Static("Image is unavailable.")
            yield Static("↑↓ scroll   ·   Esc close", classes="modal-footer")
