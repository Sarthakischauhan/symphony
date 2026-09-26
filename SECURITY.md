# Security policy

## Reporting a vulnerability

Please do not open a public GitHub issue for security problems.

Report vulnerabilities privately by email to **sarthakchauhann@gmail.com** with
the subject line `[symphony security]`. Include:

- the package and version (`symphony-core`, `symphony-harness`, `symphony-code`,
  `core-server`, or a git commit on `main`)
- a description of the issue and its impact
- steps or a minimal script to reproduce it
- any suggested fix, if you have one

You should receive an acknowledgement within a few days. Once the report is
confirmed, a fix is prepared on a private branch, released, and the issue is
disclosed in the release notes. Please give us a reasonable window to ship a
fix before publishing details.

If GitHub private vulnerability reporting is enabled for this repository, the
**Security → Report a vulnerability** form is an equivalent channel.

## Supported versions

The project is pre-1.0 (`0.1.x`). Only the latest release on PyPI and the
`main` branch receive fixes.

## Scope and what to expect

Symphony runs language-model output against real tools. Be aware of the
following before deploying it:

- `symphony-code` executes shell commands (`bash`), reads and writes any path
  the process can reach, and spawns child agents. The directory you launch
  from is only the default for relative paths, bash cwd, and `.symphony`
  state. Absolute and `~` paths are allowed. Approval prompts gate `bash`,
  file overwrites, and broad patches, but there is **no sandbox, path jail,
  or container isolation**: the agent runs with your user's permissions on
  your machine. Treat it like any other tool that runs code on your behalf.
- Local plugin addon Python is never executed unless the plugin is enabled
  and its directory is below an explicitly configured `authorized_roots`
  entry; authorized addon code runs with the agent user's permissions and
  must be treated as trusted code.
- Approval is a `before_tool` add-on in `symphony-code` (`ApprovalAddon`),
  not a harness method; a bare `CoreHarness` allows every tool. `approvals.deny` patterns in `~/.symphony/config.json`
  are checked first and block a call in every mode, including `always_allow`;
  `approvals.allow` patterns skip the prompt. Child agents share the same
  filesystem and skip `ApprovalAddon` (except its deny rules in unattended
  runs, below). `spawn_agent`
  starts background work by default in `symphony-code`; a returned child ID
  acknowledges startup, not completion. The runtime delivers results
  automatically and waits before final completion. Closing a child
  transcript does not stop it; use Ctrl+X in that view to cancel that child.
  Cancelling the parent run, hitting its limits, or exiting the TUI stops its
  managed children. Background execution does not add filesystem isolation.
- Provider API keys are read from the environment, a working-directory `.env`,
  or `~/.symphony/.env`. Subscription tokens from `/provider` live in
  `~/.symphony/oauth/` with mode `0600`. Keep those files out of version
  control.
- `core-server` denies browser origins by default and enforces request-size
  limits, but it has no authentication of its own. Put it behind your own
  auth layer before exposing it.
- `symphony bench` is non-interactive: approvals are `always_allow`, there is
  no TUI, and credentials must already be in the environment. Isolation is
  whatever container you run it in (the `symphony-bench` image mounts the
  workspace at `/testbed`); the CLI itself is not a sandbox.

### Unattended runs

`symphony --unattended` has no human in the loop. Treat it as handing the
agent your shell:

- `bash` runs with full filesystem access and every approval prompt is
  auto-approved (the approval mode is forced to `always_allow` for the run).
- `approvals.deny` fnmatch patterns (on the bash command, or on the path for
  `write_file`/`patch`/`generate_image`, normalized against the workspace so
  `../` and symlinks resolve first) are the **only** gate. They are loaded
  from the config file, so they survive restarts, and they also apply to
  spawned children through a deny-only fork of `ApprovalAddon`. Patterns match
  the literal command text; a determined model can phrase around them
  (`sh -c`, variables, scripts), so deny rules reduce accidents, they do not
  contain an adversary.
- `ask_user` never waits: it answers "no human available; pick the safest
  reasonable option and continue". Plan mode cannot be entered.
- Every decision a human would have made is emitted as an `auto_decision`
  event and journaled in the session JSONL. That is the audit trail.
- Background `bash` jobs (`background: true`) run in their own process group
  and are killed when the run is cancelled or fails. If `symphony` itself is
  SIGKILLed they keep running until `symphony --resume --continue` kills the
  recorded groups, or you do.
- `symphony run` refuses to start without `--unattended`. `symphony --resume
  --continue` always continues **unattended**, even when the interrupted session
  was an interactive one. `run --detach` leaves a process in its own session
  with no controlling terminal; stop it with `kill <pid>` (pid in
  `~/.symphony/sessions/<sid>.run.json`).
- This is **not a sandbox**. Run unattended work in a container or VM if the
  workspace or machine matters.

Plan mode is a gated planning phase, not a sandbox: `bash` is allowed and shell
writes are not scanned. Its tool gate blocks `write_file` and `patch` except for
the active plan file, and blocks `generate_image` and `spawn_agent`. Memory files
at `.symphony/memory/MEMORY.md` and `USER.md` are model-authored, sanitized on
write, and injected into the system prompt as untrusted data; do not treat them
as policy or executable instructions.

Reports about the trust model itself (for example, ways to bypass approval
prompts) are in scope and welcome.

Jev evaluates completed runs only. It does not deny tool calls or change the
approval policy. A session rule set with `/jev <rule>` may trigger one extra
agent run to revise work after a confident rule violation; normal approval
prompts still apply to that run.
