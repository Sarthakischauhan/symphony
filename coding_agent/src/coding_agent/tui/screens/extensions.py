"""Installed skills and plugins inspector."""
from __future__ import annotations
from pathlib import Path
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

from coding_agent.tui.screens.modal import EmptyState, ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import EXTENSIONS_MODAL_CSS


def _skill_card(skill):
    """Render a compact, readable skill card instead of one long text row."""
    with Vertical(classes="extension-card"):
        with Horizontal(classes="extension-card-header"):
            yield Static(skill.name, classes="extension-name")
            yield Static(skill.origin, classes="extension-origin")
        yield Static(skill.description, classes="extension-description")
        yield Static(f"SKILL.md  {skill.root / 'SKILL.md'}", classes="extension-path")


def _plugin_card(plugin):
    with Vertical(classes="extension-card"):
        with Horizontal(classes="extension-card-header"):
            yield Static(plugin.path.name, classes="extension-name")
            yield Static("ENABLED" if plugin.enabled else "DISABLED", classes=(
                "extension-status enabled" if plugin.enabled else "extension-status disabled"
            ))
        yield Static(str(plugin.path), classes="extension-path")

class ExtensionsModal(ModalBase[None]):
    CSS = EXTENSIONS_MODAL_CSS
    """Show the skills and plugins available to this workspace."""
    def __init__(self, workspace: Path, agent=None) -> None:
        super().__init__()
        self.workspace, self.agent = workspace, agent

    def compose(self):
        skills = getattr(getattr(self.agent, "skill_registry", None), "skills", ())
        plugins = getattr(getattr(self.agent, "config", None), "plugins", None)
        plugin_entries = tuple(plugins.entries) if plugins else ()
        total = len(skills) + len(plugin_entries)
        with Container(id="extensions-pane", classes="modal-pane"):
            with Horizontal(id="extensions-header"):
                yield Static("Installed extensions", id="extensions-title")
                yield Static(f"{total} total", id="extensions-counter")
                yield ModalCloseButton("Esc  close", id="modal-close")
            yield Static(
                "Skills and plugins available to this workspace",
                id="extensions-subtitle",
            )
            with ModalScroll(id="extensions-body", classes="modal-body"):
                if not total:
                    yield EmptyState("No extensions installed", "Add skills or plugins to your workspace configuration.")
                else:
                    if skills:
                        yield Static(f"SKILLS  ·  {len(skills)}", classes="extensions-section")
                        for skill in skills:
                            yield from _skill_card(skill)
                    if plugin_entries:
                        yield Static(f"PLUGINS  ·  {len(plugin_entries)}", classes="extensions-section")
                        for plugin in plugin_entries:
                            yield from _plugin_card(plugin)
            yield Static("↑↓ scroll   ·   Esc close", classes="modal-footer")
