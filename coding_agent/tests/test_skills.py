"""Skill front matter loads name, description, and args, and rejects hostile YAML."""

import time
from pathlib import Path

import pytest

from coding_agent.extension_args import ExtensionArg, render_args
from coding_agent.skills.frontmatter import read_front_matter
from coding_agent.skills.registry import SkillRegistry, bundled_skills_root


def _write_skill(root: Path, name: str, front: str, body: str = "Do the thing.\n") -> None:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")


def test_bundled_skills_all_load_with_a_valid_arg_contract():
    registry, diagnostics = SkillRegistry.discover([("bundled", bundled_skills_root())])
    assert diagnostics == ()
    assert len(registry.skills) == 7
    for skill in registry.skills:
        for arg in skill.args:
            assert arg.description
            assert arg.type != "enum" or arg.default is None or arg.default in arg.options


def test_folded_description_and_enum_arg(tmp_path: Path):
    _write_skill(
        tmp_path,
        "orient",
        """
name: orient
description: >
  Folded line
  still one description.
args:
  - name: depth
    type: enum
    enum: [sketch, thorough]
    description: How far to map.
    default: sketch
""".strip(),
    )
    registry, diagnostics = SkillRegistry.discover([("user", tmp_path)])
    assert diagnostics == ()
    skill = registry.get("user/orient")
    assert skill.description == "Folded line still one description."
    assert skill.args[0].options == ("sketch", "thorough")
    assert skill.args[0].default == "sketch"


def test_render_args_shows_type_options_default_and_required():
    args = (
        ExtensionArg(name="repro", type="string", description="Failing command.", required=True),
        ExtensionArg(name="depth", type="enum", enum=["sketch", "thorough"], description="D.", default="sketch"),
        ExtensionArg(name="max_files", type="number", description="N.", default=4),
        ExtensionArg(name="focus", type="string", description="F.", default=""),
    )
    assert render_args(args) == (
        "repro: string required, depth: enum[sketch|thorough]=sketch, max_files: number=4, focus: string"
    )


def test_malformed_skills_are_skipped_and_valid_skills_remain(tmp_path: Path):
    bad_enum = "name: bad-enum\ndescription: No options.\nargs:\n  - {name: m, type: enum, description: M.}"
    _write_skill(tmp_path, "bad-enum", bad_enum)
    _write_skill(tmp_path, "bad-yaml", "name: bad-yaml\ndescription: [unclosed")
    _write_skill(tmp_path, "ok-skill", "name: ok-skill\ndescription: This one still loads.\nargs: []")
    registry, diagnostics = SkillRegistry.discover([("user", tmp_path)])
    assert [skill.name for skill in registry.skills] == ["ok-skill"]
    assert sorted(Path(d.source).parent.name for d in diagnostics) == ["bad-enum", "bad-yaml"]
    assert any("invalid YAML front matter" in d.message for d in diagnostics)


def test_standard_keys_such_as_allowed_tools_are_ignored():
    meta = read_front_matter("---\nname: langfuse\ndescription: Trace runs.\nallowed-tools: Bash(curl:*)\n---\n")
    assert meta.name == "langfuse"


def test_closing_fence_at_eof_without_newline_is_accepted():
    assert read_front_matter("---\nname: demo\ndescription: Ends at EOF.\n---").name == "demo"


def test_mid_line_dashes_do_not_close_front_matter():
    meta = read_front_matter("---\nname: demo\ndescription: see foo---\n---\nbody ---\n")
    assert meta.description == "see foo---"


_BOMB = "a: &a [x, x, x, x, x, x, x, x, x]\n" + "".join(
    f"{chr(98 + i)}: &{chr(98 + i)} [*{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}]\n" for i in range(8)
)


@pytest.mark.parametrize(
    ("front", "error"),
    [
        (_BOMB + "name: bomb\ndescription: Alias bomb.", "aliases are not allowed"),
        ("name: big\ndescription: " + "x" * 4100, "byte limit"),
        ("name: demo\ndescription: [unclosed", "invalid YAML front matter"),
        ("name: demo\ndescription: D.\nargs: query", "tuple"),
        ("name: demo\ndescription: D.\nargs:\n  - {name: r, type: string, description: One.}\n"
         "  - {name: r, type: string, description: Two.}", "duplicate argument name"),
        ("name: demo\ndescription: D.\nargs:\n  - {name: d, type: enum, enum: [a, b], description: D., default: c}",
         "default is not in its enum"),
        ("name: demo\ndescription: D.\nargs:\n  - {name: r, type: string, description: R., required: true, default: x}",
         "required and cannot have a default"),
        ("name: demo\ndescription: D.\nargs:\n  - {name: n, type: number, description: N., default: true}",
         "does not match type number"),
        ("name: demo\ndescription: D.\nargs:\n  - {name: s, type: string, enum: [a], description: S.}",
         "other types take none"),
    ],
)
def test_invalid_front_matter_is_rejected(front: str, error: str):
    with pytest.raises(ValueError, match=error):
        read_front_matter(f"---\n{front}\n---\n")


def test_alias_bomb_is_rejected_quickly(tmp_path: Path):
    _write_skill(tmp_path, "bomb", _BOMB + "name: bomb\ndescription: Alias bomb.")
    started = time.monotonic()
    registry, diagnostics = SkillRegistry.discover([("user", tmp_path)])
    assert time.monotonic() - started < 1
    assert registry.skills == () and len(diagnostics) == 1
