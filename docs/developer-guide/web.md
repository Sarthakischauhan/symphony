# Symphony Web

From a source checkout or an installed `symphony-code` wheel:

```sh
symphony web --workspace /path/to/project
symphony web --workspace /path/to/project --model local:my-model --port 8765
```

The command starts a Python standard-library HTTP server on `127.0.0.1`, chooses
an available port by default, and opens the system browser. `--no-browser` prints
the launch URL instead. Keep that URL private: its fragment is a per-launch
capability. The frontend saves it in tab-scoped session storage and removes it
from the address bar. End users need Python and their existing provider setup;
Node.js is only required to develop or rebuild the frontend.
`SYMPHONY_HOME` can relocate configuration, sessions and ownership records when
the default user home is read-only.

Type a task into the composer to start a session; the first prompt creates it.
**New session** returns to that empty composer. Select a historical TUI session
in the sidebar to read it, then choose **Resume session** or simply send a prompt,
which resumes the session first. Web uses the same `JsonlPersistence` transcript,
context, and checkpoint APIs and the same TUI session directory. Prompts execute
through the existing stdio protocol, `CodingAgent`, and `CoreHarness`. Existing
provider configuration, tools, approval policy, and deny rules apply. Questions
and approvals block until answered; cancellation uses the harness interrupt API.
The existing TUI UI and run loop are unchanged.

Each Web session has one worker process. Its lifetime session lock is shared
with TUI/headless registration, and the live registry also detects older running
TUI processes. A session owned elsewhere is readable but cannot be resumed.
Two browser tabs connect to the same worker; overlapping prompts return HTTP 409.
A browser refresh does not stop execution. Closing the server stops its workers;
restart Web and resume the persisted session to continue with a new prompt.
An interrupted turn is never silently rerun. Do not run older Symphony versions
that lack lifetime locks against the same session storage concurrently.

## Transport and security

Commands are JSON POST requests to `/api/sessions` (new) or
`/api/sessions/{id}/{resume,prompt,cancel,answer}`. Reads expose the session list,
historical messages/events/children, `/api/sessions/{id}/events` SSE, the
workspace path and git branch (`/api/info`), and the model catalog
(`/api/models`).

The composer's model picker lists the providers you have configured. A short-lived
worker process builds the catalog once per server, so provider credentials stay out
of the server process. Creating or resuming a session accepts an optional `model`;
picking a different model for an idle live session restarts its worker on that
model, and the persisted transcript carries over. Switching while a task runs
returns HTTP 409. A prompt may carry a `reasoning_effort` from the picker's
reasoning levels.
The SSE envelope has an increasing integer `id` and the existing stdio JSON frame
as `data`. `Last-Event-ID` replays missed frames. The frontend rejects gaps and
ignores duplicates. Its initial snapshot plus replay reconstructs pending
approvals and in-flight text after refresh. Replay is retained in server memory
for each worker's lifetime; restarting the server restores durable transcripts,
not token deltas. Reopen a session after worker recovery to start a fresh cursor.

The service has no remote-bind option. It checks exact Host, same-origin Origin
and Fetch Metadata, and a random capability on every API read/write. Mutations
require JSON. No CORS access is granted. Responses set CSP, no-referrer and
nosniff headers; URLs are not logged. Artifact downloads are restricted to files
observed in successful `write_file` events inside the selected workspace and
served as attachments. HTML and SVG are not embedded as active documents.
This protects against untrusted websites, not local processes or malicious
browser extensions that can read your launch capability. Agent tools run with
your user permissions; the browser UI does not add a filesystem sandbox.

## Frontend and wheel pipeline

`coding_agent/web-ui` is a React/Vite application. All chat UI comes from
`@sarchauhan/chat` (the `feat/tool-widgets-direction-b` build, which is ahead of
the published `0.0.1`): the composer (`ChatComposer` inside
`ChatContextProvider`), message rendering (`MessageContent`, `MessageUsage`),
`LoadingState`, the model picker, and the read, patch, search, terminal,
artifact, and subagent widgets. The session sidebar is the shadcn/ui `Sidebar`
(`src/components/ui`, Tailwind CSS v4 without preflight so the SDK keeps its
browser defaults). `src/style.css` maps both shadcn variables and `--chat-*`
tokens onto one dark theme.

Symphony-specific glue stays in this app, not the SDK. `src/events.ts`
translates stdio frames and journals into SDK message parts: write results use
the SDK `{ artifact }` tool-output envelope, search hits become search results,
and usage/context events become `data` parts. A small `ChatAdapter` in
`src/main.tsx` sends the composer's prompt (creating or resuming the session
first) and settles when that run's `done` frame arrives. The composer's stop
button interrupts the run. Prompts are text only, so the composer is mounted
with `showAttachments={false}`, `inputLabel="Coding task"` and a placeholder.

The Python host and compiled assets live in `coding_agent/src/coding_agent/web`
to fit the existing Python package layout. To review the UI without a worker or
provider, run `npx vite` in `coding_agent/web-ui` and open `/demo/`; it mocks the
local API and plays a scripted run. The demo page is not part of the build.

```sh
uv sync --locked --all-packages --dev
cd coding_agent/web-ui
npm ci
npm test
npm run build
cd ../..
uv run --no-sync pytest coding_agent/tests/test_web.py
uv run --no-sync ruff check .
uv build --package symphony-code -o dist
# After installing the workspace wheels in an isolated virtual environment:
/path/to/venv/bin/python coding_agent/tests/web_wheel_smoke.py
```

Commit both frontend sources/lockfile and generated `web/static` assets. Python
wheel builds ship these assets without invoking npm. CI rebuilds and checks for
asset drift. The wheel can be installed and used on a machine without Node.
The browser integration test uses Playwright Chromium (system `chromium` when
available, otherwise `uv run playwright install chromium`); Chromium's sandbox
must be supported on the test host.

The published Chat package currently imports six helpers missing from its
published protocol dependency. `src/protocol-compat.ts` supplies backend-neutral
artifact/subagent envelopes and parsers plus usage/context parsers via a Vite
alias, re-exporting the installed protocol. The explicit protocol override and
lockfile make this reproducible. Remove this bridge when a compatible SDK is
published; do not patch `node_modules` or publish a fork as part of this feature.

HTTP/worker tests run a local OpenAI-compatible model stub through the real agent,
so no provider keys or live model requests are required. They cover history,
file-writing tasks, approvals, streaming replay, cancellation, ownership conflicts,
worker recovery and request security. The browser test covers the compiled UI,
questions, multiple turns and refresh. Live provider behavior depends on the
user's configured provider and is not exercised by these tests.

## Session navigation

The sidebar supports title/ID search, pinned sessions, active/today/recent/older
sections, message counts, and explicit TUI ownership indicators. A session that
is open in the TUI is read only here. Pinning and collapse state are saved in
this browser; they do not rewrite session journals. Preferences are scoped to the
browser origin; use a stable `--port` to retain them across separate server
launches. `Cmd/Ctrl B` toggles navigation. Below 768px wide, navigation becomes a
modal drawer with contained keyboard focus, Escape dismissal, and focus returned
to the menu button.

**Settings** at the foot of the sidebar opens a shadcn/ui `Dialog` showing the
workspace path, git branch and default model, a toggle for the token usage line
under each reply, a control to clear pinned sessions, and the keyboard
shortcuts. Like pins, these preferences live in browser storage.

## Approvals and protocol 3 fields

An `input_requested` frame with `kind: "approval"` renders as an approval
card: the `detail` (or `question`), the `target`, the write size in `bytes`,
and one button per entry in `choices`, with `default` highlighted. A click
posts `{request_id, value}` to `/api/sessions/<id>/answer`, which the host
relays as the stdio `answer` frame. Approvals are never sent as chat
messages.

Finished tool cards carry the protocol 3 facts on the tool output the SDK
widgets read: `exit_code`, `duration_ms`, `started_at` and `summary`. A bash
card is the terminal widget ("Ran"), with `tool_execution_output` chunks
split into stdout and stderr. Read, patch and search cards show the summary
counts. Subagent chunks are routed by `parent_call_id`, and `subagent_step`
adds the turn to the subagent card's title. The session journal stores these
fields, so a reloaded session (read from `session/history`) shows the same
cards. Sessions recorded before protocol 3 omit the exit code, duration and
counts instead of inventing them.

## Screenshots

These are browser captures of the `/demo/` page, which renders the real
frontend against a mocked local API, rather than live provider responses.

Welcome, with the text-only composer (no attach button):

![Symphony Web welcome with searchable sessions](https://github.com/Sarthakischauhan/symphony/blob/7e9123bf5250138cdccfeb6053c50445b4df6179/docs/assets/web/welcome-desktop.png?raw=true)

A resumed session: an edited file with its diff, and a command that passed with its exit code and duration:

![Historical session with a patch diff and a passed terminal run](https://github.com/Sarthakischauhan/symphony/blob/7e9123bf5250138cdccfeb6053c50445b4df6179/docs/assets/web/session-desktop.png?raw=true)

A live run: a failed command with stderr, the patch, and the overwrite approval:

![Failed command, patch diff, and overwrite approval](https://github.com/Sarthakischauhan/symphony/blob/7e9123bf5250138cdccfeb6053c50445b4df6179/docs/assets/web/approval-desktop.png?raw=true)
