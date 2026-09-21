"""Headless ``symphony bench``: run ``CodingAgent``, write patch + result.json."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Sequence

from core_ai import has_configured_provider
from core_ai.providers.catalog import MissingProviderCredentials
from core_harness import EventSink, HarnessCancelled, HarnessLimitExceeded

from coding_agent.agent import CodingAgent
from coding_agent.bench.patch import git_head, write_workspace_patch
from coding_agent.config import (
    ApprovalConfig,
    CodingAgentConfig,
    EvaluationConfig,
    LearningConfig,
    PluginsConfig,
    default_coding_agent_harness,
)
from coding_agent.credentials import load_provider_env

PERSONALITIES = ("direct", "precise")


def _config_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("SYMPHONY_BENCH_CONFIG", "").strip()
    if env:
        paths.append(Path(env))
    paths.append(Path("/opt/symphony/bench/config.toml"))
    here = Path(__file__).resolve()
    if len(here.parents) >= 5:
        paths.append(here.parents[4] / "bench" / "config.toml")
    return paths


def load_bench_config() -> dict[str, Any]:
    for path in _config_paths():
        if path.is_file():
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    return {}


def build_parser(defaults: dict[str, Any] | None = None) -> argparse.ArgumentParser:
    defaults = defaults if defaults is not None else load_bench_config()
    testbed = str(defaults.get("testbed") or "/testbed")
    workspace = testbed if Path(testbed).is_dir() else "."
    parser = argparse.ArgumentParser(
        prog="symphony bench",
        description="Headless Symphony bench run. Writes workspace.patch and result.json.",
    )
    parser.add_argument("--workspace", default=workspace, help="Working directory (default: /testbed if present, else .)")
    parser.add_argument(
        "--instruction",
        default="-",
        help="Instruction file, or - for stdin",
    )
    parser.add_argument("--model", default=defaults.get("model"), help="provider:model id")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=int(defaults["max_turns"]) if defaults.get("max_turns") is not None else None,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(defaults["timeout_sec"]) if defaults.get("timeout_sec") is not None else None,
        help="Run time cap in seconds (harness max_runtime_seconds)",
    )
    parser.add_argument(
        "--personality",
        choices=PERSONALITIES,
        default=str(defaults.get("personality") or "direct"),
        help="Fixed personality (no picker)",
    )
    parser.add_argument(
        "--jev",
        dest="enable_jev",
        action="store_true",
        default=False,
        help="Enable Jev critic mode (off by default)",
    )
    return parser


def read_instruction(value: str) -> str:
    if value == "-":
        if sys.stdin.isatty():
            raise SystemExit("instruction required: pass --instruction FILE or pipe stdin")
        return sys.stdin.read()
    path = Path(value).expanduser()
    if not path.is_file():
        raise SystemExit(f"instruction file not found: {value}")
    return path.read_text(encoding="utf-8")


def _write_result(workspace: Path, payload: dict[str, Any]) -> None:
    (workspace / "result.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _turns(sink: EventSink) -> int:
    return sum(1 for event in sink.events if event.event_type == "turn_started")


def _isolate_home() -> None:
    os.environ["HOME"] = tempfile.mkdtemp(prefix="symphony-bench-home-")


def _bench_config(
    *,
    personality: str,
    enable_jev: bool,
    max_turns: int | None,
    timeout: float | None,
) -> CodingAgentConfig:
    harness = default_coding_agent_harness()
    updates: dict[str, Any] = {}
    if max_turns is not None:
        updates["max_turns"] = max_turns
    if timeout is not None:
        updates["max_runtime_seconds"] = float(timeout)
    if updates:
        harness = harness.model_copy(update=updates)
    return CodingAgentConfig(
        harness=harness,
        personality=personality,
        learning=LearningConfig(enabled=False),
        evaluation=EvaluationConfig(enabled=enable_jev),
        plugins=PluginsConfig(enabled=False),
        approvals=ApprovalConfig(mode="always_allow"),
    )


async def _run_agent(agent: CodingAgent, instruction: str) -> None:
    await agent.run(instruction)


def run_bench(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    instruction = read_instruction(args.instruction)
    load_provider_env(workspace)
    start_ref = git_head(workspace)
    sink = EventSink()
    ok = False
    error: str | None = None
    try:
        if not has_configured_provider():
            raise MissingProviderCredentials()
        _isolate_home()
        from core_ai import build_default_registry, default_model_id

        registry = build_default_registry()
        agent = CodingAgent(
            registry=registry,
            model_id=default_model_id(registry, args.model),
            workspace=workspace,
            config=_bench_config(
                personality=args.personality,
                enable_jev=bool(args.enable_jev),
                max_turns=args.max_turns,
                timeout=args.timeout,
            ),
            sink=sink,
        )
        asyncio.run(_run_agent(agent, instruction))
        ok = True
    except HarnessLimitExceeded:
        ok = True
    except HarnessCancelled as exc:
        error = str(exc) or "cancelled"
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
    turns = _turns(sink)
    write_workspace_patch(workspace, start_ref=start_ref)
    payload: dict[str, Any] = {"ok": ok, "turns": turns}
    if error:
        payload["error"] = error
    _write_result(workspace, payload)
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_bench(args)
