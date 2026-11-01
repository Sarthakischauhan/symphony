"""Installed skills and plugins inspector."""
from __future__ import annotations
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

from coding_agent.addons.plugins import ResolvedPlugin
from coding_agent.addons.skills import CatalogEntry, SkillCatalog, render_args
from coding_agent.extensions import Diagnostic
from coding_agent.tui.screens.modal import EmptyState, ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import EXTENSIONS_MODAL_CSS


_STATE_LABEL = {"full": "ON", "name-only": "NAME ONLY", "manual": "MANUAL", "off": "OFF", "omitted": "OVER BUDGET"}


def _skill_card(entry: CatalogEntry):
    """One skill: name, how the catalog lists it and what that costs, description, args, path."""
    skill = entry.skill
    cost = f" · {entry.tokens} tok" if entry.tokens else ""
    with Vertical(classes="extension-card"):
        with Horizontal(classes="extension-card-header"):
            yield Static(skill.name, classes="extension-name", markup=False)
            yield Static(skill.origin, classes="extension-origin", markup=False)
            yield Static(f"{_STATE_LABEL[entry.state]}{cost}", classes=(
                "extension-status enabled" if entry.state in {"full", "name-only"} else "extension-status disabled"
            ), markup=False)
        yield Static(skill.description, classes="extension-description", markup=False)
        if skill.args:
            yield Static(f"args  {render_args(skill.args)}", classes="extension-path", markup=False)
        yield Static(f"SKILL.md  {skill.path}", classes="extension-path", markup=False)


def _plugin_card(plugin: ResolvedPlugin):
    """One plugin: name, scope, enabled state, description, addon status, skipped parts, and root."""
    with Vertical(classes="extension-card"):
        with Horizontal(classes="extension-card-header"):
            yield Static(f"{plugin.name} {plugin.version}".strip(), classes="extension-name", markup=False)
            yield Static(plugin.scope, classes="extension-origin", markup=False)
            yield Static("ENABLED" if plugin.enabled else "DISABLED", classes=(
                "extension-status enabled" if plugin.enabled else "extension-status disabled"
            ))
        if plugin.description:
            yield Static(plugin.description, classes="extension-description", markup=False)
        if plugin.addon_note:
            yield Static(plugin.addon_note, classes="extension-path", markup=False)
        for label, reason in plugin.skipped:
            yield Static(f"skipped  {label}: {reason}", classes="extension-path", markup=False)
        yield Static(str(plugin.root), classes="extension-path", markup=False)


class ExtensionsModal(ModalBase[None]):
    """Show the skills and plugins available to this workspace, what they cost, and what was skipped."""
    CSS = EXTENSIONS_MODAL_CSS

    def __init__(
        self,
        catalog: SkillCatalog,
        plugins: tuple[ResolvedPlugin, ...],
        diagnostics: tuple[Diagnostic, ...] = (),
        *,
        budget: int = 0,
    ) -> None:
        super().__init__()
        self.catalog, self.plugins, self.diagnostics, self.budget = catalog, plugins, diagnostics, budget

    def compose(self):
        total = len(self.catalog.entries) + len(self.plugins)
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
                if not total and not self.diagnostics:
                    yield EmptyState("No extensions installed", "Add one with: symphony skills add <source>  or  symphony plugins add <source>")
                if self.catalog.entries:
                    budget = f" of {self.budget}" if self.budget else ""
                    yield Static(
                        f"SKILLS  ·  {len(self.catalog.entries)}  ·  catalog {self.catalog.tokens}{budget} tokens",
                        classes="extensions-section",
                        markup=False,
                    )
                    for entry in self.catalog.entries:
                        yield from _skill_card(entry)
                if self.plugins:
                    yield Static(f"PLUGINS  ·  {len(self.plugins)}", classes="extensions-section")
                    for plugin in self.plugins:
                        yield from _plugin_card(plugin)
                if self.diagnostics:
                    yield Static(f"NOTICES  ·  {len(self.diagnostics)}", classes="extensions-section")
                    for item in self.diagnostics:
                        yield Static(f"{item.level}  {item.render()}", classes="extension-path", markup=False)
            yield Static("↑↓ scroll   ·   Esc close", classes="modal-footer")
