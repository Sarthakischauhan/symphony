from __future__ import annotations

import base64
from pathlib import Path

from coding_agent.tui.images import (
    ImageAttachment,
    build_user_content,
    display_from_content,
    dropped_image_paths,
    render_half_block,
)


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _write_png(path: Path, name: str = "shot.png") -> Path:
    image = path / name
    image.write_bytes(PNG_1X1)
    return image


def test_dropped_image_paths_detects_quoted_and_file_urls(tmp_path: Path) -> None:
    shot = _write_png(tmp_path, "my shot.png")
    other = _write_png(tmp_path, "other.png")
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")

    assert dropped_image_paths(f'"{shot}"\n') == [shot.resolve()]
    assert dropped_image_paths(f"file://{shot}") == [shot.resolve()]
    assert dropped_image_paths(f'"{shot}" "{other}"') == [shot.resolve(), other.resolve()]
    assert dropped_image_paths(f"{shot}\n{other}") == [shot.resolve(), other.resolve()]
    assert dropped_image_paths(str(notes)) == []
    assert dropped_image_paths(f"please look at {shot}") == []
    assert dropped_image_paths("just a sentence") == []


def test_build_user_content_keeps_string_without_images() -> None:
    assert build_user_content("hello", ()) == "hello"


def test_build_user_content_interleaves_markers(tmp_path: Path) -> None:
    shot = _write_png(tmp_path)
    image = ImageAttachment.from_path(shot, "[Image 1]")
    content = build_user_content("Look at [Image 1] please", (image,))
    assert content[0] == {"type": "text", "text": "Look at "}
    assert content[1]["type"] == "image"
    assert content[1]["filename"] == "shot.png"
    assert content[1]["data"] == base64.b64encode(PNG_1X1).decode("ascii")
    assert content[2] == {"type": "text", "text": " please"}


def test_display_from_content_rebuilds_clickable_markers() -> None:
    content = [
        {"type": "text", "text": "Look at "},
        {
            "type": "image",
            "media_type": "image/png",
            "data": "aaa",
            "filename": "shot.png",
        },
        {"type": "text", "text": "please"},
    ]
    text, images = display_from_content(content)
    assert text == "Look at [Image 1] please"
    assert images[0].filename == "shot.png"
    assert images[0].marker == "[Image 1]"


def test_half_block_preview_renders_unicode_blocks() -> None:
    preview = render_half_block(PNG_1X1, max_width=8, max_rows=4)
    assert "▀" in preview.plain
