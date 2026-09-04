"""Cap live tool widgets into Explored summary rows."""

from __future__ import annotations

from typing import Any, Callable, MutableMapping, Sequence

LIVE_TOOL_WIDGET_LIMIT = 10


def reconcile_live_tools(
    timeline: Any,
    tools: MutableMapping[str, Any] | None = None,
    *,
    limit: int = LIVE_TOOL_WIDGET_LIMIT,
) -> None:
    """Keep the newest ``limit`` completed tool cards live in a timeline.

    Reasoning is presentation, not a retention boundary. Spawned agents and
    in-progress tools stay live, while older terminal tools are represented by
    one lightweight summary row.
    """
    if timeline is None or limit < 0:
        return

    snapshot, replace, remove = _timeline_ops(timeline)
    completed = [
        item
        for item in tuple(snapshot())
        if _counts_toward_live_cap(item) and not _is_in_progress_tool(item)
    ]
    for widget in _overflow_past_limit(completed, limit):
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


def _counts_toward_live_cap(item: Any) -> bool:
    from coding_agent.tui.tools.calls import ToolCallWidget

    return isinstance(item, ToolCallWidget) and item.tool_name != "spawn_agent"


def _is_in_progress_tool(widget: Any) -> bool:
    return widget.status in {"preparing", "running"}


def _overflow_past_limit(live: Sequence[Any], limit: int) -> list[Any]:
    return list(live if not limit else live[:-limit])


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
    summary = next((item for item in items if isinstance(item, ToolCallSummary)), None)
    if summary is None:
        summary = ToolCallSummary()
        replace(widget, summary)
    else:
        remove(widget)
    summary.add_call(widget)
    if tools is not None:
        tools[widget.call_id] = summary
