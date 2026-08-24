"""generate_image tool timeline widget."""

from __future__ import annotations

from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual.widgets import Static

from coding_agent.tui.images import ImageAttachment
from coding_agent.tui.modal.image import ImageModal
from coding_agent.tui.widgets.tools.base import ToolCallWidget
from coding_agent.utils.text import clip_text

IMAGE_CHIP = "[Image 1]"


class ImageChipBody(Static):
    """Tool-result body that opens an image modal when clicked."""

    def action_open_image(self) -> None:
        self._open_owner_preview()

    def on_click(self, event: object) -> None:
        if self._open_owner_preview():
            stop = getattr(event, "stop", None)
            if callable(stop):
                stop()

    def _open_owner_preview(self) -> bool:
        node = self.parent
        while node is not None:
            method = getattr(node, "open_preview", None)
            if callable(method):
                return bool(method())
            node = node.parent
        return False


class GenerateImageWidget(ToolCallWidget):
    """Path-oriented generate_image card with a clickable `[Image 1]` preview."""

    def _make_body(self) -> Static:
        return ImageChipBody()

    def _tool_title(self) -> tuple[str, str]:
        return ("Image", "└")

    def _summary(self) -> str:
        return str(self.arguments.get("path") or self.raw_arguments)

    def _result_summary(self) -> str:
        if not self.result:
            return ""
        if self.result.startswith("error:"):
            return self.result
        return self.result.splitlines()[0]

    def set_result(self, result: object) -> None:
        super().set_result(result)
        if self.status == "done" and self.is_attached:
            self.collapsed = False

    def _body_rows(self) -> list[object]:
        rows: list[object] = []
        summary = clip_text(self._summary(), 300)
        if summary:
            rows.append(Text(summary, style="#a4a4a4"))
        if self.status == "failed":
            if self.result:
                rows.append(Text(f"└  {self.result}", style="#d66b73"))
            return rows
        if self.status == "done":
            chip = Text()
            chip.append(
                IMAGE_CHIP,
                style=Style(
                    color="#87b5b1",
                    bold=True,
                    underline=True,
                ),
            )

            detail = self._result_summary()
            if detail:
                chip.append(f"  {detail}", style="#666666")
            rows.append(chip)
        return rows

    def open_preview(self) -> bool:
        workspace = getattr(self.app, "workspace", None)
        path = str(self.arguments.get("path") or "")
        if workspace is None or not path or self.status == "failed":
            return False
        image = _attachment_from_workspace(Path(workspace), path)
        if image is None:
            return False
        self.app.push_screen(ImageModal(image))
        return True


def _attachment_from_workspace(workspace: Path, path: str) -> ImageAttachment | None:
    try:
        root = workspace.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return None
        return ImageAttachment.from_path(target, IMAGE_CHIP)
    except OSError:
        return None
