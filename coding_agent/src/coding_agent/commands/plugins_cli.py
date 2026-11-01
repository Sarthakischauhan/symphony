"""``symphony plugins`` and ``/plugins``: add, list, remove, enable, disable, update, marketplace.

Nothing here runs plugin code. ``add`` copies files. An enabled plugin's addon
loads the next time the agent starts; ``disable`` stops that.
"""

from __future__ import annotations

import argparse
from typing import Sequence

from coding_agent.addons.plugins import (
    ResolvedPlugin,
    UpdateResult,
    add_marketplace,
    install_plugin,
    list_marketplaces,
    remove_marketplace,
    remove_plugin,
    resolve_plugins,
    set_enabled,
    update_marketplaces,
    update_plugins,
)
from coding_agent.commands.cli_support import Context, Outcome, Parser, main as run_main, run_command, table
from coding_agent.commands.installed import diagnostics_report, plugin_details, plugins_report


def build_parser(prog: str = "symphony plugins") -> Parser:
    parser = Parser(prog=prog, description="Install and manage plugins: packages of skills and addon code.")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    add = commands.add_parser("add", help="install from a local path, git URL[@ref], owner/repo or plugin@marketplace")
    add.add_argument("source")
    add.add_argument("--path", default="", metavar="DIR", help="use this subdirectory of the source")
    commands.add_parser("list", help="list plugins and what was skipped")
    for name, help_text in (("remove", "uninstall a plugin"), ("enable", "load a plugin's skills and addon"), ("disable", "stop loading a plugin")):
        commands.add_parser(name, help=help_text).add_argument("name")
    commands.add_parser("update", help="fetch installed plugins again").add_argument("name", nargs="?")
    marketplace = commands.add_parser("marketplace", help="manage marketplaces (catalogs of plugins)")
    actions = marketplace.add_subparsers(dest="action", metavar="ACTION", required=True)
    actions.add_parser("add", help="add a marketplace from a path, git URL[@ref] or owner/repo").add_argument("source")
    actions.add_parser("list", help="list marketplaces and their plugins")
    actions.add_parser("update", help="fetch marketplaces again").add_argument("name", nargs="?")
    actions.add_parser("remove", help="forget a marketplace (its installed plugins stay)").add_argument("name")
    return parser


def _summary(plugin: ResolvedPlugin) -> list[str]:
    head = f"{plugin.name} {plugin.version}".strip()
    return [f"{head}: {plugin.skill_count} skills", *plugin_details(plugin)]


def _installed(arguments: argparse.Namespace, context: Context) -> Outcome:
    record = install_plugin(arguments.source, cwd=context.cwd, subdir=arguments.path)
    found = [item for item in resolve_plugins(context.workspace).plugins if item.key == record.key]
    if not found:
        return Outcome(f"Installed {record.key}, but another plugin named {record.name} takes precedence (see: plugins list)", changed=True)
    return Outcome("Installed " + "\n".join(_summary(found[0])), changed=True)


def _marketplace(arguments: argparse.Namespace, context: Context) -> Outcome:
    match arguments.action:
        case "add":
            record, manifest = add_marketplace(arguments.source, cwd=context.cwd)
            names = ", ".join(item.name for item in manifest.plugins) or "no plugins"
            return Outcome(f"Added marketplace {record.name} ({len(manifest.plugins)} plugins: {names})")
        case "list":
            rows = [
                (record.name, record.source.describe(), ", ".join(item.name for item in manifest.plugins) if manifest else "(unreadable: update it)")
                for record, manifest in list_marketplaces()
            ]
            return Outcome(table(("NAME", "SOURCE", "PLUGINS"), rows) if rows else "No marketplaces. Add one: symphony plugins marketplace add <source>")
        case "update":
            lines = [f"{name}: {outcome}" for name, outcome in update_marketplaces(arguments.name)]
            return Outcome("\n".join(lines) or "No marketplaces.")
        case "remove":
            kept = remove_marketplace(arguments.name)
            return Outcome(f"Removed marketplace {arguments.name} ({kept} installed plugins kept)")
    raise ValueError(f"unknown action {arguments.action!r}")


def _update_line(item: UpdateResult) -> str:
    if item.error:
        return f"{item.key}: {item.error}"
    if item.before == item.after:
        return f"{item.key}: {item.after} (unchanged)"
    return f"{item.key}: {item.after} (was {item.before or 'unversioned'})"


def execute(arguments: argparse.Namespace, context: Context) -> Outcome:
    workspace = context.workspace
    match arguments.command:
        case "add":
            return _installed(arguments, context)
        case "list":
            plugins = resolve_plugins(workspace)
            return Outcome("\n\n".join(part for part in (plugins_report(plugins), diagnostics_report(plugins.diagnostics)) if part))
        case "remove":
            return Outcome(f"Removed {remove_plugin(arguments.name, workspace).key}", changed=True)
        case "enable" | "disable":
            enabled = arguments.command == "enable"
            plugin = set_enabled(arguments.name, enabled, workspace)
            return Outcome(f"{'Enabled' if enabled else 'Disabled'} {plugin.name}", changed=True)
        case "update":
            lines = [_update_line(item) for item in update_plugins(arguments.name)]
            lines = lines or ["No plugins were installed with 'plugins add'."]
            return Outcome("\n".join(lines), changed=True)
        case "marketplace":
            return _marketplace(arguments, context)
    raise ValueError(f"unknown command {arguments.command!r}")


def run(argv: Sequence[str], context: Context) -> Outcome:
    return run_command(argv, context, build_parser, execute)


def main(argv: Sequence[str]) -> int:
    return run_main(argv, build_parser, execute)


__all__ = ["build_parser", "execute", "main", "run"]
