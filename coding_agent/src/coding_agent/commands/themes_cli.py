"""``symphony themes``: list the themes plugins provide and choose one.

Choosing saves ``theme`` in config.json; the TUI applies it the next time it starts,
or at once through ``/theme``. Nothing here loads the TUI or runs plugin code.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from coding_agent.addons.plugins import PluginTheme, find_theme, resolve_plugins
from coding_agent.commands.cli_support import Context, Outcome, Parser, main as run_main, run_command, table
from coding_agent.commands.installed import saved_config
from coding_agent.config import DEFAULT_THEME, CodingAgentConfig, ensure_spawn_settings, user_theme_path


def build_parser(prog: str = "symphony themes") -> Parser:
    parser = Parser(prog=prog, description="Themes from plugins (themes/ directories). Install some with: symphony plugins add <plugin>@<marketplace>")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    commands.add_parser("list", help="list the available themes and the one in use")
    commands.add_parser("use", help="use a theme (plugin:Name, a bare Name, or 'default')").add_argument("name")
    return parser


def available_themes(workspace: Path, config: CodingAgentConfig) -> tuple[PluginTheme, ...]:
    """Themes of the enabled plugins this workspace sees; none when plugins are switched off."""
    return resolve_plugins(workspace).themes if config.plugins.enabled else ()


def choose_theme(workspace: Path, query: str) -> CodingAgentConfig:
    """Save the theme ``query`` names as the user's choice. ``ValueError`` when no available theme matches."""
    config = saved_config(workspace)
    if query.strip().casefold() == DEFAULT_THEME:
        name = DEFAULT_THEME
    else:
        name = find_theme(available_themes(workspace, config), query).qualified_name
    return ensure_spawn_settings(workspace, overrides={"theme": name})


def _listing(workspace: Path) -> str:
    config = saved_config(workspace)
    rows = [(("*" if config.theme == DEFAULT_THEME else " "), DEFAULT_THEME, "dark", "symphony", "built in")]
    rows += [
        ("*" if config.theme.casefold() == theme.qualified_name.casefold() else " ", theme.qualified_name, theme.base, theme.format, theme.path.name)
        for theme in available_themes(workspace, config)
    ]
    lines = [table(("", "THEME", "BASE", "FORMAT", "FILE"), rows)]
    if user_theme_path().is_file():
        lines.append(f"\n{user_theme_path()} overrides the chosen theme; remove it to use the theme above.")
    if len(rows) == 1:
        lines.append("\nNo plugin themes yet. Try: symphony plugins marketplace add matcra587/claude-themes && symphony plugins add dracula@claude-themes")
    return "\n".join(lines)


def execute(arguments: argparse.Namespace, context: Context) -> Outcome:
    match arguments.command:
        case "list":
            return Outcome(_listing(context.workspace))
        case "use":
            config = choose_theme(context.workspace, arguments.name)
            return Outcome(f"Theme set to {config.theme}", changed=True)
    raise ValueError(f"unknown command {arguments.command!r}")


def run(argv: Sequence[str], context: Context) -> Outcome:
    return run_command(argv, context, build_parser, execute)


def main(argv: Sequence[str]) -> int:
    return run_main(argv, build_parser, execute)


__all__ = ["available_themes", "build_parser", "choose_theme", "execute", "main", "run"]
