"""Image attachments for the coding-agent TUI."""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote, urlparse

from rich.style import Style
from rich.text import Text

from core_ai.content import IMAGE_MIME_BY_SUFFIX, image_part, normalize_content
from core_ai.types import Content


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
            media_type=IMAGE_MIME_TYPES.get(suffix, "image/png"),
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


def render_half_block(
    payload: bytes,
    *,
    max_width: int = 88,
    max_rows: int = 28,
) -> Text:
    """Render image bytes as a Unicode half-block preview."""
    if not payload:
        return Text("No image data to preview.", style="#888888")
    try:
        from PIL import Image
    except ImportError:
        return Text("Install Pillow to preview images in the terminal.", style="#888888")

    try:
        with Image.open(io.BytesIO(payload)) as source:
            image = _to_rgb(source)
            width, height = image.size
            scale = min(max_width / max(width, 1), (max_rows * 2) / max(height, 1))
            new_width = max(1, int(width * scale))
            new_height = max(2, int(height * scale))
            if new_height % 2:
                new_height += 1
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            pixels = image.load()
    except Exception as exc:  # noqa: BLE001
        return Text(f"Could not render image ({exc}).", style="#c67b82")

    preview = Text()
    for y in range(0, new_height, 2):
        for x in range(new_width):
            upper = pixels[x, y]
            lower = pixels[x, y + 1] if y + 1 < new_height else (13, 13, 13)
            preview.append(
                "▀",
                style=Style(color=_hex(upper), bgcolor=_hex(lower)),
            )
        preview.append("\n")
    return preview


def _to_rgb(image: object) -> object:
    from PIL import Image

    assert isinstance(image, Image.Image)
    if image.mode == "RGB":
        return image.copy()
    background = Image.new("RGB", image.size, (13, 13, 13))
    if image.mode in {"RGBA", "LA"}:
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image.convert("RGB")


def _hex(pixel: tuple[int, int, int]) -> str:
    return f"#{pixel[0]:02x}{pixel[1]:02x}{pixel[2]:02x}"


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
