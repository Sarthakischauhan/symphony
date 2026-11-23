"""Live view of Symphony agents and the CPU, memory, and disk they use.

The layout matches the subagent task list (``ctrl+g``): a centered option
list whose rows refresh in place. Open it with ``/dashboard``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import OptionList, TextArea
from textual.widgets.option_list import Option

from coding_agent.addons.persistence.active import ActiveSession, list_active
from coding_agent.resources.usage import sample_usage
from coding_agent.tui.screens.modal import ModalBase

if TYPE_CHECKING:
    from core_harness import Harness


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

    def __init__(self, harness: Harness | None = None, jobs=None) -> None:
        super().__init__()
        self.harness = harness
        self.jobs = jobs
        self._samples: dict[int, _Sample] = {}

    def compose(self):  # type: ignore[no-untyped-def]
        yield OptionList(id="agent-dashboard")

    def on_mount(self) -> None:
        self.query_one(OptionList).border_title = "Agents & background tasks · CPU  RAM  disk · Esc back"
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
        task_count = 0
        if self.harness is not None:
            for record in self.harness.child_tasks.values():
                if record.status not in {"running", "background"} or (record.task is not None and record.task.done()):
                    continue
                kind = "job" if record.status == "background" else "subagent"
                label = record.label.removeprefix("bash:") if kind == "job" else record.label
                row = Text(f"{kind:8} running  ", style="#d7a84b")
                row.append(f"{_clip(label, 70)} · {record.child_id[:8]}")
                if kind == "subagent":
                    activity = record.current_tool or "thinking"
                    row.append(f"\n         {activity}", style="#a2adb8")
                elif self.jobs is not None and record.child_id in self.jobs.logs:
                    from coding_agent.tools.bash_jobs import log_tail

                    try:
                        output = log_tail(self.jobs.logs[record.child_id], 1024).strip()
                    except OSError:
                        output = ""
                    row.append(f"\n         {_clip(output, 160) if output else 'No output yet'}", style="#a2adb8")
                options.add_option(Option(row, id=f"task:{record.child_id}"))
                task_count += 1
        if not records and not task_count:
            options.add_option(Option("No agents are running.", disabled=True))
        else:
            options.highlighted = min(highlighted or 0, options.option_count - 1)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id or ""
        if not option_id.startswith("task:") or self.harness is None:
            return
        child_id = option_id.removeprefix("task:")
        record = self.harness.child_tasks.get(child_id)
        if record is None:
            return
        if self.jobs is not None and child_id in self.jobs.logs:
            self.app.push_screen(JobLogScreen(record.label.removeprefix("bash:"), self.jobs.logs[child_id]))
        else:
            child = self.app._subagents.get(child_id)
            if child is not None:
                self.app.open_subagent(child)

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
        content = Text(f"{record.kind:4} ", style=color)
        content.append(f"{_clip(label, 24):<24} ")
        content.append(f"{_clip(record.model_id or 'model unset', 24):<24}", style="#737373")
        content.append(f"  {usage.line()}", style="#a2adb8")
        return content


class JobLogScreen(ModalBase[None]):
    """Scrollable, bounded live output for a background command."""

    CSS = """
    JobLogScreen { align: center middle; background: #000000 60%; }
    #job-log { width: 90%; height: 70%; border: round #484F58; background: #0A0A0A; }
    """

    def __init__(self, command, path) -> None:
        super().__init__()
        self.command = command
        self.path = path

    def compose(self):
        yield TextArea(read_only=True, id="job-log")

    def on_mount(self) -> None:
        self.query_one(TextArea).border_title = f"{_clip(self.command, 80)} · Esc back"
        self.refresh_log()
        self.set_interval(1, self.refresh_log)
        self.query_one(TextArea).focus()

    def refresh_log(self) -> None:
        from coding_agent.tools.bash_jobs import log_tail

        try:
            output = log_tail(self.path, 65536)
        except OSError as exc:
            output = f"Unable to read log: {exc}"
        area = self.query_one(TextArea)
        if area.text != output:
            area.load_text(output)


def _workspace_name(workspace: str) -> str:
    return workspace.rstrip("/").rsplit("/", 1)[-1]


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
