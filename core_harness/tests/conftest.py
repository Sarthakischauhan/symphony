from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
CORE_HARNESS_SRC = ROOT / "src"
CORE_AI_SRC = REPO_ROOT / "core_ai" / "src"

for src_path in (CORE_HARNESS_SRC, CORE_AI_SRC):
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
