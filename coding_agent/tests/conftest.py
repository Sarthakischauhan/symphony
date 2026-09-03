from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent

for src_path in (
    ROOT / "src",
    REPO_ROOT / "core_harness" / "src",
    REPO_ROOT / "core_ai" / "src",
):
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


@pytest.fixture(autouse=True)
def _isolate_symphony_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home
