"""Record a real Symphony terminal session driven through a pseudo-terminal."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import select
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


def child(workspace: Path, log: Path) -> None:
    """Launch the unmodified TUI and inject only a deterministic provider."""
    sys.path.insert(0, str(ROOT / "coding_agent" / "tests"))
    from scripted_registry import ScriptedRegistry, first_user_text
    from coding_agent import CodingAgent
    from coding_agent.tui import app as tui_app
    from core_ai.models import list_models

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
    palette = {"default": "#d8dee9", "black": "#161616", "white": "#eeeeee", "red": "#ef7777", "green": "#8acb88", "yellow": "#e8c97a", "blue": "#8aaaff", "cyan": "#8ad9d0", "magenta": "#d9a3ee"}
    for y in range(screen.lines):
        for x, char in screen.buffer[y].items():
            if not (0 <= x < screen.columns) or not char.data.strip():
                continue
            color = palette.get(char.fg, f"#{char.fg}" if len(char.fg) == 6 else "#d8dee9")
            draw.text((12 + x * cell_w, 10 + y * cell_h), char.data, font=face, fill=color)
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", default="100x32")
    parser.add_argument("--timeout", type=float, default=35, help="Scenario deadline in seconds")
    parser.add_argument("--output", type=Path, default=Path("artifacts/tui-e2e"))
    parser.add_argument("--child", nargs=2, metavar=("WORKSPACE", "LOG"))
    args = parser.parse_args()
    if args.child:
        child(Path(args.child[0]), Path(args.child[1]))
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
        raise RuntimeError("ffmpeg is required to encode the terminal recording")
    with tempfile.TemporaryDirectory(prefix="symphony-tui-e2e-") as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        workspace.mkdir()
        log = root / "models.jsonl"
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(root), "SYMPHONY_HOME": str(root / "home"),
               "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(workspace), str(log)],
                                stdin=slave, stdout=slave, stderr=slave, cwd=workspace, env=env, start_new_session=True)
        os.close(slave)
        screen = pyte.Screen(cols, rows)
        stream = pyte.ByteStream(screen)
        face = font()
        frames = root / "frames"
        frames.mkdir()
        captures = []
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
            video = output / "child-model.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "5", "-i", str(frames / "%05d.png"),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", str(video)], check=True)
            player = output / "player"
            player.mkdir(exist_ok=True)
            (player / "child-model.mp4").write_bytes(video.read_bytes())
            (player / "index.html").write_text(
                '<!doctype html><html lang="en"><meta charset="utf-8">'
                '<title>Symphony TUI recording</title><body style="background:#111;color:#eee;font-family:sans-serif">'
                '<h1>Symphony TUI: subagent model selection</h1>'
                '<p>Real TUI on a pseudo-terminal, rendered with Pyte; responses use a scripted provider.</p>'
                '<video controls autoplay muted loop playsinline style="max-width:100%" src="child-model.mp4"></video>'
                '</body></html>', encoding="utf-8",
            )
            from coding_agent.addons.artifacts.capture import snapshot_site
            from coding_agent.addons.artifacts.store import ArtifactStore

            from coding_agent.addons.artifacts.store import artifact_id

            store = ArtifactStore(output / "versions")
            captured = snapshot_site(player, output, "Symphony TUI recording")
            saved = store.save("tui-e2e", captured, "pty-e2e")
            manifest = saved.manifest if saved else store.get("tui-e2e", artifact_id(captured.kind, captured.source))
            artifact = store.folder("tui-e2e", manifest.id) / f"v{manifest.version}"
            print(json.dumps({"video": str(video), "artifact": str(artifact), "version": manifest.version,
                              "frames": len(captures), "requests": requests, "inspector_visible": inspector_seen}, indent=2))
        except Exception:
            (output / "child-model-failure.txt").write_text(
                f"state: {state}\n\n" + "\n".join(screen.display), encoding="utf-8"
            )
            raise
        finally:
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
            os.close(master)
    return 0


def shutil_which_ffmpeg() -> bool:
    import shutil
    return shutil.which("ffmpeg") is not None


if __name__ == "__main__":
    raise SystemExit(main())
