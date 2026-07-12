from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CORE_AI_SRC = ROOT / "src"

if str(CORE_AI_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_AI_SRC))
