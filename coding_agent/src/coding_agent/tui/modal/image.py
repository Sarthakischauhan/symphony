"""Large modal used to inspect a dropped image."""

from __future__ import annotations

import io

from rich.text import Text
from textual.containers import Container
from textual.widgets import Static

from coding_agent.tui.images import ImageAttachment, render_half_block
from coding_agent.tui.modal.base import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.styles.modal import IMAGE_MODAL_CSS


class ImageModal(ModalBase[None]):
    """Terminal image preview behind a compact `[Image N]` chip."""

    CSS = IMAGE_MODAL_CSS

    def __init__(self, attachment: ImageAttachment) -> None:
        super().__init__()
        self.attachment = attachment

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="content-pane", classes="modal-pane"):
            yield ModalCloseButton("×", id="modal-close")
            yield Static(self._title(), id="image-title")
            with ModalScroll(id="content-body", classes="modal-body"):
                yield Static(self._preview(), id="image-preview")
            yield Static("↑↓ scroll   ·   Esc close", classes="modal-footer")

    def _title(self) -> Text:
        title = Text()
        title.append(self.attachment.filename, style="bold #d0d0d0")
        details = self._details()
        if details:
            title.append(f"  ·  {details}", style="#686868")
        return title

    def _details(self) -> str:
        bits = [self.attachment.media_type]
        payload = self.attachment.decoded()
        size = _image_size(payload)
        if size is not None:
            bits.insert(0, f"{size[0]}×{size[1]}")
        return "  ·  ".join(bits)

    def _preview(self) -> Text:
        return render_half_block(self.attachment.decoded())


def _image_size(payload: bytes) -> tuple[int, int] | None:
    if not payload:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.size
    except Exception:  # noqa: BLE001
        return None
