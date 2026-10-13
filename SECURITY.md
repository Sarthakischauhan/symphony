# Security policy

## Report a vulnerability

Do not open a public issue for a security problem. Email **sarthakchauhann@gmail.com** with the subject `[symphony security]`. Include the affected package (`symphony-core`, `symphony-harness`, `symphony-code`, `core-server`, or a commit on `main`), impact, reproduction steps, and (if available) a suggested fix. You should receive an acknowledgement within a few days. Please allow time for a fix before disclosing details. If GitHub private vulnerability reporting is enabled, the repository's **Security → Report a vulnerability** form is also appropriate.

## Supported versions

Symphony is pre-1.0 and its packages are not currently published on PyPI. Security fixes are made against the `main` branch. When releases are published, this policy will identify the supported release versions here.

## Important deployment boundaries

Symphony runs model-directed actions using the permissions of the process running it. **It is not a sandbox.**

- `symphony-code` can read and write paths accessible to your user, run shell commands, and start child agents. The workspace is a default working directory, not a filesystem jail; absolute and home-relative paths are allowed.
- Approval prompts are a product-level review mechanism, not isolation. A bare `CoreHarness` has no approval policy. Plugins execute Python code with your permissions when explicitly enabled and authorized.
- Unattended runs automatically approve actions (subject to configured deny rules), cannot ask a person for input, and do not provide containment. Use a disposable container or VM if the workspace or host matters. Deny patterns reduce accidental actions; they are not a defense against a determined model.
- `core-server` has no built-in authentication. Do not expose it to an untrusted network without adding and configuring an authentication boundary.
- Provider credentials may be read from the process environment and `.env` files. Subscription tokens are stored under `~/.symphony/oauth/` with restrictive file permissions. Keep credentials out of version control and prompts.
- Session archives include conversation transcripts, tool results, images, and related run data. Treat them as private data; see [Sessions](docs/user-guide/sessions.md).
- Browser agent prompts may be included in event streams and traces. Never put credentials in a browser task. Password-like page fields are masked, but this does not make arbitrary website content trustworthy.

See the [configuration guide](docs/user-guide/configuration.md) and [CLI reference](docs/reference/cli.md#symphony-run-headless-coding-run) for product behavior. Reports about ways to bypass trust controls are in scope and welcome.
