"""Enter-animation tests for the coding-agent TUI."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.geometry import Region
from textual.strip import Strip

from coding_agent.tui.animation import (
    apply_horizontal_wipe,
    play_fade_enter,
    play_wipe_enter,
    wipe_alpha,
)
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.commands import command_matches
from coding_agent.tui.slash_menu import SlashMenu
from coding_agent.tui.widgets import AssistantMessage, UserMessage, Welcome
from coding_agent.tui.widgets.status import ProcessComplete


def test_wipe_alpha_is_hidden_then_reveals_left_to_right() -> None:
    width = 20
    assert wipe_alpha(0, width, 0.0) == 0.0
    assert wipe_alpha(width - 1, width, 0.0) == 0.0
    assert wipe_alpha(0, width, 1.0) == 1.0
    assert wipe_alpha(width - 1, width, 1.0) == 1.0

    mid = 0.45
    left = wipe_alpha(1, width, mid)
    right = wipe_alpha(width - 1, width, mid)
    assert left > right
    assert left > 0.5
    assert right < 0.2


def test_apply_horizontal_wipe_fades_left_side_first() -> None:
    style = Style(color="#ffffff")
    strip = Strip([Segment("ABCDEFGHIJ", style)], 10)
    background = Color(0, 0, 0)

    hidden = apply_horizontal_wipe(strip, 0.0, background=background)
    assert hidden.text.strip() == ""

    shown = apply_horizontal_wipe(strip, 1.0, background=background)
    assert shown.text == "ABCDEFGHIJ"

    partial = apply_horizontal_wipe(strip, 0.4, background=background)

    def _brightness(segment: Segment) -> float:
        cell_style = segment.style
        if cell_style is None or cell_style.color is None:
            return 0.0
        color = Color.from_rich_color(cell_style.color)
        return (color.r + color.g + color.b) / 3

    left = _brightness(partial._segments[0])
    right = _brightness(partial._segments[-1])
    assert left > right


def test_welcome_and_user_message_wipe_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            welcome = Welcome(tmp_path)
            animated: list[str] = []
            original = welcome.animate

            def _capture(attribute: str, value: object, **kwargs: object) -> None:
                animated.append(attribute)
                original(attribute, value, **kwargs)

            welcome.animate = _capture  # type: ignore[method-assign]
            app.mount_transcript(welcome)
            await pilot.pause()
            assert "wipe_progress" in animated
            await pilot.wait_for_scheduled_animations()
            assert welcome.wipe_progress == pytest.approx(1.0)

            message = UserMessage("Add a left-to-right wipe")
            app.mount_transcript(message)
            await pilot.wait_for_scheduled_animations()
            assert message.wipe_progress == pytest.approx(1.0)

            message.wipe_progress = 0.35
            crop = Region(0, 0, message.size.width, max(message.size.height, 1))
            lines = message.render_lines(crop)
            assert lines
            first = lines[0]
            left = first.crop(0, min(4, first.cell_length))
            right = first.crop(max(first.cell_length - 4, 0), first.cell_length)
            assert _strip_brightness(left) > _strip_brightness(right)

    asyncio.run(_run())


def test_assistant_streaming_does_not_replay_enter_wipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.set_assistant("Hello", new=True)
            await pilot.wait_for_scheduled_animations()
            assistant = app.query_one(AssistantMessage)
            assert assistant.wipe_progress == pytest.approx(1.0)

            app.set_assistant("Hello, here is more text", new=False)
            assert assistant.wipe_progress == pytest.approx(1.0)
            assert "Hello, here is more text" in assistant.message_text

    asyncio.run(_run())


def test_enter_animation_is_skipped_when_animations_are_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.animation_level = "none"
            message = UserMessage("quiet")
            app.mount_transcript(message)
            await pilot.pause()
            play_wipe_enter(message)
            assert message.wipe_progress == pytest.approx(1.0)
            complete = ProcessComplete("done")
            app.mount_transcript(complete)
            await pilot.pause()
            play_fade_enter(complete)
            assert complete.styles.opacity == pytest.approx(1.0)
            assert complete.offset.x == 0

    asyncio.run(_run())


def test_slash_menu_fades_in_when_shown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            menu = app.query_one("#slash-menu", SlashMenu)
            assert not menu.display
            menu.set_commands(command_matches("/"))
            assert menu.display
            assert menu.styles.opacity < 1.0
            await pilot.wait_for_scheduled_animations()
            assert menu.styles.opacity == pytest.approx(1.0)

            menu.set_commands(command_matches("/mo"))
            assert menu.display
            assert menu.styles.opacity == pytest.approx(1.0)

            menu.set_commands(())
            assert not menu.display

    asyncio.run(_run())


def _strip_brightness(strip: Strip) -> float:
    total = 0.0
    count = 0
    for _text, style, control in strip._segments:
        if control:
            continue
        count += 1
        if style is None or style.color is None:
            continue
        color = Color.from_rich_color(style.color)
        total += (color.r + color.g + color.b) / 3
    return total / count if count else 0.0
