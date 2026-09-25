"""Installed skills and plugins inspector."""
from __future__ import annotations
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

from coding_agent.extension_args import render_args
from coding_agent.plugins import LoadedPlugin
from coding_agent.skills import Skill
from coding_agent.tui.screens.modal import EmptyState, ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import EXTENSIONS_MODAL_CSS


def _skill_card(skill: Skill):
    """Render one skill as a compact card: name, origin, description, args, and path."""
    with Vertical(classes="extension-card"):
        with Horizontal(classes="extension-card-header"):
            yield Static(skill.name, classes="extension-name")
            yield Static(skill.origin, classes="extension-origin")
        yield Static(skill.description, classes="extension-description", markup=False)
        if skill.args:
            yield Static(f"args  {render_args(skill.args)}", classes="extension-path", markup=False)
        yield Static(f"SKILL.md  {skill.root / 'SKILL.md'}", classes="extension-path")


def _plugin_card(plugin: LoadedPlugin):
    """Render one plugin manifest as a card: id, enabled state, description, and root."""
    with Vertical(classes="extension-card"):
        with Horizontal(classes="extension-card-header"):
            yield Static(plugin.plugin_id, classes="extension-name")
            yield Static("ENABLED" if plugin.enabled else "DISABLED", classes=(
                "extension-status enabled" if plugin.enabled else "extension-status disabled"
            ))
        if plugin.description:
            yield Static(plugin.description, classes="extension-description", markup=False)
        yield Static(str(plugin.root), classes="extension-path")

class ExtensionsModal(ModalBase[None]):
    """Show the skills and plugins available to this workspace."""
    CSS = EXTENSIONS_MODAL_CSS

    def __init__(self, skills: tuple[Skill, ...], plugins: tuple[LoadedPlugin, ...]) -> None:
        super().__init__()
        self.skills, self.plugins = skills, plugins

    def compose(self):
        total = len(self.skills) + len(self.plugins)
        with Container(id="extensions-pane", classes="modal-pane"):
            with Horizontal(id="extensions-header"):
                yield Static("Installed extensions", id="extensions-title")
                yield Static(f"{total} total", id="extensions-counter")
                yield ModalCloseButton("Esc  close", id="modal-close")
            yield Static(
                "Skills and plugins available from your Symphony configuration",
                id="extensions-subtitle",
            )
            with ModalScroll(id="extensions-body", classes="modal-body"):
                if not total:
                    yield EmptyState("No extensions installed", "Add skills or plugins to ~/.symphony.")
                else:
                    if self.skills:
                        yield Static(f"SKILLS  ·  {len(self.skills)}", classes="extensions-section")
                        for skill in self.skills:
                            yield from _skill_card(skill)
                    if self.plugins:
                        yield Static(f"PLUGINS  ·  {len(self.plugins)}", classes="extensions-section")
                        for plugin in self.plugins:
                            yield from _plugin_card(plugin)
            yield Static("↑↓ scroll   ·   Esc close", classes="modal-footer")
