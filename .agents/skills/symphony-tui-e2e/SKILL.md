---
name: symphony-tui-e2e
description: Test a Symphony TUI workflow in a real pseudo-terminal and provide a recorded video.
args:
  - name: scenario
    type: string
    description: The user workflow to test.
    required: true
  - name: size
    type: string
    description: Terminal size as COLSxROWS.
    default: 100x32
---

# Test a TUI scenario

1. Identify the user's actions and the visible result. Inspect the relevant TUI code and existing tests.
2. Run the real app as a subprocess in a pseudo-terminal. Send the actual keystrokes, wait for visible screen states with a timeout, and assert the result. Use an isolated temporary workspace and scripted provider; never use real credentials in automated tests.
3. Capture terminal output with Pyte and record an MP4. Check a representative decoded frame, then publish the versioned HTML player with `save_artifact` (`kind: html`). Give the user the artifact link and version.
4. Report what passed, what the user can see, and what was mocked. A Pyte recording reconstructs terminal cells; it is not a desktop screen capture. Scripted providers do not verify live model availability.

## Working example

From the repository root, run:

```sh
uv run python .agents/skills/symphony-tui-e2e/scripts/drive_tui.py --size 100x32
```

This tests **only** subagent model selection: it starts `CodingAgentApp` on a PTY, submits a prompt, opens the subagent inspector, verifies the visible model and recorded provider requests, and prints the MP4 path and versioned artifact folder. It replaces agent construction with a scripted provider; it does not test CLI onboarding or live provider access. Requires macOS/Linux, Pyte, Pillow and ffmpeg; use `uv sync --all-packages` if workspace packages are missing.

To test another scenario, copy or adapt `scripts/drive_tui.py`: replace its scripted response, prompt, keystrokes and visible assertions with those for the requested flow. Use a separate `--output` directory to preserve earlier evidence. Do not set private widget state to simulate user actions. Keep error paths nonzero, save the last screen, and clean up the process.

Inspect a video frame (the first frame may be blank):

```sh
ffmpeg -y -ss 2 -i <video.mp4> -frames:v 1 <frame.png>
```

Open the frame with `read_file`. Publish the printed artifact folder with `save_artifact`. If the run fails, inspect `child-model-failure.txt`, report the failure, and do not present it as a successful run.
