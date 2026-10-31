"""Per-model session cost, opened by clicking the footer total."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from core_ai.models.pricing import format_cost

from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton


class CostBreakdownScreen(ModalBase[None]):
    """One row per model, most expensive first, plus the session total."""

    CSS = """
    CostBreakdownScreen { align: center middle; background: rgba(0, 0, 0, 0.52); }
    #cost-pane {
        width: 64;
        height: auto;
        max-height: 80%;
        padding: 0 1 1 1;
        background: #0A0A0A;
        border: round #262626;
    }
    #cost-title {
        height: 3;
        padding: 1 1 0 1;
        color: #d9dde0;
        text-style: bold;
        background: #0A0A0A;
    }
    #cost-body { height: auto; padding: 0 1; background: #0A0A0A; color: #ededed; }
    """

    def __init__(self, costs: dict[str, float], total: float | None = None) -> None:
        super().__init__()
        self._costs = dict(costs)
        self._total = sum(self._costs.values()) if total is None else total

    def compose(self) -> ComposeResult:
        with Container(id="cost-pane"):
            yield ModalCloseButton("esc", id="modal-close")
            yield Static("Session cost", id="cost-title")
            yield Static(self._body(), id="cost-body")

    def _body(self) -> str:
        rows = sorted(self._costs.items(), key=lambda item: item[1], reverse=True)
        width = max((len(name.split(":", 1)[-1]) for name, _ in rows), default=5)
        lines = [
            f"{name.split(':', 1)[-1]:<{width}}  {format_cost(amount)}"
            for name, amount in rows
            if amount > 0
        ]
        lines.append("")
        lines.append(f"{'total':<{width}}  {format_cost(self._total)}")
        return "\n".join(lines)


__all__ = ["CostBreakdownScreen"]
