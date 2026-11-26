---
name: symphony-tui-e2e
description: Test a Symphony TUI workflow in a real pseudo-terminal and provide a recorded MP4 video.
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
2. Run the real app as a subprocess in a pseudo-terminal. Send the actual keystrokes, wait for visible screen states with a timeout, and assert the result. Use an isolated temporary workspace (`HOME`, `SYMPHONY_HOME`); never use real provider credentials in automated tests. When testing public-data features (such as live `https://models.dev/api.json` catalog discovery), fetch real public data while keeping LLM provider inference scripted unless live inference is explicitly requested.
3. Capture terminal output with Pyte and record an **MP4 only** (H.264 / `yuv420p` with `+faststart`). **Never encode, convert to, or fall back to `.gif` files or SVG slideshows.** Because `save_artifact` (`kind: image`) rejects `.mp4`, always package the `.mp4` with an `index.html` `<video>` player (no `.gif` files in the folder), inspect a representative decoded PNG frame from the MP4, and publish the versioned HTML player folder with `save_artifact` (`kind: html`). Give the user the artifact link and version.
4. Report what passed, what the user can see, what used real data, and what was mocked/scripted. A Pyte recording reconstructs terminal cells; it is not a desktop screen capture. Scripted providers do not verify live model account access.

## Working examples

From the repository root, run either built-in scenario:

```sh
# Subagent model selection (default, fully offline scripted provider)
uv run python .agents/skills/symphony-tui-e2e/scripts/drive_tui.py --size 100x32

# Dynamic model catalog discovery using live https://models.dev/api.json data
uv run python .agents/skills/symphony-tui-e2e/scripts/drive_tui.py --scenario dynamic-models --size 110x34 --output artifacts/tui-e2e-models
```

- `subagent` starts `CodingAgentApp` on a PTY, submits a prompt, opens the subagent inspector, verifies the visible child model and recorded provider requests, and prints the MP4 path and versioned HTML player folder.
- `dynamic-models` unregisters the latest Astra and Gemini 4 models before launch, lets `CodingAgentApp`'s real background subprocess fetch live `https://models.dev/api.json` data, drives `/model` filtering and switching in the PTY, submits a prompt on `openai:gpt-6.2-astra` (scripted LLM reply), and outputs an MP4 + HTML player.

Both require macOS/Linux, Pyte, Pillow and `ffmpeg`; use `uv sync --all-packages` if workspace packages are missing. The script enforces `.mp4`-only video output and rejects `.gif` targets or `.gif` files in the player folder.

To test another scenario, copy or adapt `scripts/drive_tui.py`: replace its scripted response, prompt, keystrokes and visible assertions with those for the requested flow. Use a separate `--output` directory to preserve earlier evidence. Do not set private widget state to simulate user actions. Keep error paths nonzero, save the last screen, and clean up the process.

Inspect a decoded video frame (the first frame may be blank):

```sh
ffmpeg -y -ss 2 -i <video.mp4> -frames:v 1 <frame.png>
```

Open the frame with `read_file`. Publish the printed artifact folder with `save_artifact` (`kind: html`). If the run fails, inspect `<scenario>-failure.txt`, report the failure, and do not present it as a successful run.
