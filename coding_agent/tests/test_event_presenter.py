"""Unit tests for EventPresenter stream coalescing and chrome gating."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from coding_agent.tui.runtime.events import EventPresenter
from coding_agent.tui.runtime.state import UiRunState


class RecordingView:
    def __init__(self) -> None:
        self.assistant: list[tuple[str, bool]] = []
        self.reasoning: list[tuple[str, bool]] = []
        self.finished_reasoning = 0
        self.tools: list[tuple[str, str]] = []
        self.tool_updates: list[str] = []
        self.notices: list[str] = []
        self.thinking: list[str] = []
        self.working: list[str] = []
        self.finished_process: list[str] = []

    def set_assistant(self, text: str, *, new: bool = False) -> None:
        self.assistant.append((text, new))

    def set_thinking(self, text: str) -> None:
        self.thinking.append(text)

    def set_working(self, detail: str = "") -> None:
        self.working.append(detail)

    def set_reasoning(self, text: str, *, new: bool = False) -> None:
        self.reasoning.append((text, new))

    def finish_reasoning(self) -> None:
        self.finished_reasoning += 1

    def finish_process(self, title: str, *, collapse: bool = True) -> None:
        del collapse
        self.finished_process.append(title)

    def add_tool(self, call_id: str, name: str) -> None:
        self.tools.append((call_id, name))

    def update_tool(
        self,
        call_id: str,
        *,
        arguments: Optional[Mapping[str, Any]] = None,
        raw_arguments: str = "",
        status: str = "preparing",
        result: Any = None,
    ) -> None:
        del arguments, raw_arguments, result
        self.tool_updates.append(f"{call_id}:{status}")

    def add_notice(self, text: str, tone: str = "info") -> None:
        del tone
        self.notices.append(text)


def _presenter(*, chrome: list[str] | None = None) -> tuple[EventPresenter, RecordingView, list[str]]:
    view = RecordingView()
    status_calls = chrome if chrome is not None else []
    presenter = EventPresenter(
        state=UiRunState(),
        view=view,
        set_status=status_calls.append,
        workspace="/tmp/ws",
    )
    return presenter, view, status_calls


def test_text_deltas_coalesce_until_the_next_real_paint() -> None:
    presenter, view, chrome = _presenter()
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle("turn_started", {"turn": 0})
    chrome.clear()
    view.assistant.clear()

    for index in range(20):
        presenter.handle("text_delta", {"delta": f"x{index}"})

    assert view.assistant == []
    assert len(chrome) == 1
    assert "phase=streaming" in chrome[0]

    presenter.handle("turn_completed", {})
    assert len(view.assistant) == 1
    text, is_new = view.assistant[0]
    assert is_new
    assert text.startswith("x0")
    assert text.endswith("x19")
    assert text.count("x") == 20

    presenter.handle("text_delta", {"delta": "y"})
    assert len(view.assistant) == 1
    presenter.flush_stream_paints()
    assert len(view.assistant) == 2
    assert view.assistant[-1][0].endswith("y")
    assert view.assistant[-1][1] is True


def test_reasoning_deltas_coalesce_until_reasoning_ends() -> None:
    presenter, view, _chrome = _presenter()
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle("turn_started", {"turn": 0})
    view.reasoning.clear()

    presenter.handle(
        "reasoning_delta",
        {"delta": "Inspecting ", "text": "Inspecting ", "summary_index": 0},
    )
    presenter.handle(
        "reasoning_delta",
        {
            "delta": "the file.",
            "text": "Inspecting the file.",
            "summary_index": 0,
        },
    )
    assert view.reasoning == []
    assert view.finished_reasoning == 0

    presenter.handle("text_delta", {"delta": "Done."})
    assert view.reasoning == [("Inspecting the file.", True)]
    assert view.finished_reasoning == 1
    assert view.assistant == []


def test_tool_start_flushes_buffered_assistant_before_add_tool() -> None:
    presenter, view, _chrome = _presenter()
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle("turn_started", {"turn": 0})
    for chunk in ("Hello ", "world"):
        presenter.handle("text_delta", {"delta": chunk})
    assert view.assistant == []
    assert view.tools == []

    presenter.handle(
        "tool_call_started",
        {"tool_call_id": "read-1", "tool_name": "read_file"},
    )
    assert view.assistant == [("Hello world", True)]
    assert view.tools == [("read-1", "read_file")]
    assert view.finished_reasoning == 0


def test_chrome_does_not_refresh_on_every_token() -> None:
    presenter, _view, chrome = _presenter()
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle("turn_started", {"turn": 0})
    chrome.clear()

    presenter.handle("text_delta", {"delta": "a"})
    presenter.handle("text_delta", {"delta": "b"})
    presenter.handle("text_delta", {"delta": "c"})
    assert len(chrome) == 1

    presenter.handle(
        "usage",
        {
            "prompt_tokens": 12,
            "completion_tokens": 3,
            "total_tokens": 15,
            "cumulative_tokens": 15,
        },
    )
    assert len(chrome) == 2
    assert "tokens=15" in chrome[-1]


def test_run_summary_shows_summary_so_far() -> None:
    presenter, view, _chrome = _presenter()
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle(
        "run_summary",
        {
            "label": "summary so far",
            "summary": "Patched the retry helper.\nAdded after-run learning recap.",
        },
    )
    assert view.notices == [
        "summary so far\nPatched the retry helper.\nAdded after-run learning recap."
    ]
