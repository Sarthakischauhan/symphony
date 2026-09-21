"""Thin Harbor agent: docker-run ``symphony-bench`` against the trial workspace."""

from __future__ import annotations

import asyncio
import os
import tomllib
from pathlib import Path
from typing import Any

try:
    from harbor.agents.base import BaseAgent as _HarborBase
except ImportError:  # Harbor is optional; the CLI image does not import this module.
    _HarborBase = object  # type: ignore[misc, assignment]

IMAGE_DEFAULT = "symphony-bench:latest"
TESTBED = "/testbed"
INSTRUCTION = "/instruction.md"

_PASS_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    "AI_GATEWAY_API_KEY",
    "VERCEL_AI_GATEWAY_API_KEY",
    "SYMPHONY_MODEL",
    "OPENAI_MODEL",
    "ANTHROPIC_MODEL",
    "GEMINI_MODEL",
    "GROK_MODEL",
    "XAI_MODEL",
    "OPENROUTER_MODEL",
    "VERCEL_MODEL",
    "AI_GATEWAY_MODEL",
)


def load_config(path: Path | None = None) -> dict[str, Any]:
    source = path or Path(__file__).with_name("config.toml")
    if not source.is_file():
        return {}
    payload = tomllib.loads(source.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def symphony_model(name: str | None) -> str | None:
    if not name:
        return None
    if ":" in name:
        return name
    if "/" in name:
        provider, rest = name.split("/", 1)
        return f"{provider}:{rest}"
    return name


def docker_argv(
    *,
    workspace: Path,
    instruction: Path,
    model: str | None = None,
    max_turns: int | None = None,
    timeout: float | None = None,
    personality: str = "direct",
    jev: bool = False,
    image: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    cfg = load_config()
    image = image or str(cfg.get("image") or IMAGE_DEFAULT)
    model = symphony_model(model) or symphony_model(
        str(cfg["model"]) if cfg.get("model") else None
    )
    if max_turns is None and cfg.get("max_turns") is not None:
        max_turns = int(cfg["max_turns"])
    if timeout is None and cfg.get("timeout_sec") is not None:
        timeout = float(cfg["timeout_sec"])
    argv = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{workspace.resolve()}:{TESTBED}",
        "-v",
        f"{instruction.resolve()}:{INSTRUCTION}:ro",
    ]
    forwarded: set[str] = set()
    extra_env = extra_env or {}
    for name in (*_PASS_ENV, *extra_env):
        if name in forwarded:
            continue
        forwarded.add(name)
        if name in extra_env:
            argv.extend(["-e", f"{name}={extra_env[name]}"])
        elif name in os.environ:
            argv.extend(["-e", name])
    argv.append(image)
    argv.extend(["--instruction", INSTRUCTION, "--personality", personality])
    if model:
        argv.extend(["--model", model])
    if max_turns is not None:
        argv.extend(["--max-turns", str(max_turns)])
    if timeout is not None:
        argv.extend(["--timeout", str(timeout)])
    if jev:
        argv.append("--jev")
    return argv


def emit_workspace_patch(host_workspace: Path, environment: Any) -> None:
    src = host_workspace / "workspace.patch"
    trial_paths = getattr(environment, "trial_paths", None)
    trial_dir = getattr(trial_paths, "trial_dir", None) if trial_paths else None
    if not src.is_file() or trial_dir is None:
        return
    dest = Path(trial_dir) / "workspace.patch"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())


class SymphonyAgent(_HarborBase):
    """Map a Harbor trial to ``docker run -v workspace:/testbed … symphony bench``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if _HarborBase is not object:
            super().__init__(*args, **kwargs)
        else:
            self.logs_dir = kwargs.get("logs_dir")
            self.model_name = kwargs.get("model_name")
            self._extra_env = dict(kwargs.get("extra_env") or {})
            self.options = kwargs

    @staticmethod
    def name() -> str:
        return "symphony"

    def version(self) -> str | None:
        return "0.1.0"

    async def setup(self, environment: Any) -> None:
        del environment

    async def run(self, instruction: str, environment: Any, context: Any) -> None:
        cfg = load_config()
        workdir = str(getattr(getattr(environment, "task_env_config", None), "workdir", None) or TESTBED)
        extra_env = dict(getattr(self, "extra_env", None) or getattr(self, "_extra_env", {}) or {})
        logs_dir = getattr(self, "logs_dir", None)
        async with _HostWorkspace(environment, workdir) as host_ws:
            instruction_path = host_ws.parent / "instruction.md"
            instruction_path.write_text(instruction, encoding="utf-8")
            argv = docker_argv(
                workspace=host_ws,
                instruction=instruction_path,
                model=symphony_model(getattr(self, "model_name", None)),
                personality=str(cfg.get("personality") or "direct"),
                extra_env=extra_env,
            )
            log_file = None
            stdout = None
            if logs_dir is not None:
                Path(logs_dir).mkdir(parents=True, exist_ok=True)
                log_file = open(Path(logs_dir) / "symphony-bench.log", "w", encoding="utf-8")
                stdout = log_file
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=stdout,
                    stderr=stdout,
                )
                code = await proc.wait()
            finally:
                if log_file is not None:
                    log_file.close()
            emit_workspace_patch(host_ws, environment)
            if context is not None:
                metadata = dict(getattr(context, "metadata", None) or {})
                metadata["exit_code"] = code
                context.metadata = metadata


class _HostWorkspace:
    """Download Harbor ``/testbed`` to a host dir, then upload the agent's edits back."""

    def __init__(self, environment: Any, workdir: str) -> None:
        self.environment = environment
        self.workdir = workdir
        self.path: Path | None = None
        self._tmp = None

    async def __aenter__(self) -> Path:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory(prefix="symphony-harbor-")
        root = Path(self._tmp.name)
        self.path = root / "testbed"
        self.path.mkdir()
        download = getattr(self.environment, "download_dir", None)
        if callable(download):
            await download(self.workdir, self.path)
        return self.path

    async def __aexit__(self, *_exc: object) -> None:
        upload = getattr(self.environment, "upload_dir", None)
        if callable(upload) and self.path is not None:
            await upload(self.path, self.workdir)
        if self._tmp is not None:
            self._tmp.cleanup()
