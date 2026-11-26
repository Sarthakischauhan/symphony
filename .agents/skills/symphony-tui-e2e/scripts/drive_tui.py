"""Record a real Symphony terminal session driven through a pseudo-terminal (MP4 only)."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

import pyte
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[4]
PROMPT = "Inspect the auth flow."
CHILD = "Inspect auth and report the result."
PARENT_MODEL = "openai:gpt-5.6-luna"
CHILD_MODEL = "openai:gpt-5.6-sol"

DYNAMIC_PROMPT = "Verify live Astra model routing."
DYNAMIC_START_MODEL = "openai:gpt-5.6-luna"
DYNAMIC_TARGETS = (
    ("openai", "gpt-6.2-astra"),
    ("gemini", "gemini-4-carbon"),
    ("gemini", "gemini-4-hydrogen"),
    ("gemini", "gemini-4-neon"),
)


def encode_mp4(frames_dir: Path, video_path: Path, *, framerate: int = 5) -> Path:
    """Encode captured PNG frames as H.264 MP4 only; reject GIF or other formats."""
    if video_path.suffix.lower() != ".mp4":
        raise ValueError(f"Only .mp4 video output is supported (got {video_path.name!r}); GIF is not supported.")
    if not shutil_which_ffmpeg():
        raise RuntimeError("ffmpeg is required to encode the MP4 terminal recording")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-framerate",
            str(framerate),
            "-i",
            str(frames_dir / "%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            str(video_path),
        ],
        check=True,
    )
    if not video_path.is_file() or video_path.stat().st_size == 0:
        raise RuntimeError(f"MP4 encoding produced an empty file: {video_path}")
    header = video_path.read_bytes()[:32]
    if b"ftyp" not in header:
        raise RuntimeError(f"Encoded video is missing an MP4 ftyp header: {video_path}")
    return video_path


def publish_html_player(
    output: Path,
    video: Path,
    *,
    title: str,
    subtitle: str,
    artifact_name: str,
) -> tuple[Path, int]:
    """Package an MP4 inside an HTML <video> player folder and version it (no GIFs)."""
    if video.suffix.lower() != ".mp4":
        raise ValueError(f"HTML video player only accepts .mp4 recordings (got {video.name!r}).")
    player = output / "player"
    if player.exists():
        shutil.rmtree(player)
    player.mkdir(parents=True, exist_ok=True)
    (player / video.name).write_bytes(video.read_bytes())
    (player / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        f"<title>{title}</title>"
        '<body style="background:#111;color:#eee;font-family:sans-serif;margin:24px">'
        f"<h1>{title}</h1>"
        f"<p>{subtitle}</p>"
        f'<video controls autoplay muted loop playsinline style="max-width:100%;border:1px solid #333" src="{video.name}"></video>'
        "</body></html>",
        encoding="utf-8",
    )
    if list(player.rglob("*.gif")):
        raise RuntimeError("GIF files are forbidden in the MP4 HTML player folder.")
    from coding_agent.addons.artifacts.capture import snapshot_site
    from coding_agent.addons.artifacts.store import ArtifactStore, artifact_id

    store = ArtifactStore(output / "versions")
    captured = snapshot_site(player, output, title)
    saved = store.save(artifact_name, captured, "pty-e2e")
    manifest = saved.manifest if saved else store.get(artifact_name, artifact_id(captured.kind, captured.source))
    artifact = store.folder(artifact_name, manifest.id) / f"v{manifest.version}"
    return artifact, manifest.version


def child_subagent(workspace: Path, log: Path) -> None:
    """Launch the unmodified TUI and inject only a deterministic provider."""
    sys.path.insert(0, str(ROOT / "coding_agent" / "tests"))
    from coding_agent import CodingAgent
    from coding_agent.tui import app as tui_app
    from core_ai.models import list_models
    from scripted_registry import ScriptedRegistry, first_user_text

    class Registry(ScriptedRegistry):
        def __init__(self):
            super().__init__({PROMPT: [[("spawn_agent", {
                "prompt": CHILD, "label": "Auth", "model_id": CHILD_MODEL, "background": False,
            })]]})

        def namespaces(self):
            return ("openai",)

        def models(self, provider=None):
            return list_models(provider)

        async def stream(self, model_id, messages, tools=None, **kwargs):
            with log.open("a", encoding="utf-8") as output:
                output.write(json.dumps({"prompt": first_user_text(messages), "model": model_id}) + "\n")
            async for event in super().stream(model_id, messages, tools, **kwargs):
                yield event

    def build_agent(**kwargs):
        return CodingAgent(
            registry=Registry(), model_id=PARENT_MODEL, workspace=workspace,
            sink=kwargs["sink"], config=kwargs["config"],
        )

    tui_app.build_agent = build_agent
    tui_app.CodingAgentApp(workspace=workspace, model_id=PARENT_MODEL, enable_learning=False).run()


def child_dynamic_models(workspace: Path, log: Path) -> None:
    """Launch the unmodified TUI with real live models.dev background discovery."""
    sys.path.insert(0, str(ROOT / "coding_agent" / "tests"))
    from coding_agent import CodingAgent
    from coding_agent.tui import app as tui_app
    from core_ai.models import get_model, list_models, unregister_model
    from scripted_registry import ScriptedRegistry, first_user_text

    # Remove target latest models before launch so the run proves live
    # https://models.dev/api.json discovery registers them at runtime.
    for provider, model_id in DYNAMIC_TARGETS:
        unregister_model(provider, model_id)
        assert get_model(provider, model_id) is None

    with log.open("a", encoding="utf-8") as output:
        output.write(json.dumps({
            "event": "before_launch_absent",
            "models": [f"{provider}:{model_id}" for provider, model_id in DYNAMIC_TARGETS],
        }) + "\n")

    class Registry(ScriptedRegistry):
        def __init__(self):
            super().__init__({})

        def namespaces(self):
            return ("openai", "gemini")

        def models(self, provider=None):
            return list_models(provider)

        async def stream(self, model_id, messages, tools=None, **kwargs):
            with log.open("a", encoding="utf-8") as output:
                output.write(json.dumps({
                    "event": "request",
                    "prompt": first_user_text(messages),
                    "model": model_id,
                }) + "\n")
            async for event in super().stream(model_id, messages, tools, **kwargs):
                yield event

    def build_agent(**kwargs):
        return CodingAgent(
            registry=Registry(), model_id=DYNAMIC_START_MODEL, workspace=workspace,
            sink=kwargs["sink"], config=kwargs["config"],
        )

    tui_app.build_agent = build_agent
    try:
        tui_app.CodingAgentApp(workspace=workspace, model_id=DYNAMIC_START_MODEL, enable_learning=False).run()
    finally:
        discovered = []
        for provider, model_id in DYNAMIC_TARGETS:
            info = get_model(provider, model_id)
            if info is not None:
                discovered.append({
                    "full_id": info.full_id,
                    "api": info.api,
                    "context_limit": info.context_limit,
                    "price": (
                        {
                            "input": info.price.input,
                            "output": info.price.output,
                            "cache_read": info.price.cache_read,
                            "cache_write": info.price.cache_write,
                        }
                        if info.price is not None
                        else None
                    ),
                })
        with log.open("a", encoding="utf-8") as output:
            output.write(json.dumps({"event": "discovered", "models": discovered}) + "\n")


def font():
    for path in ("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, 16)
    return ImageFont.load_default(size=16)


def render(screen: pyte.Screen, face: ImageFont.FreeTypeFont) -> Image.Image:
    cell_w = int(face.getlength("M") + 1)
    cell_h = 21
    image = Image.new("RGB", (screen.columns * cell_w + 24, screen.lines * cell_h + 24), "#0b0d10")
    draw = ImageDraw.Draw(image)
    palette = {
        "default": "#d8dee9", "black": "#161616", "white": "#eeeeee",
        "red": "#ef7777", "green": "#8acb88", "yellow": "#e8c97a",
        "blue": "#8aaaff", "cyan": "#8ad9d0", "magenta": "#d9a3ee",
    }
    for y in range(screen.lines):
        for x, char in screen.buffer[y].items():
            if not (0 <= x < screen.columns):
                continue
            fg = palette.get(char.fg, f"#{char.fg}" if len(char.fg) == 6 else "#d8dee9")
            bg = None if char.bg == "default" else palette.get(char.bg, f"#{char.bg}" if len(char.bg) == 6 else None)
            if char.reverse:
                fg, bg = bg or "#0b0d10", fg
            px, py = 12 + x * cell_w, 10 + y * cell_h
            if bg is not None:
                draw.rectangle((px, py, px + cell_w, py + cell_h), fill=bg)
            if char.data.strip():
                draw.text((px, py), char.data, font=face, fill=fg)
    return image


def _build_env(root: Path) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(root),
        "SYMPHONY_HOME": str(root / "home"),
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
    }
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def _terminate_child(proc: subprocess.Popen[bytes], master: int) -> None:
    if proc.poll() is None:
        try:
            os.write(master, b"\x11")
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def _run_subagent(args: argparse.Namespace, cols: int, rows: int, output: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="symphony-tui-e2e-") as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        workspace.mkdir()
        log = root / "models.jsonl"
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--child", "subagent", str(workspace), str(log)],
            stdin=slave, stdout=slave, stderr=slave, cwd=workspace, env=_build_env(root), start_new_session=True,
        )
        os.close(slave)
        screen = pyte.Screen(cols, rows)
        stream = pyte.ByteStream(screen)
        face = font()
        frames = root / "frames"
        frames.mkdir()
        captures: list[str] = []
        state = "startup"
        start = time.monotonic()
        last_frame = 0.0
        last_action = start
        inspector_seen = False
        try:
            while time.monotonic() - start < args.timeout:
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        data = b""
                    if data:
                        stream.feed(data)
                now = time.monotonic()
                text = "\n".join(screen.display)
                if now - last_frame >= 0.2:
                    render(screen, face).save(frames / f"{len(captures):05}.png")
                    captures.append(text)
                    last_frame = now
                if state == "startup" and "Ask Symphony" in text and now - start > 1:
                    os.write(master, PROMPT.encode() + b"\r")
                    state, last_action = "running", now
                elif state == "running" and "Subagent Auth completed" in text and "all done" in text:
                    if now - last_action > 1:
                        os.write(master, b"\x07")
                        state, last_action = "inspector", now
                elif state == "inspector" and CHILD_MODEL in text and "completed" in text:
                    inspector_seen = True
                    if now - last_action > 2:
                        break
                if proc.poll() is not None:
                    raise RuntimeError(f"TUI exited unexpectedly ({proc.returncode}):\n{text}")
            else:
                raise TimeoutError(f"TUI scenario timed out in {state}:\n{text}")
            requests = [json.loads(line) for line in log.read_text().splitlines()]
            assert {"prompt": PROMPT, "model": PARENT_MODEL} in requests
            assert {"prompt": CHILD, "model": CHILD_MODEL} in requests
            assert inspector_seen
            (output / "child-model.txt").write_text("\n\n--- frame ---\n\n".join(captures), encoding="utf-8")
            video = encode_mp4(frames, output / "child-model.mp4")
            artifact, version = publish_html_player(
                output,
                video,
                title="Symphony TUI: subagent model selection",
                subtitle="Real TUI on a pseudo-terminal, rendered with Pyte as MP4; responses use a scripted provider.",
                artifact_name="tui-e2e",
            )
            print(json.dumps({
                "scenario": "subagent",
                "format": "mp4",
                "video": str(video),
                "artifact": str(artifact),
                "version": version,
                "frames": len(captures),
                "requests": requests,
                "inspector_visible": inspector_seen,
            }, indent=2))
        except Exception:
            (output / "child-model-failure.txt").write_text(
                f"state: {state}\n\n" + "\n".join(screen.display), encoding="utf-8"
            )
            raise
        finally:
            _terminate_child(proc, master)
            os.close(master)
    return 0


def _run_dynamic_models(args: argparse.Namespace, cols: int, rows: int, output: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="symphony-tui-e2e-models-") as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        workspace.mkdir()
        log = root / "events.jsonl"
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--child", "dynamic-models", str(workspace), str(log)],
            stdin=slave, stdout=slave, stderr=slave, cwd=workspace, env=_build_env(root), start_new_session=True,
        )
        os.close(slave)
        screen = pyte.Screen(cols, rows)
        stream = pyte.ByteStream(screen)
        face = font()
        frames = root / "frames"
        frames.mkdir()
        captures: list[str] = []
        state = "startup"
        start = time.monotonic()
        last_frame = 0.0
        last_action = start
        last_nudge = start
        astra_menu_seen = False
        gemini_menu_seen = False
        try:
            while time.monotonic() - start < args.timeout:
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        data = b""
                    if data:
                        stream.feed(data)
                now = time.monotonic()
                text = "\n".join(screen.display)
                topbar = "\n".join(screen.display[:4])
                if now - last_frame >= 0.2:
                    render(screen, face).save(frames / f"{len(captures):05}.png")
                    captures.append(text)
                    last_frame = now
                if state == "startup" and "Ask Symphony" in text and now - start > 2.0:
                    os.write(master, b"/model astra")
                    state, last_action, last_nudge = "wait_astra_menu", now, now
                elif state == "wait_astra_menu":
                    if "gpt-6.2-astra" in text:
                        astra_menu_seen = True
                        if now - last_action > 1.2:
                            # Clear the prompt line before typing an unambiguous filter.
                            os.write(master, b"\x15")
                            state, last_action = "type_astra_exact", now
                    elif now - last_nudge > 1.0:
                        os.write(master, b"\x7f")
                        state, last_nudge, last_action = "nudge_astra_menu", now, now
                elif state == "nudge_astra_menu" and now - last_action > 0.25:
                    os.write(master, b"a")
                    state, last_nudge, last_action = "wait_astra_menu", now, now
                elif state == "type_astra_exact" and now - last_action > 0.35:
                    os.write(master, b"/model 6.2-astra")
                    state, last_action = "select_astra", now
                elif state == "select_astra" and "gpt-6.2-astra" in text and now - last_action > 0.8:
                    os.write(master, b"\r")
                    state, last_action = "wait_astra_switched", now
                elif state == "wait_astra_switched" and "gpt-6.2-astra" in topbar and "1,050,000" in text:
                    if now - last_action > 1.2:
                        os.write(master, b"/model gemini-4")
                        state, last_action = "wait_gemini_menu", now
                elif state == "wait_gemini_menu":
                    if all(name in text for name in ("gemini-4-carbon", "gemini-4-hydrogen", "gemini-4-neon")):
                        gemini_menu_seen = True
                        if now - last_action > 1.2:
                            os.write(master, b"-carbon")
                            state, last_action = "select_gemini", now
                elif state == "select_gemini" and "gemini-4-carbon" in text and now - last_action > 0.8:
                    os.write(master, b"\r")
                    state, last_action = "wait_gemini_switched", now
                elif state == "wait_gemini_switched" and "gemini-4-carbon" in topbar and "1,048,576" in text:
                    if now - last_action > 1.2:
                        os.write(master, b"/model 6.2-astra")
                        state, last_action = "return_astra_menu", now
                elif state == "return_astra_menu" and "gpt-6.2-astra" in text and now - last_action > 0.8:
                    os.write(master, b"\r")
                    state, last_action = "wait_return_astra", now
                elif state == "wait_return_astra" and "gpt-6.2-astra" in topbar and "1,050,000" in text:
                    if now - last_action > 0.8:
                        os.write(master, DYNAMIC_PROMPT.encode() + b"\r")
                        state, last_action = "wait_reply", now
                elif state == "wait_reply" and "all done" in text:
                    if now - last_action > 1.5:
                        break
                if proc.poll() is not None:
                    raise RuntimeError(f"TUI exited unexpectedly ({proc.returncode}):\n{text}")
            else:
                raise TimeoutError(f"TUI scenario timed out in {state}:\n{text}")

            _terminate_child(proc, master)
            events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            requests = [event for event in events if event.get("event") == "request"]
            discovered_entries = [event for event in events if event.get("event") == "discovered"]
            assert astra_menu_seen, "gpt-6.2-astra never appeared in the live /model picker"
            assert gemini_menu_seen, "Gemini 4 models never appeared in the live /model picker"
            assert any(
                req.get("prompt") == DYNAMIC_PROMPT and req.get("model") == "openai:gpt-6.2-astra"
                for req in requests
            ), f"Expected request on openai:gpt-6.2-astra, got {requests}"
            discovered = discovered_entries[-1]["models"] if discovered_entries else []
            discovered_ids = {item["full_id"] for item in discovered}
            expected_ids = {f"{provider}:{model_id}" for provider, model_id in DYNAMIC_TARGETS}
            assert expected_ids <= discovered_ids, f"Missing live models.dev entries: {expected_ids - discovered_ids}"

            (output / "dynamic-models.txt").write_text("\n\n--- frame ---\n\n".join(captures), encoding="utf-8")
            video = encode_mp4(frames, output / "dynamic-models.mp4")
            artifact, version = publish_html_player(
                output,
                video,
                title="Symphony TUI: live models.dev catalog discovery",
                subtitle=(
                    "Real TUI on a pseudo-terminal recorded as MP4 only. Catalog data fetched live from "
                    "https://models.dev/api.json in a background subprocess; LLM reply uses a scripted provider."
                ),
                artifact_name="tui-e2e-dynamic-models",
            )
            print(json.dumps({
                "scenario": "dynamic-models",
                "format": "mp4",
                "video": str(video),
                "artifact": str(artifact),
                "version": version,
                "frames": len(captures),
                "live_catalog_source": "https://models.dev/api.json",
                "discovered_models": discovered,
                "requests": requests,
                "astra_menu_visible": astra_menu_seen,
                "gemini_menu_visible": gemini_menu_seen,
            }, indent=2))
        except Exception:
            (output / "dynamic-models-failure.txt").write_text(
                f"state: {state}\n\n" + "\n".join(screen.display), encoding="utf-8"
            )
            raise
        finally:
            _terminate_child(proc, master)
            os.close(master)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("subagent", "dynamic-models"), default="subagent")
    parser.add_argument("--size", default="100x32")
    parser.add_argument("--timeout", type=float, default=35, help="Scenario deadline in seconds")
    parser.add_argument("--output", type=Path, default=Path("artifacts/tui-e2e"))
    parser.add_argument("--child", nargs=3, metavar=("SCENARIO", "WORKSPACE", "LOG"))
    args = parser.parse_args()
    if args.child:
        scenario_name, workspace_arg, log_arg = args.child
        if scenario_name == "dynamic-models":
            child_dynamic_models(Path(workspace_arg), Path(log_arg))
        else:
            child_subagent(Path(workspace_arg), Path(log_arg))
        return 0
    try:
        cols, rows = map(int, args.size.lower().split("x", 1))
        if cols < 40 or rows < 10 or args.timeout <= 0:
            raise ValueError
    except ValueError:
        parser.error("--size must be COLSxROWS (at least 40x10) and --timeout must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    if not shutil_which_ffmpeg():
        raise RuntimeError("ffmpeg is required to encode the MP4 terminal recording")
    if args.scenario == "dynamic-models":
        return _run_dynamic_models(args, cols, rows, output)
    return _run_subagent(args, cols, rows, output)


def shutil_which_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


if __name__ == "__main__":
    raise SystemExit(main())
