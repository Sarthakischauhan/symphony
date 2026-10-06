"""Restore persisted conversation messages into a TUI transcript."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from coding_agent.agent import CodingAgent
from coding_agent.addons.persistence.collection import COLLECTABLE_EVENT_TYPES, is_collected
from coding_agent.tui.runtime.events import _duration
from coding_agent.tui.tools.activity import choose_completion_verb
from coding_agent.tui.tools.images import display_from_content
from coding_agent.tui.tools.snapshots import (
    CompletedRunSummary,
    ThoughtSnapshot,
    ToolCallSnapshot,
    ToolCallSummary,
    snapshot_from_call,
)
from coding_agent.tui.transcript import UserMessage
from core_ai.content import text_from_content
from core_harness.context import COMPACTED_CONTEXT_MARK, estimate_prompt_tokens


class HistoryView(Protocol):
    def add_notice(self, text: str, tone: str = "info") -> None: ...

    def mount_transcript(self, widget: Any) -> None: ...

    def set_context_metrics(self, tokens_used: int, context_limit: int) -> None: ...

    def finalize_transcript_history(self) -> None: ...


async def load_session_history(agent: CodingAgent, view: HistoryView) -> None:
    """Restore compact history with interactive child and background-job cards."""
    loader = getattr(agent.persistence, "load_transcript", agent.persistence.load_conversation)
    messages = await loader(session_id=agent.session_id)
    # The visual transcript may retain turns that were compacted out of the
    # model context. Footer usage must describe the active context projection,
    # which is what /context reports and what the next request will send.
    context_messages = await agent.persistence.load_conversation(session_id=agent.session_id)
    context_limit = agent.harness.state.context_limit(agent.harness.model_id)
    view.set_context_metrics(estimate_prompt_tokens(context_messages), context_limit)
    view.add_notice(f"Resumed session · {agent.session_id}")

    load_events = getattr(agent.persistence, "load_events", None)
    events = await load_events(session_id=agent.session_id) if callable(load_events) else []
    restored = _history_widgets(messages, events)
    tools = getattr(view, "_tools", None)
    if isinstance(tools, dict):
        from coding_agent.tui.tools.calls import ToolCallWidget

        tools.update((widget.call_id, widget) for widget in restored if isinstance(widget, ToolCallWidget))
    mount_batch = getattr(view, "mount_transcript_batch", None)
    if callable(mount_batch):
        mount_batch(restored)
    else:
        for widget in restored:
            view.mount_transcript(widget)
    view.finalize_transcript_history()


def _history_widgets(
    messages: list[Any],
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> list[Any]:
    from coding_agent.tui.tools.calls import make_tool_widget
    from coding_agent.tui.transcript import AssistantMessage

    # Parent journals can contain forwarded child events. They belong to the
    # child screen, never to the parent's tool/thought reconstruction.
    events = [
        (kind, payload) for kind, payload in events or []
        if not payload.get("parent_id") or kind.startswith("agent_")
    ]
    notifications, job_results = _completion_notifications(messages, events)
    restored: list[Any] = []
    pending: dict[str, dict[str, Any]] = {}
    batch: list[ToolCallSnapshot | ThoughtSnapshot] = []
    thoughts = _thoughts_from_events(events or [])
    event_calls = _tool_fields_from_events(events or [])
    collected_runs = _collected_run_ids(events or [])
    run_completions = _run_completions_from_events(events or [])
    current_run: list[Any] = []
    collecting = False
    active_run_id = ""

    def flush_batch() -> None:
        if not batch:
            return
        summary = ToolCallSummary(tuple(batch))
        if collecting:
            current_run.append(summary)
        else:
            restored.append(summary)
        batch.clear()

    def add_snapshot(snapshot: ToolCallSnapshot | ThoughtSnapshot) -> None:
        batch.append(snapshot)

    def flush_run() -> None:
        nonlocal collecting
        flush_batch()
        if current_run:
            restored.extend(
                _fold_collected_run(
                    current_run,
                    **(run_completions.pop(0) if run_completions else {}),
                )
            )
            current_run.clear()
        collecting = False

    def add_visible(widget: Any) -> None:
        if collecting:
            current_run.append(widget)
        else:
            restored.append(widget)

    def add_call(fields: dict[str, Any]) -> None:
        nonlocal collecting, active_run_id
        run_id = str(fields.get("run_id") or "")
        if collected_runs and run_id and run_id != active_run_id:
            flush_run()
            active_run_id = run_id
        if collected_runs == {""}:
            collecting = True
        elif collected_runs:
            collecting = bool(run_id and run_id in collected_runs)
        arguments = fields.get("arguments") or {}
        if fields["tool_name"] in {"spawn_agent", "bash"}:
            flush_batch()
            widget = make_tool_widget(str(fields["call_id"]), str(fields["tool_name"]))
            widget.set_arguments(arguments, str(fields.get("raw_arguments") or ""))
            result = str(fields.get("result") or "")
            job = re.search(r"started background job ([A-Za-z0-9_-]+)", result)
            if job and job.group(1) in job_results:
                result = job_results[job.group(1)]
            widget.set_result(result)
            if fields.get("status") == "failed":
                widget.status = "failed"
            add_visible(widget)
        else:
            add_snapshot(snapshot_from_call(**{key: value for key, value in fields.items() if key != "run_id"}))

    for index, message in enumerate(messages):
        if index in notifications:
            continue
        if message.role == "user":
            if text_from_content(message.content).startswith(COMPACTED_CONTEXT_MARK):
                continue
            flush_run()
            pending.clear()
            text, images = display_from_content(message.content)
            restored.append(UserMessage(text, images=images))
            collecting = bool(collected_runs)
        elif message.role == "assistant":
            content = text_from_content(message.content)
            calls = [_call_fields(call) for call in message.tool_calls or []]
            for fields in calls:
                call_id = str(fields["call_id"])
                fields = _merge_call_fields(fields, event_calls.get(call_id, {}))
                run_id = str(fields.get("run_id") or "")
                if collected_runs and run_id and run_id != active_run_id:
                    flush_run()
                    active_run_id = run_id
                if collected_runs == {""}:
                    collecting = True
                elif collected_runs:
                    collecting = bool(run_id and run_id in collected_runs)
            if content:
                flush_batch()
                add_visible(AssistantMessage(content, streaming=False))
            if thoughts:
                add_snapshot(thoughts.pop(0))
            for fields in calls:
                call_id = str(fields["call_id"])
                pending[call_id] = _merge_call_fields(fields, event_calls.pop(call_id, {}))
        elif message.role == "tool":
            call_id = str(message.tool_call_id or "")
            fields = pending.pop(call_id, None) or event_calls.pop(call_id, None) or {
                "call_id": call_id or "history-tool",
                "tool_name": "tool",
                "arguments": {},
                "raw_arguments": "",
            }
            result = text_from_content(message.content)
            add_call({
                **fields,
                "result": result,
                "status": "failed" if result.startswith("error:") else "done",
            })

    for fields in pending.values():
        add_call({"status": "done", **fields})
    for leftover_fields in event_calls.values():
        add_call({"status": "done", **leftover_fields})
    for leftover in thoughts:
        add_snapshot(leftover)
    flush_run()
    return restored


def _completion_notifications(
    messages: list[Any], events: list[tuple[str, dict[str, Any]]],
) -> tuple[set[int], dict[str, str]]:
    """Recognize legacy runtime user messages only for known children/jobs.

    These messages remain in model context, but are not actual user prompts.
    Correlation avoids hiding ordinary user text mentioning background work.
    """
    children = {
        str(payload["child_id"]) for kind, payload in events
        if kind == "agent_spawned" and payload.get("child_id")
    }
    jobs: set[str] = set()
    tool_results = {str(message.tool_call_id): message for message in messages if message.role == "tool"}
    for message in messages:
        if message.role == "assistant":
            for call in message.tool_calls or []:
                fields = _call_fields(call)
                if fields["tool_name"] != "spawn_agent":
                    continue
                # Older journals may lack agent_spawned events, but the spawn
                # result still carries the child identity.
                result = tool_results.get(fields["call_id"])
                if result is None:
                    continue
                try:
                    child = json.loads(text_from_content(result.content))
                except (ValueError, TypeError):
                    continue
                if isinstance(child, dict) and child.get("child_id"):
                    children.add(str(child["child_id"]))
        if message.role == "tool":
            match = re.match(r"started background job ([A-Za-z0-9_-]+)\nlog: ", text_from_content(message.content))
            if match:
                jobs.add(match.group(1))
    hidden: set[int] = set()
    results: dict[str, str] = {}
    for index, message in enumerate(messages):
        if message.role != "user":
            continue
        text = text_from_content(message.content)
        child = re.match(r"Subagent .+ \(([^()]+)\) (?:completed|failed|cancelled|interrupted)\.\n", text)
        job = re.match(r"Background job ([A-Za-z0-9_-]+) .+ after [\d.]+s\. Last output:\n", text)
        if child and child.group(1) in children:
            hidden.add(index)
        elif job and job.group(1) in jobs and "\nFull log: " in text:
            hidden.add(index)
            results[job.group(1)] = text
    return hidden, results


def _thoughts_from_events(events: list[tuple[str, dict[str, Any]]]) -> list[ThoughtSnapshot]:
    """Restore completed thoughts from persisted events when they exist.

    Live reasoning deltas are skipped by session persistence, so this only
    reconstructs compact snapshots from completed thought payloads. History
    never remounts live ReasoningWidget cards.
    """
    thoughts: list[ThoughtSnapshot] = []
    for event_type, payload in events:
        if event_type not in {"reasoning_completed", "thought_completed"}:
            continue
        content = str(payload.get("text") or payload.get("content") or "").strip()
        if not content:
            continue
        title = str(payload.get("title") or "Thought").strip() or "Thought"
        thoughts.append(ThoughtSnapshot(title=title, content=content))
    return thoughts


def _collected_run_ids(events: list[tuple[str, dict[str, Any]]]) -> set[str]:
    """Runs whose persisted mid-run work was explicitly folded.

    Empty means a legacy collected event had no run ID. Those journals cannot
    distinguish runs, so resume keeps the historical session-wide fold.
    """
    collected = [
        payload for event_type, payload in events
        if event_type in COLLECTABLE_EVENT_TYPES and is_collected(payload)
    ]
    if not collected:
        return set()
    if any(not payload.get("run_id") for payload in collected):
        return {""}
    return {str(payload["run_id"]) for payload in collected}


def _tool_fields_from_events(
    events: list[tuple[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Use persisted protocol arguments as the source of truth for history tools."""
    calls: dict[str, dict[str, Any]] = {}
    for event_type, payload in events:
        if event_type not in {"tool_call_started", "tool_execution_started", "tool_execution_completed", "agent_spawned"}:
            continue
        call_id = str(payload.get("tool_call_id") or "")
        if not call_id:
            continue
        current = calls.setdefault(
            call_id,
            {
                "call_id": call_id,
                "tool_name": "tool",
                "arguments": {},
                "raw_arguments": "",
                "run_id": "",
            },
        )
        tool_name = str(payload.get("tool_name") or "")
        if tool_name:
            current["tool_name"] = tool_name
        arguments = payload.get("arguments")
        if isinstance(arguments, dict) and arguments:
            current["arguments"] = dict(arguments)
            current["raw_arguments"] = json.dumps(arguments, ensure_ascii=False)
        run_id = str(payload.get("run_id") or "")
        if run_id:
            current["run_id"] = run_id
        if event_type == "agent_spawned":
            call_id = str(payload.get("tool_call_id") or "")
            if call_id:
                calls.setdefault(call_id, {
                    "call_id": call_id,
                    "tool_name": "spawn_agent",
                    "arguments": {},
                    "raw_arguments": "",
                    "run_id": "",
                })["run_id"] = str(payload.get("run_id") or calls[call_id]["run_id"])
            continue
        if event_type == "tool_execution_completed":
            result = payload.get("result")
            if result:
                current["result"] = str(result)
            status = str(payload.get("status") or "")
            if status in {"error", "cancelled", "timeout"}:
                current["status"] = "failed"
            elif status:
                current["status"] = "done"
    return calls


def _merge_call_fields(preferred: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fallback)
    for key, value in preferred.items():
        if value in ("", None, {}, []) or key == "tool_name" and value == "tool":
            continue
        merged[key] = value
    return merged


def _run_completions_from_events(
    events: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, str]]:
    """Restore completed-run verb and duration from persisted run events."""
    completions: list[dict[str, str]] = []
    started: dict[str, float] = {}
    fallback_started: float | None = None
    for event_type, payload in events:
        run_id = str(payload.get("run_id") or "")
        if event_type == "run_started":
            ts = payload.get("ts")
            if isinstance(ts, (int, float)):
                if run_id:
                    started[run_id] = float(ts)
                else:
                    fallback_started = float(ts)
            continue
        if event_type not in {"run_completed", "run_completed_meta"}:
            continue
        duration = str(payload.get("duration") or "").strip()
        stored = payload.get("elapsed_seconds")
        if not duration and isinstance(stored, (int, float)):
            duration = _duration(float(stored))
        if not duration and event_type == "run_completed":
            start = started.get(run_id, fallback_started)
            end = payload.get("ts")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                duration = _duration(max(0.0, float(end) - float(start)))
        verb = str(payload.get("completion_verb") or "").strip()
        if event_type == "run_completed_meta" and completions:
            current = completions[-1]
            if verb:
                current["verb"] = verb
            if duration:
                current["duration"] = duration
            continue
        completions.append({"verb": verb, "duration": duration})
    return completions


def _folds_on_completion(item: Any) -> bool:
    """Match the live completed-run rule for foreground cards."""
    from coding_agent.tui.tools.calls import BashToolWidget, PatchDiffWidget, ToolCallWidget

    return isinstance(item, ToolCallWidget) and (
        not item.keep_in_transcript
        or isinstance(item, PatchDiffWidget)
        or isinstance(item, BashToolWidget) and not item.arguments.get("background")
    )


def _fold_collected_run(
    items: list[Any],
    *,
    verb: str = "",
    duration: str = "",
) -> list[Any]:
    """Fold mid-run history into a completed-run collection, keep the final reply."""
    from coding_agent.tui.transcript import AssistantMessage

    summary = CompletedRunSummary(
        verb=verb or choose_completion_verb(),
        duration=duration,
    )
    assistants: list[Any] = []
    cards: list[Any] = []
    for item in items:
        if isinstance(item, AssistantMessage):
            assistants.append(item)
            continue
        if isinstance(item, ToolCallSummary):
            for entry in item.entries:
                if isinstance(entry, ThoughtSnapshot):
                    summary.add_thought(entry.title, entry.content, layout=False)
                else:
                    summary.add_call(entry, layout=False)
        elif _folds_on_completion(item):
            summary.add_call(item.snapshot(), layout=False)
        else:
            cards.append(item)
    folded: list[Any] = list(cards)
    if summary.entries:
        folded.append(summary)
    if assistants:
        folded.append(assistants[-1])
    elif not folded:
        folded.extend(items)
    return folded


def _call_fields(call: Any) -> dict[str, Any]:
    function = call.get("function") or {}
    raw = function.get("arguments") or call.get("arguments") or ""
    try:
        args = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    return {
        "call_id": str(call.get("id") or "history-tool"),
        "run_id": "",
        "tool_name": str(function.get("name") or call.get("name") or "tool"),
        "arguments": args,
        "raw_arguments": raw if isinstance(raw, str) else "",
    }
