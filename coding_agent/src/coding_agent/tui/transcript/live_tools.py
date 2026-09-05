"""Fold completed tools and thought titles into Explored batches."""

from __future__ import annotations

from typing import Any, Callable, MutableMapping, Sequence

LIVE_TOOL_WIDGET_LIMIT = 10


def reconcile_live_tools(
    timeline: Any,
    tools: MutableMapping[str, Any] | None = None,
    *,
    limit: int = LIVE_TOOL_WIDGET_LIMIT,
    final: bool = False,
) -> None:
    """Compact completed tool cards in batches of ``limit``.

    The live tool window is deliberately simple: once ``limit`` completed
    widgets have accumulated, the whole batch is folded into one ``Explored``
    row together with completed thoughts preceding the batch's last tool.
    A partial batch remains visible until it reaches the limit.

    Finalization also folds partial batches and completed subagent cards.
    In-progress tools always stay live.
    """
    if timeline is None or limit < 1:
        return

    snapshot, replace, remove = _timeline_ops(timeline)
    if final:
        from coding_agent.tui.tools.calls import ToolCallSummary

        for item in snapshot():
            if isinstance(item, ToolCallSummary) and item.is_expanded:
                item.toggle()
    # Copy first: folding mutates the live timeline while we iterate.  Only
    # the current batch is folded; a partial batch remains visible.
    items = snapshot()
    completed = _completed_tools(items, include_subagents=final)
    if not final and len(completed) < limit:
        return
    from coding_agent.tui.transcript.process import ReasoningWidget

    selected = completed if final else completed[:limit]
    boundary = len(items) if final else items.index(selected[-1]) + 1
    batch = [
        item for item in items[:boundary]
        if item in selected
        or isinstance(item, ReasoningWidget) and item.has_class("is-complete")
    ]
    # Compact the oldest full batch, walking it newest-to-oldest so the
    # summary replaces the batch's final card. Existing summaries stay put.
    batch_summary = None
    for widget in reversed(batch):
        batch_summary = _fold_into_explored(
            widget, snapshot, replace, remove, tools, batch_summary
        )
    if batch_summary is not None:
        # Removal happens bottom-up; disclosures read in original event order.
        batch_summary.entries.reverse()


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


def _completed_tools(items: Sequence[Any], *, include_subagents: bool = False) -> list[Any]:
    """Terminal tool cards in timeline order (oldest first)."""
    from coding_agent.tui.tools.calls import ToolCallWidget

    return [
        item
        for item in items
        if isinstance(item, ToolCallWidget)
        and not getattr(item, "keep_in_transcript", False)
        and (include_subagents or _counts_toward_live_cap(item))
        and not _is_in_progress_tool(item)
    ]


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
    from coding_agent.tui.transcript.process import ReasoningWidget

    if isinstance(widget, ReasoningWidget):
        summary.add_thought(str(widget.title))
    else:
        summary.add_call(widget)
        if tools is not None:
            tools[widget.call_id] = summary
    return summary
