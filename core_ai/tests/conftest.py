from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE_AI_SRC = ROOT / "src"

if str(CORE_AI_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_AI_SRC))


@pytest.fixture(autouse=True)
def _isolate_symphony_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home
