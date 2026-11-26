"""Keep published workspace dependency floors aligned with the release."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]


def test_workspace_release_dependency_floors():
    projects = {}
    for directory in ("core_ai", "core_harness", "coding_agent", "core_server", "browser_agent"):
        with (ROOT / directory / "pyproject.toml").open("rb") as file:
            projects[directory] = tomllib.load(file)["project"]

    assert Version(projects["core_harness"]["version"]) >= Version("0.0.10")
    assert Version(projects["core_ai"]["version"]) >= Version("0.0.8")
    for directory, required in {
        "core_harness": ("symphony-core",),
        "coding_agent": ("symphony-core", "symphony-harness"),
        "core_server": ("symphony-core", "symphony-harness"),
        "browser_agent": ("symphony-core", "symphony-harness"),
    }.items():
        dependencies = {req.name: req for req in map(Requirement, projects[directory]["dependencies"])}
        for name in required:
            specifier = dependencies[name].specifier
            if (directory, name) == ("coding_agent", "symphony-core"):
                minimum, previous = "0.0.8", "0.0.7"
            elif (directory, name) == ("coding_agent", "symphony-harness"):
                minimum, previous = "0.0.10", "0.0.9"
            else:
                minimum, previous = "0.0.7", "0.0.6"
            assert Version(minimum) in specifier, (directory, name)
            assert Version(previous) not in specifier, (directory, name)
