"""Cap live tool widgets into Explored summary rows."""

from __future__ import annotations

from typing import Any, Callable, MutableMapping, Sequence

LIVE_TOOL_WIDGET_LIMIT = 8


def reconcile_live_tools(
    timeline: Any,
    tools: MutableMapping[str, Any] | None = None,
    *,
    limit: int = LIVE_TOOL_WIDGET_LIMIT,
) -> None:
    """Keep the last ``limit`` tool cards live; fold older ones into Explored lines.

    A stretch is a run of tools not separated by a reasoning/thinking block.
    Each stretch gets at most one Explored summary. ``spawn_agent`` cards stay
    live and do not count toward the cap. In-progress tools are not collapsed.
    """
    if timeline is None or limit < 0:
        return
    from coding_agent.tui.tools.calls import ToolCallWidget

    snapshot, replace, remove = _timeline_ops(timeline)
    live = [
        item
        for item in snapshot()
        if isinstance(item, ToolCallWidget) and item.tool_name != "spawn_agent"
    ]
    overflow = live[:-limit] if limit else live
    for widget in overflow:
        if widget.status in {"preparing", "running"}:
            continue
        _collapse_into_explored(widget, snapshot, replace, remove, tools)


def _timeline_ops(
    timeline: Any,
) -> tuple[Callable[[], list[Any]], Callable[[Any, Any], None], Callable[[Any], None]]:
    if hasattr(timeline, "timeline_items"):
        def snapshot() -> list[Any]:
            return list(timeline.timeline_items())

        return snapshot, timeline.replace_item, timeline.remove_item

    items = list(timeline) if not isinstance(timeline, list) else timeline

    def snapshot() -> list[Any]:
        return items

    def replace(old: Any, new: Any) -> None:
        items[items.index(old)] = new

    def remove(old: Any) -> None:
        items.remove(old)

    return snapshot, replace, remove


def _collapse_into_explored(
    widget: Any,
    snapshot: Callable[[], list[Any]],
    replace: Callable[[Any, Any], None],
    remove: Callable[[Any], None],
    tools: MutableMapping[str, Any] | None,
) -> None:
    from coding_agent.tui.tools.calls import ToolCallSummary

    items = snapshot()
    try:
        index = items.index(widget)
    except ValueError:
        return
    summary = _explored_summary_for_stretch(items, index)
    if summary is None:
        summary = ToolCallSummary()
        replace(widget, summary)
    else:
        remove(widget)
    summary.add_call(widget.call_id)
    if tools is not None:
        tools[widget.call_id] = summary


def _explored_summary_for_stretch(items: Sequence[Any], index: int) -> Any:
    from coding_agent.tui.tools.calls import ToolCallSummary, ToolCallWidget
    from coding_agent.tui.transcript.process import ReasoningWidget

    for item in reversed(items[:index]):
        if isinstance(item, ReasoningWidget):
            return None
        if isinstance(item, ToolCallSummary):
            return item
        if isinstance(item, ToolCallWidget):
            return None
    return None
