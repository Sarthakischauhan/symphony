"""Past-tense run fold: keep the last assistant reply, collapse the rest."""

from __future__ import annotations

from typing import Any


def fold_run_into_summary(
    process: Any,
    *,
    verb: str = "Cooked",
    duration: str = "",
    detail: str = "",
) -> None:
    """Replace remaining live timeline cards with a past-tense fold."""
    from coding_agent.tui.tools.calls import ToolCallWidget
    from coding_agent.tui.tools.snapshots import CompletedRunSummary
    from coding_agent.tui.transcript.live_tools import is_interactive_tool
    from coding_agent.tui.transcript.messages import AssistantMessage
    from coding_agent.tui.transcript.process import ReasoningWidget

    summary = CompletedRunSummary(
        verb=verb,
        duration=duration,
        detail=detail,
    )
    assistants: list[AssistantMessage] = []
    for item in list(process.timeline_items()):
        if item is process._thinking:
            process.remove_item(item)
            continue
        if isinstance(item, AssistantMessage):
            assistants.append(item)
            continue
        if isinstance(item, ReasoningWidget):
            summary.add_thought(item.title, item.reasoning_text, layout=False)
            process.remove_item(item)
            continue
        if isinstance(item, ToolCallWidget):
            if is_interactive_tool(item):
                continue
            summary.add_call(item, layout=False)
            process.remove_item(item)
            continue
        from coding_agent.tui.tools.snapshots import ThoughtSnapshot, ToolCallSummary

        if isinstance(item, ToolCallSummary):
            for entry in item.entries:
                if isinstance(entry, ThoughtSnapshot):
                    summary.add_thought(entry.title, entry.content, layout=False)
                else:
                    summary.add_call(entry, layout=False)
            process.remove_item(item)
    final_assistant = assistants[-1] if assistants else None
    for assistant in assistants[:-1]:
        process.remove_item(assistant)
    if final_assistant is not None and final_assistant in process._items:
        index = process._items.index(final_assistant)
        process._items.insert(index, summary)
        if final_assistant.is_attached:
            process.mount(summary, before=final_assistant)
            return
    process.add_item(summary)
