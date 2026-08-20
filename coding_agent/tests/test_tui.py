"""Smoke tests for the Textual TUI scaffold (no live API)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from textual import events
from textual.containers import VerticalScroll
from textual.widgets import Static

from core_ai import ModelRegistry
from core_ai.types import Message
from core_harness import HarnessResult
from coding_agent.agent import CodingAgent
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.commands import (
    SLASH_COMMANDS,
    command_matches,
    find_mode,
    find_model,
    mode_matches,
    model_matches,
)
from coding_agent.tui.control_plane import ControlPlaneEvent, TextualControlPlane
from coding_agent.tui.file_selector import (
    active_file_mention,
    complete_file_mention,
    file_matches,
)
from coding_agent.tui.modal import ContentModal, DiffModal, PlanModal
from coding_agent.tui.modal.diff import DiffFileCard
from coding_agent.tui.modal.components import PlanSectionCard
from coding_agent.tui.modal.plan import _plan_sections
from coding_agent.tui.resume import ResumeApp, SessionOption, load_session_options
from coding_agent.tui.theme import SYMPHONY_CODE_THEME, themed_markdown
from coding_agent.tui.widgets import (
    BashToolWidget,
    PatchDiffWidget,
    PromptInput,
    ReadFileWidget,
    ReasoningWidget,
    RunProcess,
    ThinkingStatus,
    UserMessage,
)
from coding_agent.tui.slash_menu import SlashMenu


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

            await pilot.press("enter")
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
        "coding_agent.tui.modal.diff.read_workspace_diff",
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
    assert [command.name for command in command_matches("/lea")] == ["learning"]
    assert find_model("gpt-5.6-luna").id == "openai:gpt-5.6-luna"  # type: ignore[union-attr]
    assert find_model("gpt-4.1-mini").id == "openai:gpt-4.1-mini"  # type: ignore[union-attr]
    assert find_model("missing") is None
    assert [model.id for model in model_matches("4.1-m")] == [
        "openai:gpt-4.1-mini"
    ]
    assert find_mode("Plan").id == "plan"  # type: ignore[union-attr]
    assert [mode.id for mode in mode_matches("")] == ["build", "plan"]


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

            menu = app.query_one(SlashMenu)
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

            menu = app.query_one(SlashMenu)
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
            menu = app.query_one(SlashMenu)

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
                    "default": "Deny",
                    "kind": "approval",
                    "tool_name": "bash",
                }
            )
            await pilot.pause()

            menu = app.query_one(SlashMenu)
            assert menu.has_class("permission-menu")
            assert menu.selected_value == "Deny"
            assert menu.highlighted == menu._option_offset + 1
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
            state=SimpleNamespace(context_limit=lambda _model_id: 64_000),
        ),
        learning_loop=None,
        set_mode=lambda mode: selected_modes.append(mode),
    )

    def _load_dotenv(*, override: bool) -> None:
        loaded.append(override)

    def _build_agent(**kwargs: Any) -> Any:
        built_with.update(kwargs)
        return reloaded_agent

    monkeypatch.setattr("coding_agent.tui.commands.reload.load_dotenv", _load_dotenv)
    monkeypatch.setattr("coding_agent.tui.commands.reload.build_agent", _build_agent)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            selected_modes.clear()
            built_with.clear()
            app._agent = SimpleNamespace(
                session_id="current-session", learning_loop=None
            )
            app._mount_transcript(UserMessage("Keep this conversation"))
            await pilot.pause()

            await app._command_manager.run("/reload")
            await pilot.pause()

            assert loaded == [True]
            assert built_with["session_id"] == "current-session"
            assert selected_modes == ["build"]
            assert app._agent is reloaded_agent
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

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            fake = FakeAgent()
            app._agent = fake  # type: ignore[assignment]

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
            assert app.query_one(SlashMenu).display
            await pilot.press("tab")
            assert prompt.value == "/model"  # type: ignore[attr-defined]

            prompt.value = "/model 4.1-m"  # type: ignore[attr-defined]
            await pilot.pause()
            assert app.query_one(SlashMenu).display
            await pilot.press("tab")
            assert prompt.value == "/model openai:gpt-4.1-mini"  # type: ignore[attr-defined]

            prompt.value = "/model "  # type: ignore[attr-defined]
            await pilot.pause()
            menu = app.query_one(SlashMenu)
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

            await app._run_slash_command("/compact")
            assert fake.compacted

            opened: list[object] = []
            app.push_screen = lambda screen, *args: opened.append(screen)  # type: ignore[method-assign]
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
        enable_learning=False,
        tools=[],
    )
    messages = [Message(role="system", content="system")]
    messages.extend(Message(role="user", content=f"message {i}") for i in range(12))

    async def _run() -> None:
        await agent.persistence.save_conversation(
            session_id=agent.session_id,
            messages=messages,
        )
        assert await agent.compact_conversation(keep_recent=8) == (13, 9)
        saved = await agent.persistence.load_conversation(session_id=agent.session_id)
        assert len(saved) == 9
        assert saved[0].role == "system"
        assert saved[-1].content == "message 11"

    asyncio.run(_run())
    assert [event for event, _ in control_plane.events] == [
        "compaction_started",
        "compaction_completed",
    ]


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

            widget.scroll_visible()
            await pilot.pause()
            await pilot.click(widget.query_one("CollapsibleTitle"))
            await pilot.pause()
            assert not widget.collapsed

    asyncio.run(_run())
