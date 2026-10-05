"""Image attachments for the coding-agent TUI."""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote, urlparse

from rich.text import Text
from textual.containers import Container
from textual.widget import Widget
from textual.widgets import Static

from core_ai.content import IMAGE_MIME_BY_SUFFIX, image_part, normalize_content, sniff_image_media_type
from core_ai.types import Content
from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import IMAGE_MODAL_CSS


IMAGE_MARKER_RE = re.compile(r"\[Image (\d+)\]")
IMAGE_EXTENSIONS = set(IMAGE_MIME_BY_SUFFIX)
IMAGE_MIME_TYPES = IMAGE_MIME_BY_SUFFIX


@dataclass(frozen=True)
class ImageAttachment:
    """One dropped or restored image, referenced in the composer as `[Image N]`."""

    marker: str
    filename: str
    media_type: str
    data: str
    path: str | None = None

    @property
    def number(self) -> str:
        match = IMAGE_MARKER_RE.fullmatch(self.marker)
        return match.group(1) if match else self.marker

    def to_part(self) -> dict[str, str]:
        return image_part(
            media_type=self.media_type,
            data=self.data,
            filename=self.filename,
        )

    def decoded(self) -> bytes:
        return base64.b64decode(self.data) if self.data else b""

    @classmethod
    def from_path(cls, path: Path, marker: str) -> "ImageAttachment":
        payload = path.read_bytes()
        suffix = path.suffix.lower()
        return cls(
            marker=marker,
            filename=path.name,
            media_type=sniff_image_media_type(payload, filename=path.name) or IMAGE_MIME_TYPES.get(suffix, "image/png"),
            data=base64.b64encode(payload).decode("ascii"),
            path=str(path),
        )

    @classmethod
    def from_part(cls, part: dict[str, object], marker: str) -> "ImageAttachment":
        return cls(
            marker=marker,
            filename=str(part.get("filename") or "image"),
            media_type=str(part.get("media_type") or "image/png"),
            data=str(part.get("data") or ""),
        )


def dropped_image_paths(text: str) -> list[Path]:
    """Return image files when the entire paste is one or more dropped paths."""
    stripped = text.strip()
    if not stripped:
        return []
    single = _resolve_image_path(stripped)
    if single is not None:
        return [single]
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) > 1:
        paths = [_resolve_image_path(line) for line in lines]
        if all(path is not None for path in paths):
            return [path for path in paths if path is not None]
        return []
    tokens = _split_path_tokens(stripped)
    if not tokens:
        return []
    paths = []
    for token in tokens:
        path = _resolve_image_path(token)
        if path is None:
            return []
        paths.append(path)
    return paths


def build_user_content(text: str, images: Sequence[ImageAttachment]) -> Content:
    """Turn composer text plus `[Image N]` attachments into canonical content."""
    active = [image for image in images if image.marker in text]
    if not active:
        return text
    parts: list[dict[str, object]] = []
    remaining = text
    for image in active:
        before, _marker, remaining = remaining.partition(image.marker)
        if before:
            parts.append({"type": "text", "text": before})
        parts.append(image.to_part())
    if remaining:
        parts.append({"type": "text", "text": remaining})
    return parts


def display_from_content(content: Content) -> tuple[str, tuple[ImageAttachment, ...]]:
    """Rebuild composer-style text and attachments from a stored message body."""
    if isinstance(content, str) or content is None:
        return content or "", ()
    chunks: list[str] = []
    images: list[ImageAttachment] = []
    for part in normalize_content(content):
        if part["type"] == "text":
            text = str(part.get("text") or "")
            if text:
                chunks.append(text)
            continue
        marker = f"[Image {len(images) + 1}]"
        images.append(ImageAttachment.from_part(part, marker))
        if chunks and not chunks[-1].endswith((" ", "\n", "\t")):
            chunks.append(" ")
        chunks.append(marker)
        chunks.append(" ")
    return "".join(chunks).strip(), tuple(images)


def textual_image(payload: bytes, *, widget_id: str | None = None) -> Widget:
    """Render image bytes with textual-image, which picks the terminal's best protocol."""
    from textual_image.widget import Image as TextualImage

    image = TextualImage(io.BytesIO(payload) if payload else None, id=widget_id)
    image.styles.max_width = 88
    image.styles.max_height = 28
    return image


def _split_path_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if char == "\\" and index + 1 < len(text) and text[index + 1] == " ":
            current.append(" ")
            index += 2
            continue
        if char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            index += 1
            continue
        current.append(char)
        index += 1
    if quote:
        return []
    if current:
        tokens.append("".join(current))
    return tokens


def _resolve_image_path(token: str) -> Path | None:
    raw = token.strip().replace("\\ ", " ")
    if not raw or "\n" in raw or "\r" in raw or len(raw) > 1024:
        return None
    if raw.startswith("file://"):
        raw = unquote(urlparse(raw).path)
    path = Path(raw).expanduser()
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    try:
        path = path.resolve()
        if not path.is_file():
            return None
    except OSError:
        return None
    return path


class ImageModal(ModalBase[None]):
    """Terminal image preview behind a compact `[Image 1]` chip."""

    CSS = IMAGE_MODAL_CSS

    def __init__(self, attachment: ImageAttachment) -> None:
        super().__init__()
        self.attachment = attachment

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="content-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            yield Static(self._title(), id="image-title")
            with ModalScroll(id="content-body", classes="modal-body"):
                yield textual_image(self.attachment.decoded(), widget_id="image-preview")
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
