"""Tests for the intentionally small coding-agent tool surface."""

from __future__ import annotations

import asyncio
import base64
import inspect
import time
from pathlib import Path

import pytest


from coding_agent.tools import (
    BashTool,
    GenerateImageTool,
    PatchTool,
    ReadFileTool,
    SearchTool,
    WriteFileArgs,
    WriteFileTool,
    build_tools,
    wrap_with_approvals,
)
from coding_agent.tools.approvals import approval_prompt
from coding_agent.tui.widgets import GenerateImageWidget
from coding_agent.tui.widgets import ReadFileWidget


from coding_agent.tools.bash import MAX_OUTPUT_BYTES
from core_harness import NullControlPlane

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
GIF_1X1 = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00"
    b"\x02\x02D\x01\x00;"
)


def test_tool_surface_is_small(tmp_path: Path) -> None:
    assert [tool.name for tool in build_tools(tmp_path)] == [
        "read_file", "write_file", "generate_image", "patch", "bash", "search", "ask_user"

    ]


def test_read_file_returns_image_parts_by_type(tmp_path: Path) -> None:
    png = tmp_path / "shot.png"
    png.write_bytes(PNG_1X1)
    gif = tmp_path / "anim.gif"
    gif.write_bytes(GIF_1X1)
    nameless = tmp_path / "screenshot"
    nameless.write_bytes(PNG_1X1)
    notes = tmp_path / "notes.py"
    notes.write_text("print(1)\n", encoding="utf-8")
    blob = tmp_path / "data.bin"
    blob.write_bytes(b"\xff\xfe\x00\x00not-an-image")

    tool = ReadFileTool(tmp_path)
    png_result = tool.run("shot.png")
    assert isinstance(png_result, list)
    assert png_result[0]["text"].startswith("Read image shot.png")
    assert png_result[1]["type"] == "image"
    assert png_result[1]["media_type"] == "image/png"
    assert png_result[1]["filename"] == "shot.png"

    gif_result = tool.run("anim.gif")
    assert gif_result[1]["media_type"] == "image/gif"

    sniffed = tool.run("screenshot")
    assert sniffed[1]["media_type"] == "image/png"

    assert tool.run("notes.py") == "print(1)\n"
    assert tool.run("data.bin").startswith("error: file is not valid UTF-8 text")

    wrapped = tool.as_harness_tool()
    executed = asyncio.run(wrapped.execute(control_plane=None, args={"path": "shot.png"}))
    assert isinstance(executed, list)
    assert executed[1]["type"] == "image"


def test_read_file_rejects_oversized_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "huge.png"
    image.write_bytes(PNG_1X1)
    monkeypatch.setattr("coding_agent.tools.read_file.MAX_IMAGE_BYTES", 1)
    result = ReadFileTool(tmp_path).run("huge.png")
    assert result.startswith("error: image exceeds")


def test_read_file_widget_summarizes_image_results() -> None:
    widget = ReadFileWidget("read-1", "read_file")
    widget.result = "Read image shot.gif (image/gif, 1,204 bytes)\n[image:shot.gif]"
    assert widget._result_summary() == "Read image shot.gif (image/gif, 1,204 bytes)"


def test_write_file_preserves_whitespace_through_validation(tmp_path: Path) -> None:
    args = WriteFileArgs.model_validate({"path": "  a.py  ", "content": "    x = 1\n\n"})
    assert args.path == "a.py"
    assert args.content == "    x = 1\n\n"
    tool = WriteFileTool(tmp_path).as_harness_tool()
    result = asyncio.run(tool.execute(control_plane=None, args=args.model_dump()))
    assert result.startswith("wrote a.py")
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "    x = 1\n\n"


def test_generate_image_writes_file_and_returns_image_parts(tmp_path: Path) -> None:
    async def fake_generate(prompt: str, output_format: str) -> tuple[bytes, str]:
        assert prompt == "a red square"
        assert output_format == "png"
        return PNG_1X1, "image/png"

    tool = GenerateImageTool(tmp_path, generate=fake_generate)
    result = asyncio.run(tool.run("a red square", "assets/icon.png"))
    assert isinstance(result, list)
    assert result[0]["text"].startswith("Wrote image assets/icon.png")
    assert result[1]["type"] == "image"
    assert result[1]["media_type"] == "image/png"
    assert result[1]["filename"] == "icon.png"
    written = tmp_path / "assets" / "icon.png"
    assert written.read_bytes() == PNG_1X1

    wrapped = tool.as_harness_tool()
    executed = asyncio.run(
        wrapped.execute(
            control_plane=None,
            args={"prompt": "a red square", "path": "assets/icon.png"},
        )
    )
    assert isinstance(executed, list)
    assert executed[1]["type"] == "image"


def test_generate_image_rejects_non_image_paths_and_missing_provider(tmp_path: Path) -> None:
    async def fake_generate(prompt: str, output_format: str) -> tuple[bytes, str]:
        del prompt, output_format
        return PNG_1X1, "image/png"

    tool = GenerateImageTool(tmp_path, generate=fake_generate)
    assert "path must end in" in asyncio.run(tool.run("a cat", "notes.txt"))
    assert "escapes workspace" in asyncio.run(tool.run("a cat", "../out.png"))

    class EmptyRegistry:
        async def generate_image(self, prompt: str, **kwargs: object) -> tuple[bytes, str]:
            del prompt, kwargs
            raise RuntimeError("image generation requires an OpenAI or Gemini provider")

    missing = GenerateImageTool(tmp_path, registry=EmptyRegistry())
    error = asyncio.run(missing.run("a cat", "cat.png"))
    assert error.startswith("error: image generation failed")
    assert "OpenAI or Gemini" in error
    assert not (tmp_path / "cat.png").exists()


def test_generate_image_widget_summarizes_and_opens_preview(tmp_path: Path) -> None:


    (tmp_path / "icon.png").write_bytes(PNG_1X1)
    widget = GenerateImageWidget("img-1", "generate_image")
    widget.set_arguments({"path": "icon.png", "prompt": "a red square"})
    widget.set_result("Wrote image icon.png (image/png, 70 bytes)\n[image:icon.png]")
    assert widget._summary() == "icon.png"
    assert widget._result_summary() == "Wrote image icon.png (image/png, 70 bytes)"
    rows = widget._body_rows()
    chip = rows[-1]
    assert "[Image 1]" in chip.plain



def test_generate_image_overwrite_asks_for_approval(tmp_path: Path) -> None:
    (tmp_path / "icon.png").write_bytes(PNG_1X1)
    needed, prompt = approval_prompt(
        "generate_image", {"path": "icon.png", "prompt": "a cat"}, tmp_path
    )
    assert needed
    assert "Overwrite" in prompt
    fresh, _ = approval_prompt(
        "generate_image", {"path": "new.png", "prompt": "a cat"}, tmp_path
    )
    assert not fresh



def test_search_content_literal_regex_and_glob(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("alpha text\n", encoding="utf-8")
    search = SearchTool(tmp_path)
    literal = search.run(query="alpha", glob="*.py")
    assert "a.py:1:def alpha():" in literal
    assert "b.txt" not in literal
    regex = search.run(query=r"return\s+\d", regex=True)
    assert "a.py:2:" in regex


def test_search_file_names(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    result = SearchTool(tmp_path).run(query="agent", mode="files")
    assert "agent.py" in result
    assert "notes.txt" not in result


def test_search_rejects_escape_and_bad_regex(tmp_path: Path) -> None:
    search = SearchTool(tmp_path)
    assert "escapes workspace" in search.run(query="x", path="../outside")
    assert search.run(query="[", regex=True).startswith("error: invalid regex")


def test_patch_keeps_unique_match_contract(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("x\nx\n", encoding="utf-8")
    patch = PatchTool(tmp_path)
    assert "matched 2 times" in patch.run("a.txt", "x", "y")
    assert patch.run("a.txt", "x", "y", replace_all=True).startswith("patched")
    assert path.read_text(encoding="utf-8") == "y\ny\n"


def test_bash_is_async_and_does_not_use_blocking_run() -> None:
    source = inspect.getsource(BashTool)
    assert "subprocess.run" not in source
    assert inspect.iscoroutinefunction(BashTool.run)


def test_bash_caps_and_times_out_without_blocking(tmp_path: Path) -> None:
    tool = BashTool(tmp_path).as_harness_tool()

    async def _run() -> None:
        capped = await tool.execute(
            control_plane=None,
            args={"command": "python3 -c \"print('x' * 80_000)\""},
        )
        assert "truncated" in capped
        assert len(capped.encode("utf-8")) < MAX_OUTPUT_BYTES + 200

        started = time.monotonic()
        timed_out = await tool.execute(
            control_plane=None,
            args={"command": "sleep 30", "timeout": 1},
        )
        assert "timed out" in timed_out
        assert time.monotonic() - started < 5

    asyncio.run(_run())


def test_bash_cancel_kills_process_group(tmp_path: Path) -> None:
    tool = BashTool(tmp_path).as_harness_tool()

    async def _run() -> None:
        task = asyncio.create_task(
            tool.execute(
                control_plane=None,
                args={"command": "sleep 30", "timeout": 30},
            )
        )
        await asyncio.sleep(0.15)
        task.cancel()
        started = time.monotonic()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert time.monotonic() - started < 2

    asyncio.run(_run())


def test_approvals_allow_once_and_deny(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("old", encoding="utf-8")
    needed, prompt = approval_prompt("bash", {"command": "ls"}, tmp_path)
    assert needed
    assert "ls" in prompt
    overwrite, overwrite_prompt = approval_prompt(
        "write_file", {"path": "existing.txt"}, tmp_path
    )
    assert overwrite
    assert "Overwrite" in overwrite_prompt
    broad, _ = approval_prompt(
        "patch",
        {"path": "existing.txt", "old_str": "x" * 500, "new_str": "y", "replace_all": False},
        tmp_path,
    )
    assert broad
    surgical, _ = approval_prompt(
        "patch",
        {"path": "existing.txt", "old_str": "old", "new_str": "new", "replace_all": False},
        tmp_path,
    )
    assert not surgical

    class AskingPlane(NullControlPlane):
        def __init__(self, answer: str) -> None:
            super().__init__()
            self.answer = answer

        async def ask_user(self, request_id: str) -> str:
            del request_id
            return self.answer

    wrapped = wrap_with_approvals([BashTool(tmp_path).as_harness_tool()], tmp_path)

    async def _run() -> None:
        denied = await wrapped[0].execute(
            control_plane=AskingPlane("Deny"),
            args={"command": "echo hi"},
        )
        allowed = await wrapped[0].execute(
            control_plane=AskingPlane("Allow once"),
            args={"command": "echo hi"},
        )
        skipped = await wrapped[0].execute(
            control_plane=NullControlPlane(),
            args={"command": "echo hi"},
        )
        assert denied.startswith("error: tool call denied")
        assert "hi" in allowed
        assert "hi" in skipped

    asyncio.run(_run())
