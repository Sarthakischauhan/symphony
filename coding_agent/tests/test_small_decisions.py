"""Shared decisions used by several surfaces: /jev argument, partial tool args, path args."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from coding_agent.addons.persistence.jsonl import JsonlPersistence
from coding_agent.commands.jev_argument import JevChange, parse_jev_argument
from coding_agent.config import ensure_spawn_settings
from coding_agent.protocols.stdio.commands import execute
from coding_agent.tools.patch import PatchArgs
from coding_agent.tools.write_file import WriteFileArgs
from coding_agent.tui.tools.labels import patch_path, read_file_detail
from coding_agent.tui.tools.partial_args import string_field


@pytest.mark.parametrize(
    ("current", "argument", "expected"),
    [
        (False, "", JevChange(enabled=True)),
        (True, "", JevChange(enabled=False)),
        (False, "toggle", JevChange(enabled=True)),
        (True, "TOGGLE", JevChange(enabled=False)),
        (True, "  toggle  ", JevChange(enabled=False)),
        *[(current, word, JevChange(enabled=True)) for current in (False, True) for word in ("on", "enable", "true", "1", "ON", "Enable")],
        *[(current, word, JevChange(enabled=False)) for current in (False, True) for word in ("off", "disable", "false", "0", "OFF", "Disable")],
        (False, "model", JevChange(enabled=True, rule="model")),
        (True, "Never touch migrations", JevChange(enabled=True, rule="Never touch migrations")),
        (False, "  keep tests green  ", JevChange(enabled=True, rule="keep tests green")),
        (False, "on please", JevChange(enabled=True, rule="on please")),
        (True, "off-limits: vendor/", JevChange(enabled=True, rule="off-limits: vendor/")),
    ],
)
def test_parse_jev_argument_table(current: bool, argument: str, expected: JevChange) -> None:
    assert parse_jev_argument(current, argument) == expected


def test_stdio_jev_stores_the_rule_in_config_and_keywords_keep_it(tmp_path: Path) -> None:
    agent = SimpleNamespace(
        workspace=tmp_path,
        config=ensure_spawn_settings(tmp_path),
        apply_system_prompt=lambda: None,
    )
    assert asyncio.run(execute(agent, "/jev Be Terse")) == "Jev enabled for the next turn."
    assert agent.config.evaluation.enabled is True
    assert agent.config.evaluation.rule == "Be Terse"
    assert asyncio.run(execute(agent, "/jev OFF")) == "Jev disabled for the next turn."
    assert agent.config.evaluation.enabled is False
    assert agent.config.evaluation.rule == "Be Terse"
    assert asyncio.run(execute(agent, "/jev")) == "Jev enabled for the next turn."


def test_string_field_decodes_escapes_and_ignores_incomplete_values() -> None:
    raw = '{"path": "dir/a \\"quoted\\" name\\\\x.py", "command": "echo \\u00e9'
    assert string_field(raw, "path") == 'dir/a "quoted" name\\x.py'
    assert string_field(raw, "command") is None
    assert string_field(raw, "query") is None
    assert string_field('{"path": ""}', "path") == ""
    assert string_field('{"a.b": "x", "aXb": "y"}', "a.b") == "x"


def test_label_helpers_read_path_from_partial_arguments() -> None:
    raw = '{"path": "src/m\\u00f6d.py", "old_str": "x'
    assert patch_path({}, raw) == "src/möd.py"
    assert read_file_detail({}, raw) == "src/möd.py"
    assert read_file_detail({}, '{"offset": 3') == '{"offset": 3'


@pytest.mark.parametrize("model", [PatchArgs, WriteFileArgs])
def test_path_arguments_are_stripped_and_must_not_be_blank(model: type) -> None:
    extra = {"old_str": "a", "new_str": "b"} if model is PatchArgs else {"content": "  kept  \n"}
    parsed = model(path="  src/a.py\n", **extra)
    assert parsed.path == "src/a.py"
    if model is WriteFileArgs:
        assert parsed.content == "  kept  \n"
    with pytest.raises(ValidationError, match="path must be a non-empty string"):
        model(path="   ", **extra)
    with pytest.raises(ValidationError, match="at least 1 character"):
        model(path="", **extra)


def test_jsonl_persistence_declares_an_empty_client(tmp_path: Path) -> None:
    store = JsonlPersistence(tmp_path)
    assert store.client == ""
    assert store._ensure_metadata("s1")["client"] == ""
    store.client = "zeron"
    assert store._ensure_metadata("s2")["client"] == "zeron"
