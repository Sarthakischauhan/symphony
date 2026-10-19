// Dev-only API mock for reviewing the UI (`npx vite` then open /demo/).
// Not part of the production bundle: vite builds only ../index.html.
const now = Date.now();
const iso = (hoursAgo: number) => new Date(now - hoursAgo * 3600e3).toISOString();
const sessions = [
  ["long", "Run the full test suite and summarize failures", 0.5, 4, false],
  ["ask", "Push the shutdown fix", 0.7, 4, false],
  ["hist", "Improve session recovery after a disconnect", 1, 14, false],
  ["tui", "Review the tool approval policy", 0.2, 22, true],
  ["s3", "Add retry handling to the API client", 5, 9, false],
  ["s4", "Explore the persistence architecture", 30, 31, false],
  ["s5", "Fix flaky checkpoint test on Windows", 70, 6, false],
  ["s6", "Document the stdio protocol v2 frames", 400, 18, false],
].map(([session_id, first_message, hours, message_count, active]) => ({
  session_id,
  first_message,
  updated_at: iso(hours as number),
  message_count,
  active,
  owned: false,
})) as any[];

const call = (id: string, name: string, args: object) => ({
  id,
  type: "function",
  function: { name, arguments: JSON.stringify(args) },
});
const history = {
  messages: [
    { role: "system", content: "…" },
    { role: "user", content: "Improve session recovery after a disconnect" },
    {
      role: "assistant",
      content: "I'll trace how the client resumes its event stream first.",
      tool_calls: [
        call("r1", "read_file", { path: "src/session.ts" }),
        call("g1", "search", { query: "lastEventId" }),
      ],
    },
    {
      role: "tool",
      tool_call_id: "r1",
      content:
        "export function connect(id: string) {\n  const cursor = 0;\n  return new EventSource(`/events/${id}?after=${cursor}`);\n}\n",
    },
    {
      role: "tool",
      tool_call_id: "g1",
      content:
        "2 content matches\nsrc/server.py:88:        cursor = int(self.headers.get(\"Last-Event-ID\") or 0)\nsrc/session.ts:3:  return new EventSource(`/events/${id}?after=${cursor}`);",
    },
    {
      role: "assistant",
      content: "",
      tool_calls: [
        call("p1", "patch", {
          path: "src/session.ts",
          old_str: "  const cursor = 0;\n",
          new_str: "  const cursor = lastEventId(id);\n",
        }),
        call("b1", "bash", { command: "npm test -- session" }),
      ],
    },
    { role: "tool", tool_call_id: "p1", content: "Patched src/session.ts" },
    {
      role: "tool",
      tool_call_id: "b1",
      content: "PASS  src/session.test.ts (4 tests)\nTests: 4 passed, 4 total",
    },
    {
      role: "assistant",
      content:
        "The client now resumes from its **last event id**, so a refresh keeps the conversation in order.\n\n- `connect()` reads the stored cursor\n- the server replays everything after it\n- duplicate ids are ignored\n\n```ts\nconst cursor = lastEventId(id);\n```\n\nThe session tests pass.",
    },
  ],
  events: [
    [
      "tool_execution_completed",
      {
        tool_call_id: "r1",
        tool_name: "read_file",
        status: "success",
        duration_ms: 18,
        summary: { lines: 4, matches: null, added: null, removed: null },
      },
    ],
    [
      "tool_execution_completed",
      {
        tool_call_id: "g1",
        tool_name: "search",
        status: "success",
        duration_ms: 40,
        summary: { lines: null, matches: 2, added: null, removed: null },
      },
    ],
    [
      "tool_execution_completed",
      {
        tool_call_id: "p1",
        tool_name: "patch",
        status: "success",
        result: "Patched src/session.ts",
        duration_ms: 26,
        summary: { lines: null, matches: null, added: 1, removed: 1 },
      },
    ],
    [
      "tool_execution_completed",
      {
        tool_call_id: "b1",
        tool_name: "bash",
        status: "success",
        result: "PASS  src/session.test.ts (4 tests)\nTests: 4 passed, 4 total",
        duration_ms: 1400,
        exit_code: 0,
        summary: { lines: 2, matches: null, added: null, removed: null },
      },
    ],
  ],
  children: [],
};


const longHistory = {
  messages: [
    { role: "system", content: "…" },
    { role: "user", content: "Here is the pytest output:\n\n/Users/sarthak/personal/symphony/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead. from starlette.testclient import TestClient as TestClient # noqa\n\ncoding_agent/tests/test_tui.py::test_dropped_image_becomes_clickable_chip\ncoding_agent/tests/test_tui.py::test_generate_image_tool_chip_opens_modal\n/Users/sarthak/personal/symphony/.venv/lib/python3.11/site-packages/textual_image/_pixeldata.py:141: DeprecationWarning: Image.Image.getdata is deprecated and will be removed in Pillow 14 (2027-10-15). Use get_flattened_data instead. data = self._image.getdata()\n\n-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html\n=========================================================================================== short test summary info ===========================================================================================\nFAILED coding_agent/tests/test_web.py::test_workspace_info_models_and_commands_come_from_the_worker_protocol_over_stdio_frames\nFAILED coding_agent/tests/test_web.py::test_browser_refresh_streaming_and_approval\n====== 2 failed, 1135 passed, 4 skipped, 7 warnings in 146.59s (0:02:26) ======\n\n```\n$ uv run --no-sync pytest coding_agent/tests/test_web.py -k test_workspace_info_models_and_commands_come_from_the_worker_protocol_over_stdio_frames --maxfail=1 -q --tb=long\n```\n\n======= Full log: /Users/sarthak/.symphony/sessions/jobs/faabce59-0d1c-4f3e-9a7e-1b2c3d4e5f60/output.log" },
    { role: "assistant", content: "Two web tests failed; both come from the worker protocol path." },
  ],
  events: [["context", { tokens_used: 61200, context_limit: 200000 }]],
  children: [],
};
const askHistory = {
  messages: [
    { role: "system", content: "…" },
    { role: "user", content: "Push the shutdown fix" },
    {
      role: "assistant",
      content: "The hook blocked the push, so I asked before bypassing it.",
      tool_calls: [
        call("ask1", "ask_user", {
          question: "The commit hook blocked the push: 1,135 tests passed, but two failed (model default mismatch and missing Playwright browser). Should I bypass the hook and push these changes?",
          choices: ["Bypass the hook and push", "Stop without pushing"],
          default: "Bypass the hook and push",
          activity: { verb: "Asking", reason: "Get approval to bypass failed repository checks", group: "push" },
        }),
      ],
    },
    { role: "tool", tool_call_id: "ask1", content: "Bypass the hook and push" },
    { role: "assistant", content: "Pushed with the hook bypassed." },
  ],
  events: [
    ["tool_execution_completed", { tool_call_id: "ask1", tool_name: "ask_user", status: "success", result: "Bypass the hook and push", duration_ms: 9100, summary: { lines: null, matches: null, added: null, removed: null } }],
    ["context", { tokens_used: 152000, context_limit: 200000 }],
  ],
  children: [],
};
const histories: Record<string, object> = { long: longHistory, ask: askHistory };

const info = { path: "/Users/you/code/symphony", display: "~/code/symphony", name: "symphony", branch: "feat/symphony-web" };
// ?reg=before mirrors the old host ("Nk context" descriptions); otherwise contextWindow.
const shotParams = new URLSearchParams(location.search);
const before = shotParams.get("reg") === "before";
const m = (id: string, label: string, limit: number, thinkingLevels?: string[]) => ({
  id, label, ...(before ? { description: `${limit / 1000}k context` } : { contextWindow: limit }),
  ...(thinkingLevels ? { thinkingLevels } : {}),
});
const models = {
  defaultProviderId: "openai",
  default: "openai:gpt-6.1",
  providers: [
    { id: "openai", label: "openai", defaultModel: "openai:gpt-6.1", models: [
      m("openai:gpt-6.1", "gpt-6.1", 400000, ["low", "medium", "high", "xhigh"]),
      m("openai:gpt-6.1-mini", "gpt-6.1-mini", 400000, ["low", "medium", "high"]),
    ] },
    { id: "anthropic", label: "anthropic", defaultModel: "anthropic:claude-opus-5-5", models: [
      m("anthropic:claude-opus-5-5", "claude-opus-5-5", 1000000, ["low", "medium", "high", "max"]),
      m("anthropic:claude-sonnet-5-5", "claude-sonnet-5-5", 1000000),
    ] },
    { id: "gemini", label: "gemini", defaultModel: "gemini:gemini-3-pro", models: [
      m("gemini:gemini-3-pro", "gemini-3-pro", 1048576, ["low", "high"]),
    ] },
    { id: "grok", label: "grok", defaultModel: "grok:grok-5", models: [m("grok:grok-5", "grok-5", 2000000)] },
    { id: "local", label: "local", defaultModel: "local:qwen3-coder", models: [{ id: "local:qwen3-coder", label: "qwen3-coder" }] },
  ],
};
// ?ctx=<tokens>&limit=<window> sets the live context frame for header shots.
const ctxUsed = Number(shotParams.get("ctx") || 61200);
const ctxLimit = Number(shotParams.get("limit") || 200000);
const sessionModels: Record<string, string> = {};
type Listener = (frame: any, id: number) => void;
const streams: Record<string, { frames: any[]; listeners: Set<Listener> }> = {};
const stream = (id: string) =>
  (streams[id] ??= { frames: [{ type: "ready", model: sessionModels[id] || models.default }, ev("usage", { prompt_tokens: 71300, completion_tokens: 20900, reasoning_tokens: 8400, total_tokens: 92200, cumulative_tokens: 184400 }), ev("context", { tokens_used: ctxUsed, context_limit: ctxLimit })], listeners: new Set() });
const emit = (id: string, frame: any) => {
  const s = stream(id);
  s.frames.push(frame);
  s.listeners.forEach((l) => l(frame, s.frames.length));
};
const ev = (event: string, payload: object) => ({ type: "event", event, payload });
let waiting: (() => void) | null = null;
async function play(id: string, prompt: string) {
  const step = (ms: number) => new Promise((r) => setTimeout(r, ms));
  emit(id, { type: "user", text: prompt });
  emit(id, ev("run_started", {}));
  for (const delta of ["Looking at how ", "the retry policy is wired ", "before changing it."]) {
    await step(250);
    emit(id, ev("reasoning_delta", { delta }));
  }
  await step(300);
  emit(id, ev("tool_execution_started", { tool_call_id: "t1", tool_name: "read_file", arguments: { path: "src/client.ts" }, started_at: new Date().toISOString() }));
  await step(500);
  emit(id, ev("tool_execution_completed", { tool_call_id: "t1", status: "success", output: "export async function request(url: string) {\n  return fetch(url);\n}\n", duration_ms: 22, summary: { lines: 3, matches: null, added: null, removed: null } }));
  emit(id, ev("tool_execution_started", { tool_call_id: "sh", tool_name: "bash", arguments: { command: "npm test -- client" }, started_at: new Date().toISOString() }));
  await step(200);
  emit(id, ev("tool_execution_output", { tool_call_id: "sh", delta: "FAIL src/client.test.ts\n", stream: "stdout" }));
  emit(id, ev("tool_execution_output", { tool_call_id: "sh", delta: "Error: fetch is not defined\n", stream: "stderr" }));
  await step(300);
  emit(id, ev("tool_execution_completed", { tool_call_id: "sh", tool_name: "bash", status: "error", result: "exit=1\nError: fetch is not defined", duration_ms: 860, exit_code: 1, summary: { lines: 2, matches: null, added: null, removed: null } }));
  emit(id, ev("tool_execution_started", { tool_call_id: "t2", tool_name: "patch", arguments: { path: "src/client.ts", old_str: "  return fetch(url);\n", new_str: "  return withRetry(() => fetch(url), { attempts: 3 });\n" } }));
  await step(400);
  emit(id, ev("tool_execution_completed", { tool_call_id: "t2", status: "success", output: "Patched src/client.ts", duration_ms: 14, summary: { lines: null, matches: null, added: 1, removed: 1 } }));
  emit(id, ev("usage", { prompt_tokens: 4200, completion_tokens: 310, cumulative_tokens: 4510 }));
  emit(id, ev("context", { tokens_used: 4200, context_limit: 200000 }));
  emit(id, ev("question_asked", {}));
  emit(id, { type: "input_requested", request_id: "q1", kind: "approval", question: "Overwrite src/retry.ts? It already exists.", detail: "It already exists and will be overwritten.", target: "src/retry.ts", bytes: 248, choices: ["Deny", "Always allow", "Allow once"], default: "Allow once" });
  await new Promise<void>((resolve) => (waiting = resolve));
  emit(id, { type: "answered", request_id: "q1" });
  emit(id, ev("tool_execution_started", { tool_call_id: "w1", tool_name: "write_file", arguments: { path: "src/retry.ts", content: "export async function withRetry<T>(fn: () => Promise<T>, { attempts = 3 } = {}) {\n  for (let i = 1; ; i++) {\n    try { return await fn(); } catch (e) { if (i >= attempts) throw e; }\n  }\n}\n" } }));
  await step(300);
  emit(id, ev("tool_execution_completed", { tool_call_id: "w1", status: "success" }));
  emit(id, ev("agent_spawned", { child_id: "c1", label: "Test writer", prompt: "Cover withRetry with unit tests" }));
  await step(900);
  emit(id, ev("agent_completed", { child_id: "c1", label: "Test writer", output_text: "Added 3 tests for withRetry; all pass." }));
  for (const delta of ["Requests now retry up to **three times** ", "through `withRetry`, and a subagent added tests for it."]) {
    await step(200);
    emit(id, ev("text_delta", { delta }));
  }
  emit(id, ev("usage", { prompt_tokens: 6100, completion_tokens: 420, cumulative_tokens: 11030 }));
  emit(id, ev("run_completed", { duration_ms: 18400 }));
  emit(id, { type: "done", status: "completed" });
}

const json = (data: any, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const owned = new Set<string>(new URLSearchParams(location.search).getAll("own"));
const realFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = new URL(String(input), location.href);
  if (!url.pathname.startsWith("/api/")) return realFetch(input, init);
  const parts = url.pathname.split("/").filter(Boolean);
  const body = init?.body ? JSON.parse(String(init.body)) : {};
  if (url.pathname === "/api/info") return json(info);
  if (url.pathname === "/api/models") return json(models);
  if (url.pathname === "/api/sessions" && init?.method === "POST") {
    const id = `live-${Date.now()}`;
    if (body.model) sessionModels[id] = body.model;
    owned.add(id);
    sessions.unshift({ session_id: id, first_message: "", updated_at: new Date().toISOString(), message_count: 0, active: true, owned: true });
    return json({ session_id: id });
  }
  if (url.pathname === "/api/sessions")
    return json(sessions.map((s) => ({ ...s, owned: owned.has(s.session_id), active: s.active || owned.has(s.session_id) })));
  const [, , id, action] = parts;
  if (action === "resume") {
    if (body.model && body.model !== (sessionModels[id] || models.default)) {
      sessionModels[id] = body.model;
      delete streams[id];
    }
    owned.add(id);
    return json({ session_id: id });
  }
  if (action === "prompt") {
    const s = sessions.find((x) => x.session_id === id);
    if (s && !s.first_message) s.first_message = body.prompt;
    void play(id, body.prompt);
    return json({ ok: true });
  }
  if (action === "answer") {
    waiting?.();
    return json({ ok: true });
  }
  if (action === "cancel") return json({ ok: true });
  if (!action)
    return json({
      ...(id === "hist" ? history : histories[id] ?? { messages: [], events: [], children: [] }),
      owned: owned.has(id),
      model: owned.has(id) ? sessionModels[id] || models.default : "",
    });
  return json({ error: "Not found" }, 404);
};

class MockEventSource {
  onopen: (() => void) | null = null;
  onmessage: ((e: { lastEventId: string; data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  private listener: Listener;
  private id: string;
  constructor(url: string) {
    this.id = new URL(url, location.href).pathname.split("/")[3];
    const s = stream(this.id);
    this.listener = (frame, seq) => this.onmessage?.({ lastEventId: String(seq), data: JSON.stringify(frame) });
    setTimeout(() => {
      this.onopen?.();
      s.frames.forEach((frame, i) => this.listener(frame, i + 1));
      s.listeners.add(this.listener);
    });
  }
  close() {
    stream(this.id).listeners.delete(this.listener);
  }
}
(window as any).EventSource = MockEventSource;
