"""Fold older completed tool cards into one Explored summary per run."""

from __future__ import annotations

from typing import Any, Callable, MutableMapping, Sequence

LIVE_TOOL_WIDGET_LIMIT = 10


def reconcile_live_tools(
    timeline: Any,
    tools: MutableMapping[str, Any] | None = None,
    *,
    limit: int = LIVE_TOOL_WIDGET_LIMIT,
) -> None:
    """Compact completed tool cards in batches of ``limit``.

    The live tool window is deliberately simple: once ``limit`` completed
    widgets have accumulated, the whole batch is folded into one ``Explored``
    row.  Folding starts at the newest widget, so the last card is removed
    first.  A partial batch remains visible until it reaches the limit.

    In-progress tools and ``spawn_agent`` cards stay live and never count.
    """
    if timeline is None or limit < 1:
        return

    snapshot, replace, remove = _timeline_ops(timeline)
    # Copy first: folding mutates the live timeline while we iterate.  Only
    # the current batch is folded; a partial batch remains visible.
    completed = _completed_tools(tuple(snapshot()))
    if len(completed) < limit:
        return
    # Compact the oldest full batch, walking it newest-to-oldest so the
    # summary replaces the batch's final card. Existing summaries stay put.
    batch_summary = None
    for widget in reversed(completed[:limit]):
        batch_summary = _fold_into_explored(
            widget, snapshot, replace, remove, tools, batch_summary
        )


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


def _completed_tools(items: Sequence[Any]) -> list[Any]:
    """Terminal tool cards in timeline order (oldest first)."""
    return [
        item
        for item in items
        if _counts_toward_live_cap(item) and not _is_in_progress_tool(item)
    ]


def _overflow_past_limit(completed: Sequence[Any], limit: int) -> list[Any]:
    """The older cards that fall outside the newest ``limit`` live slots."""
    return list(completed if not limit else completed[:-limit])


def _fold_into_explored(
    widget: Any,
    snapshot: Callable[[], list[Any]],
    replace: Callable[[Any, Any], None],
    remove: Callable[[Any], None],
    tools: MutableMapping[str, Any] | None,
    batch_summary: Any = None,
) -> Any:
    from coding_agent.tui.tools.calls import ToolCallSummary

    items = snapshot()
    if widget not in items:
        return
    summary = batch_summary
    if summary is None:
        # The first fold is the batch's newest card. Once the earlier cards
        # are removed, its summary lands above every card that stays live.
        summary = ToolCallSummary()
        replace(widget, summary)
    else:
        remove(widget)
    summary.add_call(widget)
    if tools is not None:
        tools[widget.call_id] = summary
    return summary


def _explored_summary(items: Sequence[Any]) -> Any:
    """The run's single Explored row, if one has already been created."""
    from coding_agent.tui.tools.calls import ToolCallSummary

    return next((item for item in items if isinstance(item, ToolCallSummary)), None)
