// Dev-only API mock for reviewing the UI (`npx vite` then open /demo/).
// Not part of the production bundle: vite builds only ../index.html.
const now = Date.now();
const iso = (hoursAgo: number) => new Date(now - hoursAgo * 3600e3).toISOString();
const sessions = [
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
  events: [],
  children: [],
};

const info = { path: "/Users/you/code/symphony", display: "~/code/symphony", name: "symphony", branch: "feat/symphony-web" };
const models = {
  defaultProviderId: "openai",
  default: "openai:gpt-6.1",
  providers: [
    { id: "openai", label: "openai", defaultModel: "openai:gpt-6.1", models: [
      { id: "openai:gpt-6.1", label: "gpt-6.1", description: "400k context", thinkingLevels: ["low", "medium", "high", "xhigh"] },
      { id: "openai:gpt-6.1-mini", label: "gpt-6.1-mini", description: "400k context", thinkingLevels: ["low", "medium", "high"] },
    ] },
    { id: "anthropic", label: "anthropic", defaultModel: "anthropic:claude-opus-5-5", models: [
      { id: "anthropic:claude-opus-5-5", label: "claude-opus-5-5", description: "1000k context", thinkingLevels: ["low", "medium", "high", "max"] },
      { id: "anthropic:claude-sonnet-5-5", label: "claude-sonnet-5-5", description: "1000k context" },
    ] },
  ],
};
const sessionModels: Record<string, string> = {};
type Listener = (frame: any, id: number) => void;
const streams: Record<string, { frames: any[]; listeners: Set<Listener> }> = {};
const stream = (id: string) =>
  (streams[id] ??= { frames: [{ type: "ready", model: sessionModels[id] || models.default }], listeners: new Set() });
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
  emit(id, ev("tool_execution_started", { tool_call_id: "t1", tool_name: "read_file", arguments: { path: "src/client.ts" } }));
  await step(500);
  emit(id, ev("tool_execution_completed", { tool_call_id: "t1", status: "success", output: "export async function request(url: string) {\n  return fetch(url);\n}\n" }));
  emit(id, ev("tool_execution_started", { tool_call_id: "t2", tool_name: "patch", arguments: { path: "src/client.ts", old_str: "  return fetch(url);\n", new_str: "  return withRetry(() => fetch(url), { attempts: 3 });\n" } }));
  await step(400);
  emit(id, ev("tool_execution_completed", { tool_call_id: "t2", status: "success", output: "Patched src/client.ts" }));
  emit(id, ev("usage", { prompt_tokens: 4200, completion_tokens: 310, cumulative_tokens: 4510 }));
  emit(id, ev("context", { tokens_used: 4200, context_limit: 200000 }));
  emit(id, ev("question_asked", {}));
  emit(id, { type: "input_requested", request_id: "q1", question: "Overwrite src/retry.ts? It already exists.", choices: ["Allow once", "Always allow in this session", "Deny"] });
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
const owned = new Set<string>();
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
      ...(id === "hist" ? history : { messages: [], events: [], children: [] }),
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
