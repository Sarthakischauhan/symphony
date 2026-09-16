"""Live tool stretches: show cards until a non-tool widget interrupts them."""

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


def is_timeline_chrome(widget: Any) -> bool:
    """Status chrome that neither joins nor splits a tool stretch."""
    from coding_agent.tui.transcript.process import ThinkingStatus

    return isinstance(widget, ThinkingStatus)


def is_tool_stretch_item(widget: Any) -> bool:
    """Live tool cards and tool-bearing Explored folds in one consecutive stretch."""
    from coding_agent.tui.tools.calls import ToolCallSummary, ToolCallWidget

    if isinstance(widget, ToolCallWidget):
        return True
    return isinstance(widget, ToolCallSummary) and widget.count > 0


def is_thought_stretch_item(widget: Any) -> bool:
    """Reasoning widgets that form their own stretch, splitting tool groups."""
    from coding_agent.tui.transcript.process import ReasoningWidget

    return isinstance(widget, ReasoningWidget)


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


def segment_tool_stretches(items: Sequence[Any]) -> list[tuple[list[Any], bool]]:
    """Split a timeline into consecutive tool stretches.

    Each result is ``(stretch_items, interrupted)``. A stretch is a run of
    tool cards and tool-bearing Explored folds. Assistant text, thinking,
    notices, or any other non-tool widget closes the stretch so later tools
    start a new one. ThinkingStatus is chrome and is skipped without closing
    a stretch. ``interrupted`` is True when a non-tool widget follows.
    """
    return _segment_stretches(items, is_tool_stretch_item)


def segment_thought_stretches(items: Sequence[Any]) -> list[tuple[list[Any], bool]]:
    """Split a timeline into consecutive reasoning stretches."""
    return _segment_stretches(items, is_thought_stretch_item)


def reconcile_live_tools(
    timeline: Any,
    tools: MutableMapping[str, Any] | None = None,
    *,
    limit: int | None = None,
    final: bool = False,
) -> None:
    """Keep live tool cards until a non-tool widget interrupts the stretch.

    Completed tools stay visible while their stretch is active. When text,
    thinking, or another non-tool widget arrives, that consecutive stretch
    folds into one Explored row. Tools after the interruption start a new
    stretch. ``limit < 1`` disables compaction; stretch size is not capped.
    Finalization folds remaining stretches, interactive cards, and completed
    thoughts, and closes expanded batches.
    """
    if timeline is None or (limit is not None and limit < 1):
        return

    snapshot, replace, remove = _timeline_ops(timeline)
    if final:
        _collapse_expanded_summaries(snapshot())

    previous: tuple[int, ...] | None = None
    while True:
        items = snapshot()
        folded = _fold_ready_stretch(
            snapshot,
            replace,
            remove,
            tools,
            members=segment_tool_stretches(items),
            collectable=lambda item: is_collectable_tool(
                item, include_interactive=final
            ),
            final=final,
        )
        if not folded and final:
            items = snapshot()
            folded = _fold_ready_stretch(
                snapshot,
                replace,
                remove,
                tools,
                members=segment_thought_stretches(items),
                collectable=is_collectable_thought,
                final=True,
            )
        if not folded:
            return
        progress = tuple(id(item) for item in snapshot())
        if progress == previous:
            return
        previous = progress


def _segment_stretches(
    items: Sequence[Any],
    is_member: Callable[[Any], bool],
) -> list[tuple[list[Any], bool]]:
    stretches: list[tuple[list[Any], bool]] = []
    current: list[Any] = []
    for item in items:
        if is_timeline_chrome(item):
            continue
        if is_member(item):
            current.append(item)
            continue
        if current:
            stretches.append((current, True))
            current = []
    if current:
        stretches.append((current, False))
    return stretches


def _fold_ready_stretch(
    snapshot: Callable[[], list[Any]],
    replace: Callable[[Any, Any], None],
    remove: Callable[[Any], None],
    tools: MutableMapping[str, Any] | None,
    *,
    members: Sequence[tuple[list[Any], bool]],
    collectable: Callable[[Any], bool],
    final: bool,
) -> bool:
    from coding_agent.tui.tools.calls import ToolCallSummary

    for stretch, interrupted in members:
        if not (interrupted or final):
            continue
        selected = [item for item in stretch if collectable(item)]
        if not selected:
            continue
        existing = next(
            (item for item in stretch if isinstance(item, ToolCallSummary)),
            None,
        )
        _fold_batch(
            selected,
            snapshot,
            replace,
            remove,
            tools,
            batch_summary=existing,
        )
        return True
    return False


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
        # The first fold is the stretch's oldest card, so Explored sits where
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
