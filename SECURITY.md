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
  not a harness method. Unattended `CoreHarness` runs allow tools. Child
  agents share the same filesystem and skip `ApprovalAddon`. `spawn_agent`
  starts background work by default in `symphony-code`; a returned child ID
  acknowledges startup, not completion. The runtime delivers results
  automatically and waits before final completion. Closing a child
  transcript does not stop it; use Ctrl+X in that view to cancel that child.
  Cancelling the parent run, hitting its limits, or exiting the TUI stops its
  managed children. Background execution does not add filesystem isolation.
- Provider API keys are read from the environment, a working-directory `.env`,
  or `~/.symphony/.env`. Keep those files out of version control.
- `core-server` denies browser origins by default and enforces request-size
  limits, but it has no authentication of its own. Put it behind your own
  auth layer before exposing it.

Plan mode is a gated planning phase, not a sandbox: `bash` is allowed and shell
writes are not scanned. Its tool gate blocks `write_file` and `patch` except for
the active plan file, and blocks `generate_image` and `spawn_agent`. Memory files
at `.symphony/memory/MEMORY.md` and `USER.md` are model-authored, sanitized on
write, and injected into the system prompt as untrusted data; do not treat them
as policy or executable instructions.

Reports about the trust model itself (for example, ways to bypass approval
prompts) are in scope and welcome.
