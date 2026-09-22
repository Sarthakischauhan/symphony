"""Unit tests for EventPresenter stream coalescing and chrome gating."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from coding_agent.tui.runtime.events import EventPresenter
from coding_agent.tui.runtime.state import UiRunState


class RecordingView:
    def __init__(self) -> None:
        self.assistant: list[tuple[str, bool]] = []
        self.finished_assistant = 0
        self.reasoning: list[tuple[str, bool]] = []
        self.finished_reasoning = 0
        self.tools: list[tuple[str, str]] = []
        self.tool_updates: list[str] = []
        self.tool_payloads: list[tuple[str, Optional[Mapping[str, Any]], str]] = []
        self.notices: list[str] = []
        self.updates: list[str] = []
        self.run_summaries: list[tuple[str, str, str]] = []
        self.thinking: list[str] = []
        self.working: list[str] = []
        self.finished_process: list[str] = []
        self._agent = None

    def set_assistant(self, text: str, *, new: bool = False) -> None:
        self.assistant.append((text, new))

    def finish_assistant(self) -> None:
        self.finished_assistant += 1

    def set_thinking(self, text: str) -> None:
        self.thinking.append(text)

    def set_working(self, detail: str = "") -> None:
        self.working.append(detail)

    def set_churning(self, turn: int = 0) -> None:
        del turn
        return None

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
        tool_name: str = "tool",
        arguments: Optional[Mapping[str, Any]] = None,
        raw_arguments: str = "",
        status: str = "preparing",
        result: Any = None,
    ) -> None:
        del result, tool_name
        self.tool_updates.append(f"{call_id}:{status}")
        self.tool_payloads.append((call_id, arguments, raw_arguments))

    def add_notice(self, text: str, tone: str = "info") -> None:
        del tone
        self.notices.append(text)

    def add_update(self, text: str, hint: str = "") -> None:
        del hint
        self.updates.append(text)

    def add_run_summary(
        self,
        summary: str,
        *,
        label: str = "summary so far",
        event_type: str = "run_summary",
    ) -> None:
        self.run_summaries.append((label, summary, event_type))


def _presenter(
    *,
    schedule: list | None = None,
    chrome: list[str] | None = None,
) -> tuple[EventPresenter, RecordingView, list[str]]:
    view = RecordingView()
    status_calls = chrome if chrome is not None else []
    kwargs: dict[str, Any] = dict(
        state=UiRunState(),
        view=view,
        set_status=status_calls.append,
        workspace="/tmp/ws",
    )
    if schedule is not None:
        kwargs["schedule_flush"] = schedule.append
    presenter = EventPresenter(**kwargs)
    return presenter, view, status_calls


def test_completed_metrics_use_run_usage_and_unique_call_counts() -> None:
    presenter, view, _ = _presenter()
    presenter.handle("run_started", {"ts": 100.0})
    for turn in range(44):
        presenter.handle("turn_started", {"turn": turn})
    # Replayed starts and streaming fragments must not inflate the counters.
    presenter.handle("turn_started", {"turn": 43})
    for index in range(56):
        call = {"tool_call_id": str(index), "tool_name": "read_file"}
        presenter.handle("tool_call_started", call)
        presenter.handle("tool_call_delta", {**call, "delta": "{}"})
        presenter.handle("tool_execution_started", call)
    presenter.handle("tool_execution_started", call)
    presenter.handle("usage", {"prompt_tokens": 42030, "completion_tokens": 100})
    presenter.handle("run_completed", {
        "ts": 292.9,
        "usage": {"prompt_tokens": 1620916, "completion_tokens": 7031,
                  "reasoning_tokens": 2137, "total_tokens": 1627947},
        "context": {"tokens_used": 42030},
    })
    assert view.finished_process[-1] == (
        "3m 12s (↑1.62M ↓7.03k) · 44 model calls · 56 tool calls"
    )
    # Exact values remain available to context/status consumers.
    assert presenter.state.metrics.prompt_tokens == 1620916
    assert presenter.state.metrics.reasoning_tokens == 2137
    assert presenter.state.metrics.tokens_used == 42030


def test_completed_metrics_reset_and_use_monotonic_time_without_timestamps(monkeypatch) -> None:
    presenter, view, _ = _presenter()
    presenter.handle("run_started", {"ts": 100.0})
    presenter.handle("turn_started", {"turn": 0})
    presenter.handle("tool_execution_started", {"tool_call_id": "old"})
    presenter.handle("usage", {"prompt_tokens": 100, "estimated": True})
    presenter.handle("run_completed", {"ts": 105.0, "usage": {"prompt_tokens": 100}})
    assert "↑~100" in view.finished_process[-1]

    clock = iter([10.0, 15.9])
    monkeypatch.setattr("coding_agent.tui.runtime.events.time.monotonic", lambda: next(clock))
    presenter.handle("run_started", {})
    presenter.handle("turn_started", {"turn": 0})
    presenter.handle("model_retry_scheduled", {"attempt": 2, "retry_after": 1})
    # Logical model calls count turns; retries do not count as extra turns.
    presenter.handle("run_completed", {
        "usage": {"prompt_tokens": 1, "completion_tokens": 53, "total_tokens": 54},
    })
    assert view.finished_process[-1] == "5s (↑1 ↓53) · 1 model call · 0 tool calls"


def test_completed_output_is_replaced_before_process_is_finished() -> None:
    presenter, view, _ = _presenter()
    presenter.handle("run_started", {"ts": 100.0})
    presenter.handle("turn_started", {"turn": 0})
    presenter.handle("text_delta", {"delta": "intermediate"})
    presenter.handle(
        "run_completed",
        {
            "ts": 101.0,
            "output_text": "**final**\n\n- formatted",
            "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
        },
    )
    assert view.assistant[-1] == ("**final**\n\n- formatted", False)
    assert view.finished_assistant == 1
    assert view.finished_process[-1].endswith("1 model call · 0 tool calls")


def test_collected_events_are_ignored_by_the_presenter() -> None:
    presenter, view, _ = _presenter()
    presenter.handle("run_started", {"ts": 100.0})
    presenter.handle(
        "tool_call_started",
        {"tool_call_id": "read-1", "tool_name": "read_file", "collected": True},
    )
    presenter.handle("collected", {"run_id": "run", "seq": 3, "collected": True})
    presenter.handle("text_delta", {"delta": "final", "collected": True})
    presenter.handle("run_completed", {"ts": 101.0, "output_text": "final"})
    assert view.tools == []
    assert view.assistant[-1] == ("final", False)


def test_text_deltas_coalesce_to_one_scheduled_paint() -> None:
    scheduled: list = []
    presenter, view, chrome = _presenter(schedule=scheduled)
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle("turn_started", {"turn": 0})
    chrome.clear()
    view.assistant.clear()

    for index in range(20):
        presenter.handle("text_delta", {"delta": f"x{index}"})

    assert view.assistant == []
    assert len(scheduled) == 1
    assert len(chrome) == 1
    assert "phase=streaming" in chrome[0]

    scheduled[0]()
    assert len(view.assistant) == 1
    text, is_new = view.assistant[0]
    assert is_new
    assert text.startswith("x0")
    assert text.endswith("x19")
    assert text.count("x") == 20

    presenter.handle("text_delta", {"delta": "y"})
    assert len(view.assistant) == 1
    assert len(scheduled) == 2
    scheduled[1]()
    assert len(view.assistant) == 2
    assert view.assistant[-1][0].endswith("y")
    assert view.assistant[-1][1] is False


def test_reasoning_deltas_coalesce_to_one_scheduled_paint() -> None:
    scheduled: list = []
    presenter, view, _chrome = _presenter(schedule=scheduled)
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
    assert len(scheduled) == 1

    scheduled[0]()
    assert view.reasoning == [("Inspecting the file.", True)]
    assert view.finished_reasoning == 0

    presenter.handle("text_delta", {"delta": "Done."})
    assert view.finished_reasoning == 1
    assert len(scheduled) == 2


def test_delta_only_reasoning_fragments_are_accumulated() -> None:
    scheduled: list = []
    presenter, view, _chrome = _presenter(schedule=scheduled)
    presenter.handle("run_started", {"model_id": "anthropic:test"})
    presenter.handle("turn_started", {"turn": 0})
    presenter.handle("reasoning_delta", {"delta": "Plan", "summary_index": 0})
    presenter.handle("reasoning_delta", {"delta": " the change", "summary_index": 0})

    scheduled[0]()

    assert view.reasoning == [("Plan the change", True)]


def test_partial_tool_argument_json_exposes_protocol_path() -> None:
    scheduled: list = []
    presenter, view, _chrome = _presenter(schedule=scheduled)
    presenter.handle(
        "tool_call_started",
        {"tool_call_id": "read-1", "tool_name": "read_file"},
    )
    presenter.handle(
        "tool_call_delta",
        {"tool_call_id": "read-1", "delta": '{"path":"history.py"'},
    )
    scheduled[0]()
    assert view.tool_payloads == [
        ("read-1", {"path": "history.py"}, '{"path":"history.py"')
    ]


def test_tool_argument_deltas_coalesce_to_one_scheduled_paint() -> None:
    scheduled: list = []
    presenter, view, _chrome = _presenter(schedule=scheduled)
    presenter.handle(
        "tool_call_started",
        {"tool_call_id": "read-1", "tool_name": "read_file"},
    )

    for delta in ('{"pa', 'th":"src/', 'app.py"}'):
        presenter.handle("tool_call_delta", {"tool_call_id": "read-1", "delta": delta})

    assert view.tool_updates == []
    assert len(scheduled) == 1

    scheduled[0]()
    assert view.tool_updates == ["read-1:preparing"]
    assert view.tool_payloads == [
        ("read-1", {"path": "src/app.py"}, '{"path":"src/app.py"}')
    ]


def test_tool_start_flushes_buffered_assistant_before_add_tool() -> None:
    # A scheduler is required to observe buffering: without one the presenter
    # paints deltas immediately (the intended fallback for non-Textual hosts).
    scheduled: list = []
    presenter, view, _chrome = _presenter(schedule=scheduled)
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle("turn_started", {"turn": 0})
    for chunk in ("Hello ", "world"):
        presenter.handle("text_delta", {"delta": chunk})
    assert view.assistant == []
    assert view.tools == []
    assert len(scheduled) == 1

    presenter.handle(
        "tool_call_started",
        {"tool_call_id": "read-1", "tool_name": "read_file"},
    )
    assert view.assistant == [("Hello world", True)]
    assert view.tools == []
    assert view.finished_reasoning == 0

    # The deferred paint is now a no-op: the buffer was drained before add_tool.
    scheduled[0]()
    assert view.assistant == [("Hello world", True)]


def test_stream_deltas_paint_immediately_without_scheduler() -> None:
    presenter, view, _chrome = _presenter()
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle("turn_started", {"turn": 0})
    presenter.handle("text_delta", {"delta": "Hello "})
    presenter.handle("text_delta", {"delta": "world"})
    assert view.assistant == [("Hello ", True), ("Hello world", False)]


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
    assert view.notices == []
    assert view.run_summaries == [
        (
            "summary so far",
            "Patched the retry helper.\nAdded after-run learning recap.",
            "run_summary",
        )
    ]


def test_compaction_completed_updates_context_metrics_and_repaints_chrome() -> None:
    presenter, view, chrome = _presenter()
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle(
        "context",
        {
            "turn": 0,
            "context_limit": 100_000,
            "tokens_used": 90_000,
            "context_left": 10_000,
            "utilization": 0.9,
        },
    )
    chrome.clear()

    presenter.handle("compaction_started", {"turn": 1, "message_count": 30, "manual": True})
    presenter.handle(
        "compaction_completed",
        {
            "turn": 1,
            "message_count_before": 30,
            "message_count_after": 12,
            "estimated_tokens_before": 90_000,
            "estimated_tokens_after": 25_000,
            "context_limit": 100_000,
            "manual": True,
        },
    )

    metrics = presenter.state.metrics
    assert metrics.tokens_used == 25_000
    assert metrics.context_left == 75_000
    assert metrics.context_limit == 100_000
    assert metrics.utilization == 0.25
    assert presenter.state.detail == "ready"
    assert chrome and "tokens=25000" in chrome[-1]
    assert "context_left=75000/100000" in chrome[-1]
    assert view.updates[-1] == (
        "Compacted context · 30 → 12 messages · ~90,000 → ~25,000 tokens"
    )


def test_compaction_completed_without_estimate_keeps_metrics() -> None:
    presenter, view, _chrome = _presenter()
    presenter.handle("run_started", {"model_id": "openai:test"})
    presenter.handle("context", {"context_limit": 1_000, "tokens_used": 400, "context_left": 600})

    presenter.handle(
        "compaction_completed",
        {"message_count_before": 9, "message_count_after": 4},
    )

    assert presenter.state.metrics.tokens_used == 400
    assert presenter.state.metrics.context_left == 600
    assert view.updates[-1] == "Compacted context · 9 → 4 messages"


def test_jev_recommendation_update_toastable_vs_silent() -> None:
    from types import SimpleNamespace

    from coding_agent.tui.runtime.events import jev_recommendation_update

    assert jev_recommendation_update(None) is None
    for action in ("replan", "retry", "review", "gather", "ask"):
        text = jev_recommendation_update(SimpleNamespace(action=action, reason="need more context"))
        assert text == f"Jev → {action}: need more context"
    for action in ("continue_normally", "finish", "continue", None):
        assert jev_recommendation_update(SimpleNamespace(action=action, reason="done")) is None


def test_jev_recommendation_update_clips_reason() -> None:
    from types import SimpleNamespace

    from coding_agent.tui.runtime.events import (
        _JEV_TOAST_REASON_LIMIT,
        jev_recommendation_update,
    )

    long_reason = "x" * (_JEV_TOAST_REASON_LIMIT + 40)
    text = jev_recommendation_update(SimpleNamespace(action="retry", reason=long_reason))
    assert text is not None
    assert text.startswith("Jev → retry: ")
    clipped = text.removeprefix("Jev → retry: ")
    assert len(clipped) == _JEV_TOAST_REASON_LIMIT
    assert clipped.endswith("…")


def test_run_completed_shows_jev_toast_for_user_facing_decision() -> None:
    from types import SimpleNamespace

    presenter, view, _ = _presenter()
    view._agent = SimpleNamespace(
        harness=SimpleNamespace(
            addons=[
                SimpleNamespace(
                    name="jev",
                    last_decision=SimpleNamespace(action="review", reason="claims look unsupported"),
                )
            ]
        )
    )
    presenter.handle("run_started", {"ts": 1.0})
    presenter.handle("run_completed", {"ts": 2.0, "output_text": "done"})
    assert view.updates == ["Jev → review: claims look unsupported"]


def test_run_completed_skips_toast_when_jev_silent_or_missing() -> None:
    from types import SimpleNamespace

    presenter, view, _ = _presenter()
    presenter.handle("run_started", {"ts": 1.0})
    presenter.handle("run_completed", {"ts": 2.0})
    assert view.updates == []

    view._agent = SimpleNamespace(
        harness=SimpleNamespace(
            addons=[
                SimpleNamespace(
                    name="jev",
                    last_decision=SimpleNamespace(action="continue_normally", reason="ok"),
                )
            ]
        )
    )
    presenter.handle("run_started", {"ts": 3.0})
    presenter.handle("run_completed", {"ts": 4.0})
    assert view.updates == []
