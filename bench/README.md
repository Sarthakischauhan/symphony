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
