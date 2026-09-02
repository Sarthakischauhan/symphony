"""Smoke tests for the Textual TUI scaffold (no live API)."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from types import SimpleNamespace
from typing import Any

import pytest
from textual import events
from textual.app import App
from textual.containers import VerticalScroll
from textual.widgets import Static

from core_ai import ModelRegistry
from core_ai.types import Message
from coding_agent.tui.screens import ContextModal
from core_harness import HarnessResult
from core_harness.context import COMPACTED_CONTEXT_MARK, build_context_report
from coding_agent.agent import CodingAgent
from coding_agent.config import CodingAgentConfig, LearningConfig
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.commands import (
    EFFORT_CATALOG,
    ModelOption,
    SLASH_COMMANDS,
    command_matches,
    effort_matches,
    effort_options_for_model,
    find_mode,
    find_model,
    mode_matches,
    model_matches,
    model_options,
    model_supports_effort,
)
from coding_agent.tui.runtime import ControlPlaneEvent, TextualControlPlane
from coding_agent.tui.screens.file_selector import (
    active_file_mention,
    complete_file_mention,
    file_matches,
)
from coding_agent.tui.tools import (
    ImageAttachment,
    build_user_content,
    display_from_content,
    dropped_image_paths,
    render_half_block,
)
from coding_agent.tui.screens import (
    ContentModal,
    DiffFileCard,
    DiffModal,
    ImageModal,
    PlanModal,
    PlanSectionCard,
    _plan_sections,
)
from coding_agent.tui.runtime import SubagentRecord, SubagentScreen, SubagentWidget
from coding_agent.tui.screens.resume import ResumeApp, SessionOption, load_session_options
from coding_agent.tui.theme import SYMPHONY_CODE_THEME, themed_markdown
from coding_agent.tui.tools import (
    BashToolWidget,
    GenerateImageWidget,
    PatchDiffWidget,
    ReadFileWidget,
    ToolCallSummary,
    ToolCallWidget,
)
from coding_agent.tui.composer import PromptInput, SlashMenu
from coding_agent.tui.transcript import (
    ReasoningWidget,
    RunProcess,
    ThinkingStatus,
    TopBar,
    UserMessage,
)


def test_tui_escape_cancels_busy_run_and_restores_composer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = True
            prompt = app.query_one("#prompt")
            prompt.disabled = True
            await pilot.press("escape")
            await pilot.pause()
            assert app.control_plane.cancelled
            assert app.control_plane.cancel_reason == "user_cancel"
            assert not prompt.disabled
            assert prompt.has_focus

    asyncio.run(_run())


def test_tui_quit_cancels_pending_learning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    cancelled: list[str] = []

    class FakeLearning:
        def cancel(self) -> None:
            cancelled.append("cancel")

        async def shutdown(self) -> None:
            cancelled.append("shutdown")

    class FakeAgent:
        learning_loop = FakeLearning()

        async def shutdown_learning(self) -> None:
            await self.learning_loop.shutdown()

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._agent = FakeAgent()  # type: ignore[assignment]
            app.action_quit()
            await app.on_unmount()
            assert cancelled == ["cancel", "shutdown"]

    asyncio.run(_run())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._agent is None
            assert app.query_one("#transcript") is not None
            assert app.query_one("#composer") is not None
            assert app.query_one("#prompt") is not None
            assert app.query_one("#status") is not None

    asyncio.run(_run())


def test_markdown_code_theme_matches_tui_surface() -> None:
    background = SYMPHONY_CODE_THEME.get_background_style().bgcolor
    assert background is not None
    assert background.get_truecolor().hex == "#0a0a0a"


def test_topbar_renders_borderless_model_label(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        app = CodingAgentApp(workspace=tmp_path, model_id="anthropic:claude-sonnet-5")
        async with app.run_test() as pilot:
            await pilot.pause()
            topbar = app.query_one(TopBar)
            topbar.set_context(tmp_path, "anthropic:claude-sonnet-5")
            model_label = topbar.query_one("#topbar-model")
            assert str(model_label.render()) == " anthropic:claude-sonnet-5 "

    asyncio.run(_run())


def test_themed_markdown_avoids_rich_monokai_default() -> None:
    from rich.markdown import Markdown

    bare = Markdown("```py\nprint(1)\n```")
    assert bare.code_theme == "monokai"

    themed = themed_markdown("```py\nprint(1)\n```")
    assert themed.code_theme is SYMPHONY_CODE_THEME
    assert themed.inline_code_theme is SYMPHONY_CODE_THEME


def test_plan_stream_writes_to_file_without_rendering_in_chat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._plan_store.begin("To build a server")
            app._plan_run_active = True
            app.on_harness_event(ControlPlaneEvent("text_delta", {"delta": "## Steps\n"}))
            app.on_harness_event(
                ControlPlaneEvent("text_delta", {"delta": "1. Add API.\n"})
            )

            assert app._assistant is None
            plan_path = tmp_path / ".symphony" / "plans" / "to_build_a_server_plan.md"
            assert plan_path.read_text().endswith(
                "## Steps\n1. Add API.\n"
            )

            app.on_harness_event(ControlPlaneEvent("run_completed", {}))
            assert not app._plan_run_active

    asyncio.run(_run())


def test_plan_modal_offers_build_now(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    app._plan_store.save("Add API", "1. Build it.")
    actions: list[str | None] = []

    async def _run() -> None:
        async with app.run_test() as pilot:
            app.push_screen(PlanModal(tmp_path), actions.append)
            await pilot.pause()
            assert app.screen.query_one(PlanSectionCard) is not None
            await pilot.click("#plan-build")
            await pilot.pause()
            assert actions == ["build"]

    asyncio.run(_run())


def test_plan_modal_normalizes_top_level_heading() -> None:
    _task, sections = _plan_sections(
        "# Plan\n\n**Task:** Keep tool output small\n\n"
        "# Plan: Limit Large Tool Results\n\n1. Clip output.\n"
    )

    assert sections == [
        ("Overview", "**Plan: Limit Large Tool Results**\n\n1. Clip output.")
    ]


def test_pasted_prompt_is_compacted_without_changing_agent_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    calls: list[str] = []

    class FakeAgent:
        learning_loop = None

        async def run(self, user_input: str) -> HarnessResult:
            calls.append(user_input)
            return HarnessResult(output_text="", messages=[])

    prefix = "Can you help me with the error "
    pasted = "traceback line\n" * 90
    expected = (prefix + pasted).strip()

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._agent = FakeAgent()  # type: ignore[assignment]
            prompt = app.query_one("#prompt", PromptInput)
            prompt.value = prefix
            prompt.cursor_position = len(prefix)
            prompt.post_message(events.Paste(pasted))
            await pilot.pause()

            assert prompt.value == f"{prefix}[{len(pasted):,} chars]"
            assert prompt.expanded_value() == prefix + pasted
            assert prompt.pasted_chunks == (pasted,)

            await pilot.press("ctrl+enter")
            await pilot.pause()

            assert calls == [expected]
            message = app.query_one(UserMessage)
            assert message._hidden_content == {"0": pasted.rstrip()}
            display = message._compact_content(expected, (pasted,))
            assert display.plain == f"{prefix}[{len(pasted.rstrip()):,} chars]"
            assert display.spans[0].style.meta["@click"] == "open_content('0')"

            message.action_open_content("0")
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, ContentModal)
            assert modal.query_one("#content-text", Static).content == pasted.rstrip()

    asyncio.run(_run())


def test_compact_paste_marker_opens_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    prefix = "Can you help "
    pasted = "failure details\n" * 40

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt", PromptInput)
            prompt.value = prefix
            prompt.cursor_position = len(prefix)
            prompt.post_message(events.Paste(pasted))
            await pilot.pause()

            await pilot.click(prompt, offset=(len(prefix) + 2, 0))
            await pilot.pause()

            assert isinstance(app.screen, ContentModal)
            assert app.screen.query_one("#content-text", Static).content == pasted
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ContentModal)

    asyncio.run(_run())


def test_dropped_image_becomes_clickable_chip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    image_path = tmp_path / "shot.png"
    image_path.write_bytes(
        __import__("base64").b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
    )
    app = CodingAgentApp(workspace=tmp_path)
    calls: list[object] = []

    class FakeAgent:
        learning_loop = None

        async def run(self, user_input: object) -> HarnessResult:
            calls.append(user_input)
            return HarnessResult(output_text="", messages=[])

    prefix = "What is in "
    expected_marker = "[Image 1]"

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._agent = FakeAgent()  # type: ignore[assignment]
            prompt = app.query_one("#prompt", PromptInput)
            prompt.value = prefix
            prompt.cursor_position = len(prefix)
            prompt.post_message(events.Paste(f"{image_path}\n"))
            await pilot.pause()

            assert expected_marker in prompt.value
            assert prompt.images[0].filename == "shot.png"
            assert str(image_path) not in prompt.value

            await pilot.click(prompt, offset=(len(prefix) + 2, 0))
            await pilot.pause()
            assert isinstance(app.screen, ImageModal)
            title = app.screen.query_one("#image-title", Static).content
            title_text = title.plain if hasattr(title, "plain") else str(title)
            assert "shot.png" in title_text
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ImageModal)

            await pilot.press("ctrl+enter")
            await pilot.pause()

            assert calls
            content = calls[0]
            assert isinstance(content, list)
            assert content[0] == {"type": "text", "text": prefix}
            assert content[1]["type"] == "image"
            assert content[1]["filename"] == "shot.png"
            message = app.query_one(UserMessage)
            display = message._compact_content(f"{prefix}{expected_marker} ", ())
            assert display.plain == f"{prefix}{expected_marker} "
            assert display.spans[0].style.meta["@click"] == "open_image('1')"

            message.action_open_image("1")
            await pilot.pause()
            assert isinstance(app.screen, ImageModal)

    asyncio.run(_run())


def test_generate_image_tool_chip_opens_modal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    image_path = tmp_path / "icon.png"
    image_path.write_bytes(
        __import__("base64").b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
    )
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.add_tool("img-1", "generate_image")
            app.update_tool(
                "img-1",
                arguments={"path": "icon.png", "prompt": "a red square"},
                status="running",
            )
            app.update_tool(
                "img-1",
                status="done",
                result="Wrote image icon.png (image/png, 70 bytes)\n[image:icon.png]",
            )

            await pilot.pause()
            widget = app._tools["img-1"]
            assert isinstance(widget, GenerateImageWidget)
            assert not widget.collapsed
            assert widget.open_preview()
            await pilot.pause()
            assert isinstance(app.screen, ImageModal)
            title = app.screen.query_one("#image-title", Static).content
            title_text = title.plain if hasattr(title, "plain") else str(title)
            assert "icon.png" in title_text
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ImageModal)

    asyncio.run(_run())


def test_modal_escape_closes_when_scroll_has_focus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ContentModal("long content\n" * 50))
            await pilot.pause()
            scroll = app.screen.query_one("#content-body", VerticalScroll)
            scroll.focus()
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ContentModal)

    asyncio.run(_run())


def test_diff_modal_shows_file_names_and_change_stats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "coding_agent.tui.screens.diff.read_workspace_diff",
        lambda _workspace: (
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1,2 @@\n"
            "-old\n"
            "+new\n"
            "+added\n"
        ),
    )
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            app.push_screen(DiffModal(tmp_path))
            await pilot.pause()

            card = app.screen.query_one(DiffFileCard)
            assert card.path == "src/app.py"
            assert (card.additions, card.deletions) == (2, 1)
            assert "src/app.py" in str(card.query_one(".diff-file-path").render())
            assert "+2" in str(card.query_one(".diff-file-stats").render())
            assert "−1" in str(card.query_one(".diff-file-stats").render())

    asyncio.run(_run())


def test_resume_app_selects_with_arrow_keys() -> None:
    sessions = [
        SessionOption("one", "2026-08-12T16:00:00+00:00", "First task", 3),
        SessionOption("two", "2026-08-11T16:00:00+00:00", "Second task", 7),
    ]
    app = ResumeApp(sessions)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.press("down", "enter")
            await pilot.pause()
            assert app.return_value == "two"

    asyncio.run(_run())


def test_resume_options_use_existing_persistence_api() -> None:
    class Persistence:
        async def list_sessions(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    session_id="saved-1",
                    updated_at="2026-08-12T16:00:00+00:00",
                )
            ]

        async def load_conversation(self, *, session_id: str) -> list[Message]:
            assert session_id == "saved-1"
            return [
                Message(role="system", content="system"),
                Message(role="user", content="Fix the login flow"),
                Message(role="assistant", content="Done"),
            ]

    options = asyncio.run(load_session_options(Persistence()))

    assert options[0].first_message == "Fix the login flow"
    assert options[0].message_count == 3


def test_resume_app_escape_exits_without_selection() -> None:
    app = ResumeApp([SessionOption("one", "2026-08-12T16:00:00+00:00", "Task", 1)])

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.press("escape")
            await pilot.pause()
            assert app.return_value is None

    asyncio.run(_run())


def test_textual_control_plane_posts_message() -> None:
    posted: list[ControlPlaneEvent] = []

    class FakeApp:
        def post_message(self, message: ControlPlaneEvent) -> None:
            posted.append(message)

    cp = TextualControlPlane()
    cp.bind(FakeApp())

    async def _emit() -> None:
        await cp.emit("run_started", {"model_id": "openai:test"})

    asyncio.run(_emit())
    assert len(posted) == 1
    assert posted[0].event_type == "run_started"
    assert posted[0].payload["model_id"] == "openai:test"


def test_textual_control_plane_fork_isolates_approvals_and_shares_cancel() -> None:
    parent = TextualControlPlane()
    parent.set_approval_mode("ask")
    child_allow = parent.fork(approvals=parent.approvals.model_copy(update={"mode": "always_allow"}))
    child_ask = parent.fork()
    assert parent.approvals.mode == "ask"
    assert child_allow.approvals.mode == "always_allow"
    assert child_ask.approvals.mode == "ask"
    assert child_allow.cancel_event is parent.cancel_event
    assert child_ask.cancel_event is parent.cancel_event
    assert child_allow._interaction_lock is parent._interaction_lock
    assert child_ask._question_futures is parent._question_futures
    parent.request_cancel("user_cancel")
    assert parent.cancelled
    assert child_allow.cancelled
    assert child_ask.cancelled
    assert child_allow.cancel_reason == "user_cancel"


def test_textual_control_plane_parent_answers_child_question() -> None:
    parent = TextualControlPlane()
    child = parent.fork()

    async def _run() -> str:
        future = child._get_question_future("child-q")
        await parent.answer_user("child-q", "Allow once")
        return future.result()

    assert asyncio.run(_run()) == "Allow once"


def test_tui_run_agent_turn_delegates_to_agent(tmp_path: Path) -> None:
    class FakeAgent:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def run(self, user_input: str, **kwargs: object) -> HarnessResult:
            self.calls.append(user_input)
            return HarnessResult(
                output_text=f"answer to {user_input}",
                messages=[
                    Message(role="system", content="system prompt"),
                    Message(role="user", content=user_input),
                    Message(role="assistant", content=f"answer to {user_input}"),
                ],
            )

    app = CodingAgentApp(workspace=tmp_path)
    fake_agent = FakeAgent()
    app._agent = fake_agent  # type: ignore[assignment]

    result = asyncio.run(app._run_agent_turn("first"))
    assert result.output_text == "answer to first"
    assert fake_agent.calls == ["first"]


def test_tui_maps_stream_usage_and_read_file_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._presenter is not None
            app._thinking = None
            app._presenter.handle("run_started", {"model_id": "openai:test"})
            app._presenter.handle("turn_started", {"turn": 0, "message_count": 2})
            app._presenter.handle(
                "reasoning_delta",
                {
                    "turn": 0,
                    "summary_index": 0,
                    "delta": "Inspecting ",
                    "text": "Inspecting ",
                },
            )
            app._presenter.handle(
                "reasoning_delta",
                {
                    "turn": 0,
                    "summary_index": 0,
                    "delta": "the requested file.",
                    "text": "Inspecting the requested file.",
                },
            )
            app._presenter.handle(
                "reasoning_delta",
                {
                    "turn": 0,
                    "summary_index": 1,
                    "delta": "Choosing an implementation.",
                    "text": "Choosing an implementation.",
                },
            )
            app._presenter.handle("text_delta", {"turn": 0, "delta": "I’ll inspect it."})
            app._presenter.handle(
                "tool_call_started",
                {"tool_call_id": "read-1", "tool_name": "read_file"},
            )
            app._presenter.handle(
                "tool_call_delta",
                {"tool_call_id": "read-1", "delta": '{"path":"src/app.py"}'},
            )
            app._presenter.handle(
                "tool_execution_started",
                {
                    "tool_call_id": "read-1",
                    "tool_name": "read_file",
                    "arguments": {"path": "src/app.py"},
                },
            )
            app._presenter.handle(
                "tool_execution_completed",
                {
                    "tool_call_id": "read-1",
                    "tool_name": "read_file",
                    "result": "line one\nline two\n",
                },
            )
            app._presenter.handle(
                "usage",
                {
                    "turn": 0,
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "reasoning_tokens": 18,
                    "total_tokens": 150,
                    "cumulative_tokens": 150,
                    "estimated": False,
                },
            )
            await pilot.pause()

            read = app.query_one(ReadFileWidget)
            thinking = app.query_one(ThinkingStatus)
            reasoning = list(app.query(ReasoningWidget))
            assert read.status == "done"
            assert read.collapsed
            assert read.arguments["path"] == "src/app.py"
            assert "120 in / 30 out" in str(thinking.render())
            assert "18 reasoning" in str(thinking.render())
            assert [widget.reasoning_text for widget in reasoning] == [
                "Inspecting the requested file.\n\nChoosing an implementation.",
            ]
            assert reasoning[0].collapsed
            assert app._assistant is not None

            read.scroll_visible()
            await pilot.pause()
            await pilot.click(read.query_one("CollapsibleTitle"))
            await pilot.pause()
            assert not read.collapsed

            app._presenter.handle(
                "run_completed",
                {
                    "usage": {
                        "prompt_tokens": 120,
                        "completion_tokens": 30,
                        "reasoning_tokens": 18,
                        "total_tokens": 150,
                    }
                },
            )
            await pilot.pause()
            process = app.query_one(RunProcess)
            assert process.query_one(".process-complete") is not None
            await pilot.click(reasoning[0].query_one("CollapsibleTitle"))
            assert not reasoning[0].collapsed

    asyncio.run(_run())


def test_tui_animates_working_gradient_while_rate_limit_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._presenter is not None
            app._presenter.handle("run_started", {"model_id": "openai:test"})
            app._presenter.handle("turn_started", {"turn": 0, "message_count": 2})
            app._presenter.handle(
                "model_retry_scheduled",
                {"turn": 0, "retry_after": 2.5, "attempt": 1},
            )
            await pilot.pause()

            thinking = app.query_one(ThinkingStatus)
            first = thinking.render()
            first_styles = [span.style for span in first.spans]
            thinking._advance_gradient()
            second = thinking.render()
            second_styles = [span.style for span in second.spans]

            assert "Working" in first.plain
            assert "retrying in 2.5s" in first.plain
            assert "attempt 1" in first.plain
            assert first_styles != second_styles
            assert app._ui_state.detail == "rate limited; retrying in 2.5s"

    asyncio.run(_run())


def test_tui_labels_stream_error_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._presenter is not None
            app._presenter.handle("run_started", {"model_id": "openai:test"})
            app._presenter.handle("turn_started", {"turn": 0, "message_count": 2})
            app._presenter.handle(
                "model_retry_scheduled",
                {
                    "turn": 0,
                    "retry_after": 1,
                    "attempt": 1,
                    "reason": "stream_error",
                    "resets_stream": True,
                },
            )
            await pilot.pause()

            thinking = app.query_one(ThinkingStatus).render()
            assert "Stream error" in thinking.plain
            assert "retrying in 1s" in thinking.plain
            assert app._ui_state.detail == "stream error; retrying in 1s"

    asyncio.run(_run())


def test_bash_tool_uses_timeline_header_with_right_aligned_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.add_tool("bash-1", "bash")
            app.update_tool(
                "bash-1",
                arguments={"command": "git diff --check && git diff --stat"},
                status="running",
            )
            await pilot.pause()

            bash = app.query_one(BashToolWidget)
            assert "Bash" in str(bash.query_one(".bash-tool-label").render())
            assert "git diff --check" in str(
                bash.query_one(".bash-tool-command").render()
            )
            assert str(bash.query_one(".bash-tool-status").render()) == "running"
            assert not list(bash.query("CollapsibleTitle"))

            app.update_tool("bash-1", status="done", result="clean")
            await pilot.pause()
            assert bash.collapsed
            assert not bash.query_one(".bash-tool-body").display

            bash.scroll_visible()
            await pilot.pause()
            header = bash.query_one(".bash-tool-header")
            assert "▸" in str(bash.query_one(".bash-tool-label").render())
            await pilot.click(header)
            await pilot.pause()
            assert not bash.collapsed
            assert bash.query_one(".bash-tool-body").display
            assert "▾" in str(bash.query_one(".bash-tool-label").render())

            header.focus()
            await pilot.press("space")
            await pilot.pause()
            assert bash.collapsed
            assert not bash.query_one(".bash-tool-body").display
            assert "▸" in str(bash.query_one(".bash-tool-label").render())

    asyncio.run(_run())


def test_tool_timeline_columns_align_across_widget_types(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.add_tool("search-1", "search")
            app.update_tool(
                "search-1", arguments={"query": "collapsible"}, status="running"
            )
            app.add_tool("read-1", "read_file")
            app.update_tool(
                "read-1", arguments={"path": "src/app.py"}, status="running"
            )
            app.add_tool("patch-1", "patch")
            app.update_tool(
                "patch-1",
                arguments={
                    "path": "src/app.py",
                    "old_str": "old\n",
                    "new_str": "new\n",
                },
                status="running",
            )
            app.add_tool("bash-1", "bash")
            app.update_tool(
                "bash-1", arguments={"command": "pytest -q"}, status="running"
            )
            await pilot.pause()

            widgets = [
                app._tools[call_id]
                for call_id in ("search-1", "read-1", "patch-1", "bash-1")
            ]
            headers = [
                widget.query_one(
                    ".bash-tool-header"
                    if isinstance(widget, BashToolWidget)
                    else ".tool-call-header"
                )
                for widget in widgets
            ]
            labels = [
                widget.query_one(
                    ".bash-tool-label"
                    if isinstance(widget, BashToolWidget)
                    else ".tool-call-label"
                )
                for widget in widgets
            ]
            commands = [
                widget.query_one(
                    ".bash-tool-command"
                    if isinstance(widget, BashToolWidget)
                    else ".tool-call-command"
                )
                for widget in widgets
            ]
            statuses = [
                widget.query_one(
                    ".bash-tool-status"
                    if isinstance(widget, BashToolWidget)
                    else ".tool-call-status"
                )
                for widget in widgets
            ]

            assert len({header.region.x for header in headers}) == 1
            assert len({label.region.x for label in labels}) == 1
            assert len({command.region.x for command in commands}) == 1
            assert len({status.region.right for status in statuses}) == 1

    asyncio.run(_run())


def test_tool_updates_keep_rows_stable_until_manually_expanded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.add_tool("patch-1", "patch")
            await pilot.pause()
            widget = app.query_one(PatchDiffWidget)
            heights = [widget.region.height]
            assert widget.collapsed

            arguments = {
                "path": "src/app.py",
                "old_str": "old\n",
                "new_str": "new\n",
            }
            app.update_tool("patch-1", arguments=arguments)
            await pilot.pause()
            heights.append(widget.region.height)
            assert widget.collapsed

            app.update_tool("patch-1", arguments=arguments, status="running")
            await pilot.pause()
            heights.append(widget.region.height)
            assert widget.collapsed

            app.update_tool("patch-1", status="done", result="patched src/app.py")
            await pilot.pause()
            heights.append(widget.region.height)
            assert widget.collapsed
            assert len(set(heights)) == 1

            widget.collapsed = False
            await pilot.pause()
            app.update_tool("patch-1", status="done", result="patched src/app.py")
            await pilot.pause()
            assert not widget.collapsed

    asyncio.run(_run())


def test_live_tool_updates_do_not_hijack_transcript_scroll(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.mount_transcript(Static("\n".join(f"line {i}" for i in range(80))))
            await pilot.pause()
            transcript = app.query_one("#transcript", VerticalScroll)
            transcript.scroll_end(animate=False, force=True)
            await pilot.pause()
            assert transcript.scroll_y > 0

            transcript.scroll_home(animate=False, force=True)
            await pilot.pause()
            assert transcript.scroll_y == 0

            app.add_tool("bash-1", "bash")
            app.update_tool(
                "bash-1", arguments={"command": "pytest -q"}, status="running"
            )
            app.update_tool("bash-1", status="done", result="clean")
            await pilot.pause()
            assert transcript.scroll_y == 0

    asyncio.run(_run())


def test_live_reasoning_follows_tail_then_folds_to_thought(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._presenter is not None
            app._presenter.handle("run_started", {"model_id": "openai:test"})
            app._presenter.handle(
                "reasoning_delta",
                {
                    "turn": 0,
                    "summary_index": 0,
                    "delta": "**REASONING SUMMARY**\nStarting.",
                    "text": "**REASONING SUMMARY**\nStarting.",
                },
            )
            app._presenter.flush_stream_paints()
            await pilot.pause()
            text = "**REASONING SUMMARY**\n**Explaining application context**\n\nStarting.\n\n" + "\n\n".join(
                f"Streaming thought {index}." for index in range(30)
            )
            app._presenter.handle(
                "reasoning_delta",
                {
                    "turn": 0,
                    "summary_index": 0,
                    "delta": text,
                    "text": text,
                },
            )
            app._presenter.flush_stream_paints()
            await pilot.pause()

            thought = app.query_one(ReasoningWidget)
            scroll = thought.query_one(".reasoning-scroll")
            assert not thought.collapsed
            assert "REASONING SUMMARY" not in thought.reasoning_text
            assert scroll.is_anchored

            app._presenter.handle(
                "tool_call_started",
                {"tool_call_id": "read-1", "tool_name": "read_file"},
            )
            await pilot.pause()

            assert thought.title == "Thought - Explaining application context"
            assert thought.collapsed
            assert not scroll.is_anchored
            assert app._thinking is not None
            assert not app._thinking.display

    asyncio.run(_run())


@pytest.mark.parametrize(
    ("content", "expected_title"),
    [
        ("# Inspecting files\n\nReading the repository.", "Thought - Inspecting files"),
        ("__Planning changes__\n\nReviewing the code.", "Thought - Planning changes"),
        ("Explaining application context\n\nThis is ordinary prose.", "Thought"),
        ("**Bold opening sentence.** More prose follows.", "Thought"),
    ],
)
def test_reasoning_title_uses_only_a_standalone_markdown_heading(
    content: str, expected_title: str
) -> None:
    thought = ReasoningWidget(content)
    thought.complete()
    assert thought.title == expected_title


def test_slash_command_discovery_and_model_resolution() -> None:
    assert [command.name for command in command_matches("/mo")] == ["model", "mode"]
    assert "diff" in [command.name for command in SLASH_COMMANDS]
    assert "learning" in [command.name for command in SLASH_COMMANDS]
    assert "plan" in [command.name for command in SLASH_COMMANDS]
    assert "effort" in [command.name for command in SLASH_COMMANDS]
    assert "context" in [command.name for command in SLASH_COMMANDS]
    assert [command.name for command in command_matches("/lea")] == ["learning"]
    assert find_model("gpt-5.6-luna").id == "openai:gpt-5.6-luna"  # type: ignore[union-attr]
    assert find_model("gpt-5.6-sol").id == "openai:gpt-5.6-sol"  # type: ignore[union-attr]
    assert find_model("claude-sonnet-5").id == "anthropic:claude-sonnet-5"  # type: ignore[union-attr]
    assert find_model("gemini-3.7-flash").id == "gemini:gemini-3.7-flash"  # type: ignore[union-attr]
    assert find_model("missing") is None
    assert [model.id for model in model_matches("5.6-luna")] == [
        "openai:gpt-5.6-luna"
    ]
    assert find_mode("Plan").id == "plan"  # type: ignore[union-attr]
    assert [mode.id for mode in mode_matches("")] == ["build", "plan"]
    assert [effort.id for effort in effort_matches("xh")] == ["xhigh"]
    assert [effort.id for effort in EFFORT_CATALOG] == [
        "default",
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]


def test_effort_is_only_available_when_model_advertises_effort() -> None:
    assert model_supports_effort("openai:gpt-5.6-luna")
    assert effort_options_for_model("openai:gpt-5.6-luna")
    assert not model_supports_effort("gemini:gemini-2.5-flash")
    assert effort_options_for_model("gemini:gemini-2.5-flash") == ()
    assert command_matches("/e", include_effort=False) == ()


def test_file_mentions_are_ranked_and_preserve_prompt_text(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "turn.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_turn.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("hidden", encoding="utf-8")

    matches = file_matches(tmp_path, "turn")

    assert [match.path for match in matches] == ["src/turn.py", "tests/test_turn.py"]
    assert active_file_mention("Review @tur") == (7, "tur")
    assert active_file_mention("Review @src/turn.py next") is None
    assert complete_file_mention("Review @tur", "src/turn.py") == (
        "Review @src/turn.py ",
        20,
    )


def test_at_file_selector_uses_existing_composer_menu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "turn.py").write_text("pass\n", encoding="utf-8")
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt")
            prompt.value = "Review @tur"
            await pilot.pause()

            menu = app.query_one("#slash-menu", SlashMenu)
            assert menu.display
            assert menu.is_file_selector
            assert menu.selected_value == "@src/turn.py"

            await pilot.press("tab")
            await pilot.pause()
            assert prompt.value == "Review @src/turn.py "
            assert prompt.cursor_position == len(prompt.value)
            assert not menu.display

            prompt.value = "Also inspect @tur"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert prompt.value == "Also inspect @src/turn.py "
            assert not menu.display

    asyncio.run(_run())


def test_file_selector_scrolls_to_keep_selection_visible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for index in range(20):
        (tmp_path / f"file_{index:02}.py").write_text("pass\n", encoding="utf-8")
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt")
            prompt.value = "Review @file_"
            await pilot.pause()

            menu = app.query_one("#slash-menu", SlashMenu)
            assert menu.display
            assert len(menu._files) == 20
            assert menu.scroll_y == 0

            for _ in range(12):
                await pilot.press("down")
            await pilot.pause()

            assert menu.selected_index == 12
            assert menu.scroll_y > 0
            assert menu.selected_value == "@file_12.py"
            assert menu.styles.scrollbar_size_vertical == 1

            menu.post_message(
                events.MouseScrollDown(menu, 0, 0, 0, 1, 0, False, False, False)
            )
            await pilot.pause()
            assert menu.selected_index == 13

            menu.post_message(
                events.MouseScrollUp(menu, 0, 0, 0, -1, 0, False, False, False)
            )
            await pilot.pause()
            assert menu.selected_index == 12

    asyncio.run(_run())


def test_plan_menu_options_are_hoverable_and_clickable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._plan_store.save("Ship feature", "1. Build it.")
            opened: list[object] = []
            app.push_screen = lambda screen, *args: opened.append(screen)  # type: ignore[method-assign]

            prompt = app.query_one("#prompt")
            prompt.value = "/plan "
            await pilot.pause()
            menu = app.query_one("#slash-menu", SlashMenu)

            assert menu.display
            assert menu.selected_value == "/plan ship_feature_plan.md"
            assert await pilot.hover(menu, offset=(4, 2))
            assert menu._mouse_hovering_over == 0
            assert await pilot.click(menu, offset=(4, 2))
            await pilot.pause()

            assert opened and opened[0].__class__.__name__ == "PlanModal"

    asyncio.run(_run())


def test_permission_question_has_distinct_secure_design(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            answer = app.control_plane._get_question_future("approval-1")
            app._show_question(
                {
                    "request_id": "approval-1",
                    "question": "Allow bash command once?\n`uv run pytest`",
                    "choices": ["Allow once", "Deny"],
                    "default": "Allow once",
                    "kind": "approval",
                    "tool_name": "bash",
                }
            )
            await pilot.pause()

            menu = app.query_one("#approval-menu", SlashMenu)
            assert menu.has_class("permission-menu")
            assert menu.selected_value == "Allow once"
            assert menu.highlighted == menu._option_offset
            assert str(menu.options[0].prompt) == (
                "  Allow Symphony to run the following command?"
            )
            assert "uv run pytest" in str(menu.options[1].prompt)
            assert app.query_one("#prompt").value == ""

            assert await pilot.click(menu, offset=(4, 4))
            await pilot.pause()
            assert answer.result() == "Allow once"
            assert app.query_one("#prompt").value == ""

    asyncio.run(_run())


def test_subagent_approval_question_uses_parent_approval_menu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            answer = app.control_plane._get_question_future("child-approval-1")
            app.on_harness_event(
                ControlPlaneEvent(
                    "question_asked",
                    {
                        "request_id": "child-approval-1",
                        "question": "Allow bash command once?\n`uv run pytest`",
                        "choices": ["Allow once", "Deny"],
                        "default": "Allow once",
                        "kind": "approval",
                        "tool_name": "bash",
                        "agent_id": "child-1",
                        "parent_id": "parent-1",
                    },
                )
            )
            await pilot.pause()

            menu = app.query_one("#approval-menu", SlashMenu)
            assert menu.display
            assert app._pending_question_id == "child-approval-1"
            assert app._subagents["child-1"].events[-1][0] == "question_asked"

            assert await pilot.click(menu, offset=(4, 4))
            await pilot.pause()
            assert answer.result() == "Allow once"

    asyncio.run(_run())


def test_subagent_approval_closes_nested_screen_before_prompting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            record = SubagentRecord(
                agent_id="child-1",
                parent_id="parent-1",
                label="run tests",
                prompt="Run the test suite.",
            )
            app._subagents[record.agent_id] = record
            app.open_subagent(record)
            await pilot.pause()
            assert isinstance(app.screen, SubagentScreen)

            answer = app.control_plane._get_question_future("child-approval-2")
            app.on_harness_event(
                ControlPlaneEvent(
                    "question_asked",
                    {
                        "request_id": "child-approval-2",
                        "question": "Allow bash command once?\n`pytest`",
                        "choices": ["Allow once", "Deny"],
                        "default": "Allow once",
                        "kind": "approval",
                        "tool_name": "bash",
                        "agent_id": "child-1",
                        "parent_id": "parent-1",
                    },
                )
            )
            await pilot.pause()

            assert not isinstance(app.screen, SubagentScreen)
            assert app.query_one("#approval-menu", SlashMenu).display
            assert app._pending_question_id == "child-approval-2"

            await app._answer_question("Deny")
            assert answer.result() == "Deny"

    asyncio.run(_run())


def test_reload_refreshes_config_without_clearing_conversation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    loaded: list[bool] = []
    built_with: dict[str, Any] = {}
    selected_modes: list[str] = []

    reloaded_agent = SimpleNamespace(
        session_id="current-session",
        harness=SimpleNamespace(
            model_id="openai:reloaded-model",
            reasoning_effort=None,
            state=SimpleNamespace(context_limit=lambda _model_id: 64_000),
        ),
        registry=SimpleNamespace(namespaces=lambda: ("openai",)),
        learning_loop=None,
        set_mode=lambda mode: selected_modes.append(mode),
    )

    def _load_dotenv(*, override: bool) -> None:
        loaded.append(override)

    def _build_agent(**kwargs: Any) -> Any:
        built_with.update(kwargs)
        return reloaded_agent

    monkeypatch.setattr("coding_agent.tui.commands.manager.load_dotenv", _load_dotenv)
    monkeypatch.setattr("coding_agent.tui.commands.manager.build_agent", _build_agent)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            selected_modes.clear()
            built_with.clear()
            app._agent = SimpleNamespace(
                session_id="current-session",
                learning_loop=None,
                harness=SimpleNamespace(reasoning_effort="high"),
            )
            app._mount_transcript(UserMessage("Keep this conversation"))
            await pilot.pause()

            await app._command_manager.run("/reload")
            await pilot.pause()

            assert loaded == [True]
            assert built_with["session_id"] == "current-session"
            assert selected_modes == ["build"]
            assert app._agent is reloaded_agent
            assert app._agent.harness.reasoning_effort == "high"
            assert len(app.query(".user-message")) == 1
            assert app._ui_state.model_id == "openai:reloaded-model"

    asyncio.run(_run())


def test_reasoning_usage_without_summary_skips_reasoning_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._presenter is not None
            app._presenter.handle("run_started", {"model_id": "openai:gpt-5.4-mini"})
            app._presenter.handle(
                "usage",
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "reasoning_tokens": 2,
                    "total_tokens": 15,
                },
            )
            await pilot.pause()
            assert not app.query(ReasoningWidget)

    asyncio.run(_run())


def test_slash_menu_and_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    class FakeState:
        def context_limit(self, model_id: str) -> int:
            del model_id
            return 128_000

    class FakeAgent:
        def __init__(self) -> None:
            self.session_id = "old-session"
            self.harness = SimpleNamespace(
                model_id="openai:gpt-4o-mini",
                reasoning_effort=None,
                session_id="old-session",
                state=FakeState(),
            )
            self.learning_loop = None
            self.mode = "build"
            self.compacted = False

        def set_mode(self, mode: str) -> None:
            self.mode = mode

        async def compact_conversation(self) -> tuple[int, int]:
            self.compacted = True
            return (14, 9)

        async def context_report(self):
            return build_context_report(
                [
                    Message(role="system", content="sys"),
                    Message(role="user", content="hello"),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": "{}"},
                            }
                        ],
                    ),
                    Message(role="tool", content="file contents " * 40, tool_call_id="c1"),
                ],
                context_limit=128_000,
            )

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            fake = FakeAgent()
            app._agent = fake  # type: ignore[assignment]
            app._model_options = (
                ModelOption("openai:gpt-5.6-luna", "gpt-5.6-luna", "openai · responses"),
                ModelOption("openai:gpt-5.6-sol", "gpt-5.6-sol", "openai · responses"),
            )

            prompt = app.query_one("#prompt")
            await pilot.press("tab")
            assert app.mode == "plan"
            assert fake.mode == "plan"
            assert app.query_one("#composer").has_class("plan-mode")
            await pilot.press("tab")
            assert app.mode == "build"
            assert not app.query_one("#composer").has_class("plan-mode")

            prompt.value = "/mo"  # type: ignore[attr-defined]
            await pilot.pause()
            assert app.query_one("#slash-menu", SlashMenu).display
            await pilot.press("tab")
            assert prompt.value == "/model"  # type: ignore[attr-defined]

            prompt.value = "/model 5.6-luna"  # type: ignore[attr-defined]
            await pilot.pause()
            assert app.query_one("#slash-menu", SlashMenu).display
            await pilot.press("tab")
            assert prompt.value == "/model openai:gpt-5.6-luna"  # type: ignore[attr-defined]

            prompt.value = "/model "  # type: ignore[attr-defined]
            await pilot.pause()
            menu = app.query_one("#slash-menu", SlashMenu)
            assert menu.selected_index == 0
            await pilot.press("down")
            assert menu.selected_index == 1
            await pilot.press("up")
            assert menu.selected_index == 0
            await pilot.press("enter")
            await pilot.pause()
            assert fake.harness.model_id == "openai:gpt-5.6-luna"
            assert app._ui_state.model_id == "openai:gpt-5.6-luna"

            prompt.value = "/mode "  # type: ignore[attr-defined]
            await pilot.pause()
            assert menu.display
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert app.mode == "plan"
            assert fake.mode == "plan"
            assert "PLAN" in str(app.query_one("#composer-mode").render())

            prompt.value = "/effort "  # type: ignore[attr-defined]
            await pilot.pause()
            assert menu.display
            assert menu.selected_value == "/effort default"
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert fake.harness.reasoning_effort == "none"

            prompt.value = "/effort xh"  # type: ignore[attr-defined]
            await pilot.pause()
            assert menu.selected_value == "/effort xhigh"
            await pilot.press("enter")
            await pilot.pause()
            assert fake.harness.reasoning_effort == "xhigh"

            await app._run_slash_command("/effort")
            await pilot.pause()
            assert prompt.value == "/effort "  # type: ignore[attr-defined]
            assert menu.selected_value == "/effort xhigh"

            await app._run_slash_command("/effort default")
            assert fake.harness.reasoning_effort is None

            await app._run_slash_command("/compact")
            assert fake.compacted

            opened: list[object] = []
            app.push_screen = lambda screen, *args: opened.append(screen)  # type: ignore[method-assign]
            await app._run_slash_command("/context")
            assert opened and opened[0].__class__.__name__ == "ContextModal"

            opened.clear()
            app._busy = True
            await app._run_slash_command("/context")
            assert opened and opened[0].__class__.__name__ == "ContextModal"
            app._busy = False

            opened.clear()
            await app._run_slash_command("/diff")
            assert opened and opened[0].__class__.__name__ == "DiffModal"

            opened.clear()
            await app._run_slash_command("/learning")
            assert opened and opened[0].__class__.__name__ == "LearningModal"

            opened.clear()
            app._plan_store.save("Add API", "1. Build it.")
            app._plan_store.save("Fix login", "1. Inspect auth.")
            prompt.value = "/plan add"  # type: ignore[attr-defined]
            await pilot.pause()
            assert menu.selected_value == "/plan add_api_plan.md"
            await app._run_slash_command("/plan")
            assert not opened
            assert prompt.value == "/plan "  # type: ignore[attr-defined]
            assert menu.display
            assert menu.selected_value == "/plan fix_login_plan.md"
            await pilot.press("down")
            assert menu.selected_value == "/plan add_api_plan.md"
            await pilot.press("enter")
            await pilot.pause()
            assert opened and opened[0].__class__.__name__ == "PlanModal"

            await app._run_slash_command("/new")
            assert fake.session_id != "old-session"
            assert fake.harness.session_id == fake.session_id

    asyncio.run(_run())


def test_manual_compaction_persists_recent_messages(tmp_path: Path) -> None:
    class CapturingControlPlane:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
            self.events.append((event_type, payload))

    control_plane = CapturingControlPlane()
    agent = CodingAgent(
        registry=ModelRegistry(),
        model_id="openai:gpt-4o-mini",
        workspace=tmp_path,
        control_plane=control_plane,
        config=CodingAgentConfig(learning=LearningConfig(enabled=False)),
        tools=[],
    )
    messages = [Message(role="system", content="system")]
    messages.extend(Message(role="user", content=f"message {i}") for i in range(12))

    async def _run() -> None:
        await agent.persistence.save_conversation(
            session_id=agent.session_id,
            messages=messages,
        )
        assert await agent.compact_conversation(keep_recent=8) == (13, 11)
        saved = await agent.persistence.load_conversation(session_id=agent.session_id)
        assert len(saved) == 11
        assert saved[0].role == "system"
        assert saved[1].content == "message 0"
        assert str(saved[2].content).startswith(COMPACTED_CONTEXT_MARK)
        assert saved[-1].content == "message 11"

    asyncio.run(_run())
    assert [event for event, _ in control_plane.events] == [
        "compaction_started",
        "compaction_completed",
    ]


def test_context_modal_filters_buckets() -> None:
    report = build_context_report(
        [
            Message(role="system", content="sys"),
            Message(role="user", content="hello there"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "bash", "arguments": "{}"},
                    }
                ],
            ),
            Message(role="tool", content="command output " * 30, tool_call_id="c1"),
        ],
        context_limit=128_000,
        keep_recent_tool_results=0,
        prune_tokens=0,
    )

    class Host(App):
        def on_mount(self) -> None:
            self.push_screen(ContextModal(report))

    async def _run() -> None:
        async with Host().run_test() as pilot:
            await pilot.pause()
            modal = pilot.app.screen
            assert isinstance(modal, ContextModal)
            listing = str(modal.query_one("#context-list").render())
            assert "hello there" in listing
            modal.set_filter("tool")
            await pilot.pause()
            filtered = str(modal.query_one("#context-list").render())
            assert "hello there" not in filtered
            assert "bash" in filtered
            assert "stub" in filtered.lower()
            meta = str(modal.query_one("#context-meta").render())
            assert "tool only" in meta

    asyncio.run(_run())


def test_patch_events_render_a_specialized_diff_widget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    arguments = {
        "path": "src/greeting.py",
        "old_str": 'def greet():\n    return "hello"\n',
        "new_str": 'def greet(name):\n    return f"hello {name}"\n',
        "replace_all": False,
    }

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._presenter is not None
            app._presenter.handle(
                "tool_call_started",
                {"tool_call_id": "patch-1", "tool_name": "patch"},
            )
            app._presenter.handle(
                "tool_execution_started",
                {
                    "tool_call_id": "patch-1",
                    "tool_name": "patch",
                    "arguments": arguments,
                },
            )
            app._presenter.handle(
                "tool_execution_completed",
                {
                    "tool_call_id": "patch-1",
                    "tool_name": "patch",
                    "result": "patched src/greeting.py (1 replacement(s), +7 bytes)",
                },
            )
            await pilot.pause()

            widget = app.query_one(PatchDiffWidget)
            diff = widget._diff()
            assert widget.status == "done"
            assert widget.collapsed
            assert widget.arguments["path"] == "src/greeting.py"
            assert widget._stats(diff) == (2, 2)
            assert '-    return "hello"' in diff
            assert '+    return f"hello {name}"' in diff
            assert "Update" in str(widget.query_one(".tool-call-label").render())
            assert "src/greeting.py" in str(
                widget.query_one(".tool-call-command").render()
            )
            assert "+2 -2" in str(widget.query_one(".tool-call-command").render())
            assert str(widget.query_one(".tool-call-status").render()) == "done"

            widget.scroll_visible()
            await pilot.pause()
            await pilot.click(widget.query_one("CollapsibleTitle"))
            await pilot.pause()
            assert not widget.collapsed

    asyncio.run(_run())


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


def test_subagent_card_opens_nested_session_screen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.set_thinking("Thinking…")
            await pilot.pause()
            thinking_before = str(app._thinking.render()) if app._thinking is not None else ""
            app.add_tool("spawn-1", "spawn_agent")
            app.update_tool(
                "spawn-1",
                arguments={
                    "prompt": "Inspect auth.py and summarize the login flow.",
                    "label": "inspect auth",
                },
                status="running",
            )
            app.on_harness_event(
                ControlPlaneEvent(
                    "agent_spawned",
                    {
                        "child_id": "child-1",
                        "agent_id": "parent-1",
                        "label": "inspect auth",
                        "prompt": "Inspect auth.py and summarize the login flow.",
                        "model_id": "openai:gpt-5.6-luna",
                    },
                )
            )
            widget = app._tools["spawn-1"]
            assert isinstance(widget, SubagentWidget)
            assert widget.record is not None
            assert widget.record.agent_id == "child-1"

            app.on_harness_event(
                ControlPlaneEvent(
                    "run_started",
                    {
                        "agent_id": "child-1",
                        "parent_id": "parent-1",
                        "model_id": "openai:gpt-5.6-luna",
                    },
                )
            )
            app.on_harness_event(
                ControlPlaneEvent(
                    "tool_execution_started",
                    {
                        "agent_id": "child-1",
                        "parent_id": "parent-1",
                        "tool_name": "read_file",
                        "arguments": {"path": "auth.py"},
                    },
                )
            )
            assert app._thinking is not None
            assert str(app._thinking.render()) == thinking_before
            assert widget.record.tools[0]["name"] == "read_file"

            widget.scroll_visible()
            await pilot.pause()
            assert await pilot.click(widget.query_one(".tool-call-header"))
            await pilot.pause()
            assert isinstance(app.screen, SubagentScreen)
            assert app.screen.record.label == "inspect auth"
            assert app.screen.record.tools[0]["name"] == "read_file"
            assert app.screen.query_one(TopBar)
            assert app.screen.query_one(UserMessage)
            assert app.screen._tools
            tool = next(iter(app.screen._tools.values()))
            assert tool.tool_name == "read_file"

            app.on_harness_event(
                ControlPlaneEvent(
                    "text_delta",
                    {
                        "agent_id": "child-1",
                        "parent_id": "parent-1",
                        "delta": "Auth uses JWT cookies.",
                    },
                )
            )
            await pilot.pause()
            assert "JWT cookies" in app.screen.record.output_text

            app.on_harness_event(
                ControlPlaneEvent(
                    "agent_completed",
                    {
                        "child_id": "child-1",
                        "agent_id": "parent-1",
                        "output_text": "Auth uses JWT cookies.",
                    },
                )
            )
            await pilot.pause()
            assert app.screen.record.status == "completed"
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, SubagentScreen)

    asyncio.run(_run())


def test_parallel_subagent_rows_bind_by_label(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.add_tool("spawn-auth", "spawn_agent")
            app.update_tool(
                "spawn-auth",
                arguments={"prompt": "Inspect auth.py", "label": "auth"},
                status="running",
            )
            app.add_tool("spawn-db", "spawn_agent")
            app.update_tool(
                "spawn-db",
                arguments={"prompt": "Inspect db.py", "label": "db"},
                status="running",
            )
            app.on_harness_event(
                ControlPlaneEvent(
                    "agent_spawned",
                    {
                        "child_id": "child-db",
                        "agent_id": "parent-1",
                        "label": "db",
                        "prompt": "Inspect db.py",
                    },
                )
            )
            app.on_harness_event(
                ControlPlaneEvent(
                    "agent_spawned",
                    {
                        "child_id": "child-auth",
                        "agent_id": "parent-1",
                        "label": "auth",
                        "prompt": "Inspect auth.py",
                    },
                )
            )
            await pilot.pause()
            auth = app._tools["spawn-auth"]
            db = app._tools["spawn-db"]
            assert isinstance(auth, SubagentWidget)
            assert isinstance(db, SubagentWidget)
            assert auth.record is not None and auth.record.agent_id == "child-auth"
            assert db.record is not None and db.record.agent_id == "child-db"

    asyncio.run(_run())


def test_old_tool_widgets_collapse_to_one_explored_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    app.live_tool_widget_limit = 8

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            for index in range(12):
                call_id = f"read-{index}"
                app.add_tool(call_id, "read_file")
                app.update_tool(
                    call_id,
                    arguments={"path": f"src/f{index}.py"},
                    status="running",
                )
                app.update_tool(call_id, status="done", result="ok")
            await pilot.pause()

            live = [
                node
                for node in app._tools.values()
                if isinstance(node, ToolCallWidget)
            ]
            summaries = list(
                dict.fromkeys(
                    node
                    for node in app._tools.values()
                    if isinstance(node, ToolCallSummary)
                )
            )
            assert len(live) == 8
            assert [node.call_id for node in live] == [
                f"read-{index}" for index in range(4, 12)
            ]
            assert len(summaries) == 1
            assert summaries[0].count == 4
            assert summaries[0].call_ids == ["read-0", "read-1", "read-2", "read-3"]
            assert len(list(app.query(ToolCallWidget))) == 8
            assert len(list(app.query(ToolCallSummary))) == 1
            rendered = str(summaries[0].render())
            assert "[ Explored       4 tools]" in rendered

    asyncio.run(_run())


def test_explored_summary_splits_when_reasoning_separates_tool_batches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    app.live_tool_widget_limit = 3

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            for index in range(5):
                call_id = f"a-{index}"
                app.add_tool(call_id, "read_file")
                app.update_tool(
                    call_id, arguments={"path": f"a{index}.py"}, status="done", result="ok"
                )
            app.set_reasoning("Considering the next batch.", new=True)
            app.finish_reasoning()
            for index in range(5):
                call_id = f"b-{index}"
                app.add_tool(call_id, "read_file")
                app.update_tool(
                    call_id, arguments={"path": f"b{index}.py"}, status="done", result="ok"
                )
            await pilot.pause()

            summaries = list(app.query(ToolCallSummary))
            assert len(summaries) == 2
            assert summaries[0].count == 2
            assert summaries[1].count == 2
            assert "[ Explored       2 tools]" in str(summaries[0].render())
            assert "[ Explored       2 tools]" in str(summaries[1].render())
            assert len(list(app.query(ToolCallWidget))) == 6
            assert len(list(app.query(ReasoningWidget))) == 1


def test_explored_does_not_collapse_second_stretch_under_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    app.live_tool_widget_limit = 8

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            for index in range(5):
                call_id = f"a-{index}"
                app.add_tool(call_id, "read_file")
                app.update_tool(
                    call_id, arguments={"path": f"a{index}.py"}, status="done", result="ok"
                )
            app.set_reasoning("Considering the next batch.", new=True)
            app.finish_reasoning()
            for index in range(5):
                call_id = f"b-{index}"
                app.add_tool(call_id, "read_file")
                app.update_tool(
                    call_id, arguments={"path": f"b{index}.py"}, status="done", result="ok"
                )
            await pilot.pause()

            assert not list(app.query(ToolCallSummary))
            live = [
                node
                for node in app._tools.values()
                if isinstance(node, ToolCallWidget)
            ]
            assert [node.call_id for node in live] == [
                f"a-{index}" for index in range(5)
            ] + [f"b-{index}" for index in range(5)]
            assert len(list(app.query(ToolCallWidget))) == 10
            assert len(list(app.query(ReasoningWidget))) == 1

    asyncio.run(_run())


def test_thinking_gradient_timer_pauses_when_hidden_or_idle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._presenter is not None
            app._presenter.handle("run_started", {"model_id": "openai:test"})
            app._presenter.handle("turn_started", {"turn": 0})
            app._presenter.handle(
                "model_retry_scheduled",
                {"turn": 0, "retry_after": 2.5, "attempt": 1},
            )
            await pilot.pause()

            thinking = app.query_one(ThinkingStatus)
            assert thinking._animation_timer is not None
            assert thinking._animation_timer._active.is_set()

            thinking.set_visible(False)
            await pilot.pause()
            assert not thinking._animation_timer._active.is_set()

            thinking.set_visible(True)
            await pilot.pause()
            assert thinking._animation_timer._active.is_set()

            thinking.set_text("Completed · idle")
            await pilot.pause()
            assert not thinking._working
            assert not thinking._animation_timer._active.is_set()

    asyncio.run(_run())
