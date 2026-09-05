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

- `symphony-code` executes shell commands (`bash`), writes files, and spawns
  child agents inside the workspace you point it at. Approval prompts gate
  `bash`, file overwrites, and broad patches, but there is **no sandbox or
  container isolation**: the agent runs with your user's permissions on your
  machine. Treat it like any other tool that runs code on your behalf.
- Workspace tools reject paths that resolve outside the workspace root, but
  `bash` itself is not confined to that root.
- Provider API keys are read from the environment, a workspace `.env`, or
  `~/.symphony/.env`. Keep those files out of version control.
- `core-server` denies browser origins by default and enforces request-size
  limits, but it has no authentication of its own. Put it behind your own
  auth layer before exposing it.

Reports about the trust model itself (for example, ways to bypass approval
prompts or escape the workspace via a tool) are in scope and welcome.
