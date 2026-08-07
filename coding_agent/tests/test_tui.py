"""Smoke tests for the Textual TUI scaffold (no live API)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core_ai import ModelRegistry
from core_ai.types import Message
from core_harness import HarnessResult
from coding_agent.agent import CodingAgent
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.commands import command_matches, find_model, model_matches
from coding_agent.tui.control_plane import ControlPlaneEvent, TextualControlPlane
from coding_agent.tui.theme import SYMPHONY_CODE_THEME
from coding_agent.tui.widgets import (
    PatchDiffWidget,
    ReadFileWidget,
    ReasoningWidget,
    RunProcess,
    SlashMenu,
    ThinkingStatus,
)


def test_tui_composes_without_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    assert background.get_truecolor().hex == "#202020"


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
            assert read.arguments["path"] == "src/app.py"
            assert "120 in / 30 out" in str(thinking.render())
            assert "18 reasoning" in str(thinking.render())
            assert [widget.reasoning_text for widget in reasoning] == [
                "Inspecting the requested file.",
                "Choosing an implementation.",
            ]
            assert app._assistant is not None

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
            assert process.collapsed
            await pilot.click("CollapsibleTitle")
            assert not process.collapsed

    asyncio.run(_run())


def test_slash_command_discovery_and_model_resolution() -> None:
    assert [command.name for command in command_matches("/m")] == ["model"]
    assert find_model("gpt-5.4-mini").id == "openai:gpt-5.4-mini"  # type: ignore[union-attr]
    assert find_model("gpt-4.1-mini").id == "openai:gpt-4.1-mini"  # type: ignore[union-attr]
    assert find_model("missing") is None
    assert [model.id for model in model_matches("4.1-m")] == [
        "openai:gpt-4.1-mini"
    ]


def test_reasoning_usage_without_summary_shows_fallback(
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
            assert "did not include" in app.query_one(ReasoningWidget).reasoning_text

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
            self.compacted = False

        async def compact_conversation(self) -> tuple[int, int]:
            self.compacted = True
            return (14, 9)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            fake = FakeAgent()
            app._agent = fake  # type: ignore[assignment]

            prompt = app.query_one("#prompt")
            prompt.value = "/m"  # type: ignore[attr-defined]
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
            assert fake.harness.model_id == "openai:gpt-5.4-mini"
            assert app._ui_state.model_id == "openai:gpt-5.4-mini"

            await app._run_slash_command("/compact")
            assert fake.compacted

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
            assert widget.arguments["path"] == "src/greeting.py"
            assert widget._stats(diff) == (2, 2)
            assert '-    return "hello"' in diff
            assert '+    return f"hello {name}"' in diff

    asyncio.run(_run())
