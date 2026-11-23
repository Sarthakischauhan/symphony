"""The start screen shown in an empty transcript.

A card in the top-left: the logo and what this workspace loaded on the left,
recent conversations on the right. A recent row is a click target; the app
resumes that conversation in place. A tip under the card rotates and prefers
advice about this workspace. The card measures itself against the space it
has and drops detail (recent rows, padding, the box) until it fits.
"""

from __future__ import annotations

import asyncio
import tomllib
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Sequence

from rich import box
from rich.cells import cell_len
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.message import Message
from textual.widgets import Static

from coding_agent.addons.persistence.jsonl import JsonlPersistence
from coding_agent.tui.theme import SYMPHONY_COLORS

LOGO = (
    " ███████╗██╗   ██╗███╗   ███╗██████╗ ██╗  ██╗ ██████╗ ███╗   ██╗██╗   ██╗",
    " ██╔════╝╚██╗ ██╔╝████╗ ████║██╔══██╗██║  ██║██╔═══██╗████╗  ██║╚██╗ ██╔╝",
    " ███████╗ ╚████╔╝ ██╔████╔██║██████╔╝███████║██║   ██║██╔██╗ ██║ ╚████╔╝ ",
    " ╚════██║  ╚██╔╝  ██║╚██╔╝██║██╔═══╝ ██╔══██║██║   ██║██║╚██╗██║  ╚██╔╝  ",
    " ███████║   ██║   ██║ ╚═╝ ██║██║     ██║  ██║╚██████╔╝██║ ╚████║   ██║   ",
    " ╚══════╝   ╚═╝   ╚═╝     ╚═╝╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ",
)
RAINBOW = ("#ff5f5f", "#ffaf5f", "#ffff5f", "#5fff5f", "#5fffff", "#5fafff", "#af5fff")

RECENT_LIMIT = 5
# The recent column needs this many cells before it sits beside the logo.
RECENT_MIN_WIDTH = 36
TIP_SECONDS = 12.0

# (key, rest). Every key names something that exists in the TUI or CLI today.
TIPS: tuple[tuple[str, str], ...] = (
    ("/context", "shows exactly what the model sees"),
    ("@", "suggests workspace paths as you type"),
    ("/diff", "opens the workspace diff"),
    ("ctrl+g", "lists running subagents"),
    ("ctrl+b", "shows live agents and their CPU, memory and disk"),
    ("/compact", "frees context and keeps recent messages"),
    ("shift+enter", "adds a new line without sending"),
    ("ctrl+a", "starts voice mode"),
    ("/theme", "previews color themes live"),
    ("/installed", "lists the skills and plugins in use"),
    ("symphony doctor", "finds and fixes setup problems"),
)


@dataclass(frozen=True)
class RecentSession:
    session_id: str
    title: str
    age: str


@dataclass(frozen=True)
class WelcomeSummary:
    """What the running agent loaded, recorded by the app once the agent is built."""

    skills: int
    plugins: int
    personality: str
    persistence: JsonlPersistence | None = None


@dataclass(frozen=True)
class WelcomeFacts:
    """What the card shows. ``None`` means not known yet (the agent is still starting)."""

    version: str = ""
    agents_md: bool | None = None
    skills: int | None = None
    plugins: int | None = None
    personality: str = ""
    recent: tuple[RecentSession, ...] = field(default_factory=tuple)


class Welcome(Static):
    """Start screen. Removed by the transcript as soon as anything else mounts."""

    # The card picks what to show from the height it is given, so it must not size itself
    # from its own content. theme.toml sets the same; this holds for themes that omit it.
    DEFAULT_CSS = """
    Welcome {
        height: 1fr;
    }
    """

    class ResumeRequested(Message):
        """A recent conversation was clicked."""

        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.art = load_art(workspace)
        self.facts = WelcomeFacts(version=_installed_version(), agents_md=(workspace / "AGENTS.md").is_file())
        self._tip_index = date.today().toordinal()
        super().__init__("", classes="welcome")

    def on_mount(self) -> None:
        self.refresh_facts()
        self.set_interval(TIP_SECONDS, self._next_tip)

    def on_resize(self) -> None:
        self.refresh()

    # ---- data ------------------------------------------------------------

    def refresh_facts(self) -> None:
        """Show what the agent loaded and reload recent sessions. Nothing until the agent is built."""
        from coding_agent.tui.app import CodingAgentApp

        app = self.app
        if not isinstance(app, CodingAgentApp) or app.welcome_summary is None:
            return
        summary = app.welcome_summary
        self.set_facts(
            replace(self.facts, skills=summary.skills, plugins=summary.plugins, personality=summary.personality)
        )
        if summary.persistence is not None:
            persistence, current = summary.persistence, app.session_id or ""
            self.run_worker(
                lambda: self._load_recent(persistence, current),
                thread=True, exclusive=True, group="welcome-recent",
            )

    def _load_recent(self, persistence: JsonlPersistence, current: str) -> None:
        from coding_agent.tui.screens.resume import _relative_time, load_session_options

        try:
            options = asyncio.run(load_session_options(persistence))
        except Exception:  # noqa: BLE001 - the start screen must never fail to draw
            return
        recent = tuple(
            RecentSession(option.session_id, option.first_message, _relative_time(option.updated_at))
            for option in options
            if option.session_id != current
        )[:RECENT_LIMIT]
        self.app.call_from_thread(self.set_recent, recent)

    def set_facts(self, facts: WelcomeFacts) -> None:
        self.facts = facts
        self.refresh()

    def set_recent(self, recent: Sequence[RecentSession]) -> None:
        self.set_facts(replace(self.facts, recent=tuple(recent)))

    def action_resume(self, index: int) -> None:
        if 0 <= index < len(self.facts.recent):
            self.post_message(self.ResumeRequested(self.facts.recent[index].session_id))

    # ---- tips ------------------------------------------------------------

    def tips(self) -> list[tuple[str, str]]:
        """Advice about this workspace first, then the general rotation."""
        found: list[tuple[str, str]] = []
        if self.facts.agents_md is False:
            found.append(("AGENTS.md", "in the project root gives Symphony standing instructions"))
        if self.facts.recent:
            found.append(("click", "a recent conversation to pick it up where you left off"))
        return found + list(TIPS)

    def current_tip(self) -> tuple[str, str]:
        tips = self.tips()
        return tips[self._tip_index % len(tips)]

    def _next_tip(self) -> None:
        self._tip_index += 1
        self.refresh()

    # ---- rendering -------------------------------------------------------

    def render(self) -> RenderableType:
        width = max(24, self.size.width)
        height = self.size.height or 30
        console = self.app.console
        options = console.options.update_width(width)
        rows = len(self.facts.recent)
        variants = [(rows, 1), (min(rows, 3), 1), (min(rows, 3), 0), (0, 0)]
        for recent_rows, pad in variants:
            card = self._card(width, recent_rows, pad)
            used = 1 + len(console.render_lines(card, options, pad=False))
            if used <= height:
                break
        else:
            return Group(*self._logo(), *self._context_lines(width))
        blocks: list[RenderableType] = [Text(""), card]
        if used + 2 <= height:
            blocks += [Text(""), self._tip_line()]
        return Group(*blocks)

    def _card(self, width: int, recent_rows: int, pad: int) -> Panel:
        c = SYMPHONY_COLORS
        art_width = max((cell_len(line) for line in self.art), default=0)
        inner = width - 6  # border and horizontal padding
        side_by_side = recent_rows > 0 and inner - art_width - 3 >= RECENT_MIN_WIDTH

        identity: list[RenderableType] = list(self._logo())
        tagline = Text("coding agent", style=c["subtext"])
        if self.facts.version:
            tagline.append(f" · v{self.facts.version}", style=c["muted"])
        identity += [tagline, Text("")]

        recent = self._recent(recent_rows) if recent_rows else []

        if side_by_side:
            identity += self._context_lines(art_width)
            body: RenderableType = Table(
                box=box.MINIMAL, show_header=False, show_edge=False, padding=(0, 1),
                border_style=c["edge"], expand=True,
            )
            body.add_column(width=art_width, no_wrap=True)
            body.add_column(ratio=1)
            body.add_row(Group(*identity), Group(*recent))
        else:
            identity += self._context_lines(inner)
            body = Group(*identity, *([Text(""), *recent] if recent else []))
        return Panel(body, box=box.ROUNDED, border_style=c["accent"], padding=(pad, 2), width=width)

    def _logo(self) -> list[Text]:
        return gradient(self.art)

    def _recent(self, count: int) -> list[RenderableType]:
        c = SYMPHONY_COLORS
        header = Text()
        header.append("Recent", style=f"bold {c['accent']}")
        header.append("  click to open", style=c["muted"])
        lines: list[RenderableType] = [header]
        for index, session in enumerate(self.facts.recent[:count]):
            row = Table.grid(expand=True, padding=(0, 1))
            row.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
            row.add_column(justify="right", no_wrap=True)
            title = Text(
                " ".join(session.title.split()) or "Untitled conversation",
                style=Style(color=c["foreground"], meta={"@click": f"resume({index})"}),
                no_wrap=True,
                overflow="ellipsis",
            )
            row.add_row(title, Text(session.age.removesuffix(" ago"), style=c["muted"]))
            lines.append(row)
        return lines

    def _context_lines(self, width: int) -> list[Text]:
        """Loaded-context chips, wrapped to ``width``. A filled dot is present, a hollow one missing."""
        c = SYMPHONY_COLORS
        f = self.facts
        chips: list[tuple[str, bool | None]] = [
            ("AGENTS.md" if f.agents_md is not False else "no AGENTS.md", f.agents_md),
            (_count(f.skills, "skill"), None if f.skills is None else f.skills > 0),
            (_count(f.plugins, "plugin"), None if f.plugins is None else f.plugins > 0),
        ]
        if f.personality:
            chips.append((f"{f.personality} personality", True))
        lines = [Text()]
        for label, present in chips:
            if present:
                dot, dot_style, label_style = "●", c["string"], c["foreground"]
            elif present is False:
                dot, dot_style, label_style = "○", c["muted"], c["muted"]
            else:
                dot, dot_style, label_style = "◌", c["muted"], c["muted"]
            chip = Text()
            chip.append(f"{dot} ", style=dot_style)
            chip.append(label, style=label_style)
            line = lines[-1]
            gap = 3 if line.cell_len else 0
            if line.cell_len and line.cell_len + gap + chip.cell_len > width:
                lines.append(Text())
                line, gap = lines[-1], 0
            line.append(" " * gap)
            line.append_text(chip)
        return lines

    def _tip_line(self) -> Text:
        c = SYMPHONY_COLORS
        key, rest = self.current_tip()
        tip = Text(no_wrap=True, overflow="ellipsis")
        tip.append("   tip  ", style=f"bold {c['muted']}")
        tip.append(key, style=c["subtext"])
        tip.append(f" {rest}", style=c["muted"])
        return tip


def gradient(lines: Sequence[str]) -> list[Text]:
    """Color non-space cells left to right across the rainbow."""
    width = max((len(line) for line in lines), default=1)
    out = []
    for line in lines:
        text = Text(no_wrap=True, overflow="crop")
        for index, character in enumerate(line):
            if character == " ":
                text.append(character)
                continue
            text.append(character, style=RAINBOW[round(index * (len(RAINBOW) - 1) / max(width - 1, 1))])
        out.append(text)
    return out


def load_art(workspace: Path) -> list[str]:
    """``art`` from ``.symphony/dashboard.toml`` or ``dashboard.toml``, else the Symphony logo."""
    for config in (workspace / ".symphony" / "dashboard.toml", workspace / "dashboard.toml"):
        try:
            with config.open("rb") as stream:
                art = tomllib.load(stream).get("art")
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if art is None:
            break
        # An explicit but malformed art setting shows no logo, as before.
        return art if isinstance(art, list) and all(isinstance(line, str) for line in art) else []
    return list(LOGO)


def _count(value: int | None, noun: str) -> str:
    if value is None:
        return f"{noun}s…"
    return f"{value} {noun}{'' if value == 1 else 's'}"


def _installed_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("symphony-code")
    except PackageNotFoundError:
        return ""


__all__ = ["LOGO", "RecentSession", "TIPS", "Welcome", "WelcomeFacts", "WelcomeSummary", "load_art"]
