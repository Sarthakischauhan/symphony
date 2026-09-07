"""Small non-interactive installer used by Symphony and local automation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from coding_agent.config import spawn_settings_path

def add_entry(config: Path, section: str, entry: dict) -> None:
    data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
    data.setdefault(section, {}).setdefault("entries", []).append(entry)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

def main() -> None:
    parser = argparse.ArgumentParser(description="Register a coding-agent skill or plugin")
    parser.add_argument("kind", choices=("skill", "plugin"))
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--config",
        type=Path,
        default=spawn_settings_path(Path.cwd()),
        help="Settings file (default: .symphony/config.json)",
    )
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args()
    if args.kind == "skill":
        data = json.loads(args.config.read_text(encoding="utf-8")) if args.config.exists() else {}
        data.setdefault("skills", {}).setdefault("roots", []).append(str(args.path))
        args.config.parent.mkdir(parents=True, exist_ok=True)
        args.config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        entry = {"path": str(args.path), "enabled": args.enable}
        add_entry(args.config, "plugins", entry)

if __name__ == "__main__":
    main()
