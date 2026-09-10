"""Active vs collected tool cards: keep the hot cell, fold the rest into Explored."""

from __future__ import annotations

from typing import Any, Callable, MutableMapping, Sequence

LIVE_TOOL_WIDGET_LIMIT = 10


def is_hot_tool(widget: Any) -> bool:
    """True while a tool card is still the in-progress cell."""
    from coding_agent.tui.tools.calls import ToolCallWidget

    return isinstance(widget, ToolCallWidget) and widget.status in {"preparing", "running"}


def is_interactive_tool(widget: Any) -> bool:
    """Cards that stay mounted after completion (image preview, child transcript)."""
    return bool(getattr(widget, "keep_in_transcript", False)) or getattr(
        widget, "tool_name", ""
    ) in {"generate_image", "spawn_agent"}


def is_collectable_tool(widget: Any, *, include_interactive: bool = False) -> bool:
    """Terminal tool cards that should leave the hot live set."""
    from coding_agent.tui.tools.calls import ToolCallWidget

    if not isinstance(widget, ToolCallWidget) or is_hot_tool(widget):
        return False
    if is_interactive_tool(widget) and not include_interactive:
        return False
    return True


def is_collectable_thought(widget: Any) -> bool:
    """Completed reasoning that can fold into Explored."""
    from coding_agent.tui.transcript.process import ReasoningWidget

    return isinstance(widget, ReasoningWidget) and widget.has_class("is-complete")


def release_live_binding(
    tools: MutableMapping[str, Any] | None,
    widget: Any,
    collected: Any,
) -> None:
    """Point the live map at the collected form so the hot widget is gone."""
    call_id = getattr(widget, "call_id", None)
    if tools is None or not call_id:
        return
    tools[call_id] = collected


def collectable_tools(
    items: Sequence[Any],
    *,
    include_interactive: bool = False,
) -> list[Any]:
    """Terminal tool cards in timeline order (oldest first)."""
    return [
        item
        for item in items
        if is_collectable_tool(item, include_interactive=include_interactive)
    ]


def reconcile_live_tools(
    timeline: Any,
    tools: MutableMapping[str, Any] | None = None,
    *,
    limit: int = LIVE_TOOL_WIDGET_LIMIT,
    final: bool = False,
) -> None:
    """Collect completed tool cards into Explored as they leave the hot set.

    In-progress tools stay live. Interactive cards (subagents, generated
    images) stay mounted until finalization. Every other completed tool is
    folded immediately: it appends to the open Explored batch when that
    batch is under ``limit``, otherwise it starts a new one. Finalization
    also folds remaining interactive cards, completed thoughts, and closes
    expanded batches.
    """
    if timeline is None or limit < 1:
        return

    snapshot, replace, remove = _timeline_ops(timeline)
    if final:
        _collapse_expanded_summaries(snapshot())

    previous: tuple[int, ...] | None = None
    while True:
        items = snapshot()
        completed = collectable_tools(items, include_interactive=final)
        thoughts = [item for item in items if is_collectable_thought(item)]
        progress = tuple(id(item) for item in completed + thoughts)
        if progress == previous:
            return
        previous = progress
        if not completed and not (final and thoughts):
            return

        open_batch = (
            None
            if final
            else _open_collect_batch(
                items, completed[0] if completed else None, limit=limit
            )
        )
        if open_batch is not None and completed:
            room = max(0, limit - open_batch.count)
            selected = completed[:room]
            if selected:
                _fold_batch(
                    _batch_with_thoughts(items, selected),
                    snapshot,
                    replace,
                    remove,
                    tools,
                    batch_summary=open_batch,
                )
                continue

        selected = completed if final else completed[:limit]
        batch = _batch_with_thoughts(items, selected) if selected else thoughts
        if not batch:
            return
        _fold_batch(batch, snapshot, replace, remove, tools)
        if final:
            return


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


def _collapse_expanded_summaries(items: Sequence[Any]) -> None:
    from coding_agent.tui.tools.calls import ToolCallSummary

    for item in items:
        if isinstance(item, ToolCallSummary) and item.is_expanded:
            item.toggle()


def _open_collect_batch(
    items: Sequence[Any],
    widget: Any,
    *,
    limit: int,
) -> Any | None:
    from coding_agent.tui.tools.calls import ToolCallSummary

    if widget in items:
        index = items.index(widget)
        neighbors = []
        if index:
            neighbors.append(items[index - 1])
        if index + 1 < len(items):
            neighbors.append(items[index + 1])
        for neighbor in neighbors:
            if isinstance(neighbor, ToolCallSummary) and neighbor.count < limit:
                return neighbor
    last = None
    for item in items:
        if isinstance(item, ToolCallSummary):
            last = item
    if last is not None and last.count < limit:
        return last
    return None


def _batch_with_thoughts(items: Sequence[Any], selected: Sequence[Any]) -> list[Any]:
    if not selected:
        return [item for item in items if is_collectable_thought(item)]
    boundary = items.index(selected[-1]) + 1
    chosen = {id(item) for item in selected}
    return [
        item
        for item in items[:boundary]
        if id(item) in chosen or is_collectable_thought(item)
    ]


def _fold_batch(
    batch: Sequence[Any],
    snapshot: Callable[[], list[Any]],
    replace: Callable[[Any, Any], None],
    remove: Callable[[Any], None],
    tools: MutableMapping[str, Any] | None,
    batch_summary: Any = None,
) -> None:
    summary = batch_summary
    for widget in batch:
        summary = _fold_into_explored(
            widget, snapshot, replace, remove, tools, summary
        )
    if summary is not None:
        _refresh_summary(summary)


def _refresh_summary(summary: Any) -> None:
    summary.title = summary._summary_title()
    from textual._context import NoActiveAppError

    try:
        summary.refresh(layout=True)
    except NoActiveAppError:
        pass
    from coding_agent.tui.motion import settle_row

    settle_row(summary)


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
        return batch_summary
    summary = batch_summary
    if summary is None:
        # The first fold is the batch's oldest card, so Explored sits where
        # that stretch of completed work began.
        summary = ToolCallSummary()
        replace(widget, summary)
    else:
        remove(widget)
    from coding_agent.tui.transcript.process import ReasoningWidget

    if isinstance(widget, ReasoningWidget):
        summary.add_thought(str(widget.title), layout=False)
    else:
        summary.add_call(widget, layout=False)
        release_live_binding(tools, widget, summary)
    return summary
