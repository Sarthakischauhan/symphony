"""Live view of Symphony agents and the CPU, memory, and disk they use.

The layout matches the subagent task list (``ctrl+g``): a centered option
list whose rows refresh in place. Open it with ``/dashboard``.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from coding_agent.persistence.active import ActiveSession, list_active
from coding_agent.resources.usage import sample_usage
from coding_agent.tui.screens.modal import ModalBase


_KIND_COLOR = {"tui": "#d7a84b", "run": "#72a57a"}


@dataclass
class _Sample:
    cpu_seconds: float | None = None
    sampled_at: float | None = None


class AgentDashboard(ModalBase[None]):
    """Small list of every live Symphony agent and its resource use."""

    CSS = """
    AgentDashboard { align: center middle; background: #000000 60%; }
    #agent-dashboard { width: 90%; height: 70%; border: round #484F58; background: #0A0A0A; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._samples: dict[int, _Sample] = {}

    def compose(self):  # type: ignore[no-untyped-def]
        yield OptionList(id="agent-dashboard")

    def on_mount(self) -> None:
        self.query_one(OptionList).border_title = "Agents · CPU  RAM  disk · Esc back"
        self.refresh_agents()
        self.set_interval(1, self.refresh_agents)
        self.query_one(OptionList).focus()

    def refresh_agents(self) -> None:
        options = self.query_one(OptionList)
        highlighted = options.highlighted
        options.clear_options()
        records = list_active()
        seen: set[int] = set()
        for record in records:
            seen.add(record.pid)
            options.add_option(Option(self._row(record), id=str(record.pid)))
        self._samples = {pid: sample for pid, sample in self._samples.items() if pid in seen}
        if not records:
            options.add_option(Option("No agents are running.", disabled=True))
        else:
            options.highlighted = min(highlighted or 0, len(records) - 1)

    def _row(self, record: ActiveSession) -> Text:
        previous = self._samples.get(record.pid, _Sample())
        usage, cpu_seconds, sampled_at = sample_usage(
            record.pid,
            workspace=record.workspace or None,
            previous_cpu_seconds=previous.cpu_seconds,
            previous_at=previous.sampled_at,
        )
        self._samples[record.pid] = _Sample(cpu_seconds, sampled_at)
        color = _KIND_COLOR.get(record.kind, "#a2adb8")
        label = record.label.strip() or _workspace_name(record.workspace) or record.session_id[:8]
        content = Text(f"{record.kind:6} ", style=color)
        content.append(_clip(label, 48))
        content.append(f"  {record.model_id or 'model unset'}", style="#737373")
        content.append(f"\n  {usage.line()}", style="#a2adb8")
        content.append(f"   pid {record.pid}   {record.session_id[:8]}", style="#555555")
        return content


def _workspace_name(workspace: str) -> str:
    return workspace.rstrip("/").rsplit("/", 1)[-1]


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
