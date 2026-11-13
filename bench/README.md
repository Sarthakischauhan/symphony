# Symphony bench

Headless `symphony bench` plus a Harbor Docker adapter. Sanity pack: produce a
patch and a container exit. The grader owns pass/fail. 70+ is not a v1 exit.

No gold or test patches are baked into the agent image.

## Image

From the repo root:

```sh
docker build -f bench/Dockerfile -t symphony-bench:latest .
```

The image is slim Python, `uv sync --frozen`, and the entrypoint is the headless
CLI. Mount the trial workspace at `/testbed`. Pass the instruction as a file.
Provider keys are environment variables; there is no TUI on this path.

```sh
docker run --rm \
  -v "$PWD/workspace:/testbed" \
  -v "$PWD/instruction.md:/instruction.md:ro" \
  -e ANTHROPIC_API_KEY \
  symphony-bench:latest \
  --instruction /instruction.md
```

On exit the workspace contains `workspace.patch` (git diff from start) and
`result.json` `{ok, turns, error?}`. Exit 0 means the agent finished cleanly.

## CLI

```sh
uv run --package symphony-code symphony bench \
  --workspace /testbed \
  --instruction instruction.md \
  --model anthropic:claude-sonnet-5 \
  --max-turns 24 \
  --timeout 900 \
  --personality direct
```

`--personality` is `direct` or `precise` only (no picker). `--jev` is off by
default. `--instruction -` (or omitted) reads stdin.

Pinned model and timeouts: [`config.toml`](config.toml).

## Harbor smoke

Agent name is `symphony`. Harbor custom agents take an import path.

```sh
export ANTHROPIC_API_KEY=...
PYTHONPATH=. harbor run --dataset swebench-verified \
  --agent bench.agent:SymphonyAgent \
  --model anthropic/claude-sonnet-5 \
  --include-task-name astropy__astropy-12907 \
  --n-concurrent 1
```

The adapter maps a trial to:

```text
docker run -v workspace:/testbed … symphony-bench:latest --instruction /instruction.md
```

and copies `workspace.patch` to the Harbor trial directory.

Pinned SWE-bench Verified ids: [`smoke_ids.txt`](smoke_ids.txt) (8 ids). For each
id, assert `workspace.patch` exists and the container exited.

```sh
while read -r id; do
  PYTHONPATH=. harbor run --dataset swebench-verified \
    --agent bench.agent:SymphonyAgent \
    --model anthropic/claude-sonnet-5 \
    --include-task-name "$id" \
    --n-concurrent 1
done < bench/smoke_ids.txt
```

## Provider benchmark

`run.py` measures Symphony's `core_ai` providers against openai-python,
anthropic-python, google-genai, LiteLLM and, optionally, the Vercel AI SDK. It
benchmarks whichever `core_ai` is importable, so check out another revision to
compare. Nothing in the repo is modified.

```sh
uv sync --all-packages
uv pip install -r bench/requirements.txt
uv run --no-sync python bench/run.py --mock --quick     # ~2 min, no network, no keys
uv run --no-sync python bench/run.py --mock --with-node # full mock matrix; `npm install` in bench/node first
OPENAI_API_KEY=... uv run --no-sync python bench/run.py --live --model gpt-4o-mini --budget-usd 0.05
```

- **Mock.** `mock_server.py` replays the streams in `fixtures.py` (OpenAI,
  Anthropic and Gemini SSE: 2,000 text deltas, a 150-chunk tool call and usage)
  over HTTP and TLS. The TLS certificate is generated into a temp dir for each
  run. Each client runs in its own process (`mock_worker.py`), which reports
  TTFE, total time, events/s, CPU per 1k tokens, 10 and 100 concurrent streams,
  peak RSS and new TCP connections counted by the server. `rttproxy.py` adds
  emulated round-trip time and `coldstart.py` measures imports.
- **Live.** `live.py` uses the OpenAI Responses API only. It reads
  `OPENAI_API_KEY` from the environment, never prints or stores it, and skips
  live mode when it is unset. Before every request it checks the worst-case
  cost against `--budget-usd` and stops instead of going over.
- **Output.** `bench/results/<UTC timestamp>/` (or `--out DIR`) gets
  `results.json`, `report.md` and `report.png`. `bench/results/` is ignored by git.

`core_ai/tests/test_bench_smoke.py` runs the Symphony clients against the
fixture streams in CI.
