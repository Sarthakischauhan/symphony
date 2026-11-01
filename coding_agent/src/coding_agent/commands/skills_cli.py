"""``symphony skills`` and ``/skills``: add, list, remove, enable, disable, mode, update."""

from __future__ import annotations

import argparse
from typing import Sequence

from coding_agent.addons.skills import (
    SkillUpdate,
    add_skills,
    remove_skill,
    set_skill_enabled,
    set_skill_mode,
    update_skills,
)
from coding_agent.commands.cli_support import Context, Outcome, Parser, main as run_main, run_command
from coding_agent.commands.installed import discover, saved_config, skills_report

def build_parser(prog: str = "symphony skills") -> Parser:
    parser = Parser(prog=prog, description="Install and manage skills (prompt files the model reads when they match the task).")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    add = commands.add_parser("add", help="install from a local path, git URL[@ref] or owner/repo")
    add.add_argument("source")
    add.add_argument("--project", action="store_true", help="install into the project's .agents/skills instead of ~/.symphony/skills")
    add.add_argument("--path", default="", metavar="DIR", help="use this subdirectory of the source")
    commands.add_parser("list", help="list skills with their catalog mode and token cost")
    for name, help_text in (("remove", "delete a skill installed by 'skills add'"), ("enable", "load a skill"), ("disable", "stop loading a skill")):
        commands.add_parser(name, help=help_text).add_argument("name")
    mode = commands.add_parser("mode", help="set how the catalog lists a skill")
    mode.add_argument("name")
    mode.add_argument("mode", choices=("on", "name-only", "manual", "default"))
    commands.add_parser("update", help="fetch installed skills again").add_argument("name", nargs="?")
    return parser


def _update_line(item: SkillUpdate) -> str:
    if item.error:
        return f"{item.name}: {item.error}"
    if item.before == item.after:
        return f"{item.name}: up to date"
    return f"{item.name}: {item.before or 'new'} → {item.after}"


def execute(arguments: argparse.Namespace, context: Context) -> Outcome:
    workspace = context.workspace
    match arguments.command:
        case "add":
            added = add_skills(arguments.source, workspace=workspace, cwd=context.cwd, project=arguments.project, subdir=arguments.path)
            lines = [f"Installed {item.name} ({item.scope}) → {item.path}" for item in added]
            return Outcome("\n".join(lines), changed=True)
        case "list":
            skills, _ = discover(workspace)
            return Outcome(skills_report(skills, saved_config(workspace).skills.max_context_tokens))
        case "remove":
            return Outcome(f"Removed {remove_skill(arguments.name, workspace=workspace)}", changed=True)
        case "enable" | "disable":
            enabled = arguments.command == "enable"
            set_skill_enabled(arguments.name, enabled, workspace=workspace)
            return Outcome(f"{'Enabled' if enabled else 'Disabled'} {arguments.name}", changed=True)
        case "mode":
            set_skill_mode(arguments.name, None if arguments.mode == "default" else arguments.mode, workspace=workspace)
            return Outcome(f"{arguments.name}: {arguments.mode}", changed=True)
        case "update":
            lines = [_update_line(item) for item in update_skills(arguments.name, workspace=workspace)]
            lines = lines or ["No skills were installed with 'skills add'."]
            return Outcome("\n".join(lines), changed=True)
    raise ValueError(f"unknown command {arguments.command!r}")


def run(argv: Sequence[str], context: Context) -> Outcome:
    return run_command(argv, context, build_parser, execute)


def main(argv: Sequence[str]) -> int:
    return run_main(argv, build_parser, execute)


__all__ = ["build_parser", "execute", "main", "run"]
