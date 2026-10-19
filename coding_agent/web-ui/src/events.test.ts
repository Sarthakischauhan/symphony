import { describe, it, expect } from "vitest";
import {
  historical,
  initial,
  isTerminalChunk,
  isToolSummary,
  reduce,
  type State,
} from "./events";
import { parseFrame } from "./frames";
import { parseArtifact, parseSubagent, parseUsage } from "./protocol-compat";

// Frames arrive as JSON; parse them the way the SSE handler does.
const apply = (state: State, raw: unknown, id: number) => {
  const frame = parseFrame(raw);
  if (!frame) throw new Error(`unparsed frame: ${JSON.stringify(raw)}`);
  return reduce(state, frame, id);
};
const run = (frames: unknown[]) =>
  frames.reduce<State>((s, frame, i) => apply(s, frame, i + 1), initial());
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const partsOf = (s: State, row: number): any[] => s.rows[row].parts;
const event = (name: string, payload: Record<string, unknown>) => ({
  type: "event",
  event: name,
  payload,
});

describe("Symphony event adapter", () => {
  it("takes the user turn from run_started and keeps questions until a later event", () => {
    let s = run([
      event("run_started", { prompt: "task", model_id: "m" }),
      event("text_delta", { delta: "Hello " }),
      event("text_delta", { delta: "world" }),
    ]);
    expect(s.rows[0]).toMatchObject({
      role: "user",
      parts: [{ text: "task" }],
    });
    expect(partsOf(s, 1)[0].text).toBe("Hello world");
    expect(s.busy).toBe(true);
    s = apply(
      s,
      {
        type: "input_requested",
        request_id: "q",
        question: "Allow?",
        choices: ["Yes"],
      },
      4,
    );
    expect(s.pending.q.question).toBe("Allow?");
    // No answered frame exists; the next run event confirms the answer.
    s = apply(
      s,
      event("tool_execution_started", { tool_call_id: "t", tool_name: "bash" }),
      5,
    );
    expect(s.pending).toEqual({});
    expect(apply(s, { type: "done", status: "completed" }, 6).busy).toBe(false);
  });
  it("ignores frames this client does not render", () => {
    expect(parseFrame({ type: "user", text: "made up" })).toBeNull();
    expect(parseFrame({ type: "answered", request_id: "q" })).toBeNull();
    expect(parseFrame(event("run_completed", {}))).toBeNull();
    expect(
      parseFrame({ type: "ready", model: "m", session_id: "s" }),
    ).not.toBeNull();
  });
  it("renders tool events as they arrive, including written files", () => {
    let s = run([
      event("tool_execution_started", {
        tool_call_id: "p",
        tool_name: "patch",
        arguments: { path: "a.py", old_str: "old", new_str: "new" },
      }),
      event("tool_execution_completed", {
        tool_call_id: "p",
        tool_name: "patch",
        status: "error",
        result: "failed",
      }),
    ]);
    expect(partsOf(s, 0)[0]).toMatchObject({
      input: { before: "old", after: "new" },
      state: "output-error",
      output: "failed",
    });
    s = apply(
      s,
      event("tool_execution_started", {
        tool_call_id: "w",
        tool_name: "write_file",
        arguments: { path: "report.md", content: "# Done" },
      }),
      3,
    );
    s = apply(
      s,
      event("tool_execution_completed", {
        tool_call_id: "w",
        status: "success",
        result: "wrote report.md",
      }),
      4,
    );
    // No artifact synthesis: the write tool shows its own input and result.
    expect(partsOf(s, 0).at(-1)).toMatchObject({
      toolName: "write_file",
      input: { path: "report.md", content: "# Done" },
      output: "wrote report.md",
      state: "output-available",
    });
  });
  it("routes child text into subagent views", () => {
    const s = run([
      event("agent_spawned", {
        child_id: "child",
        label: "Research",
        prompt: "Inspect",
      }),
      event("text_delta", {
        parent_id: "parent",
        agent_id: "child",
        delta: "Child reply",
      }),
    ]);
    expect(partsOf(s, 0)[0].data.messages[0].parts[0].text).toBe("Child reply");
    expect(partsOf(s, 0).some((p) => p.type === "text")).toBe(false);
  });
  it("validates compatibility envelopes", () => {
    expect(parseArtifact(null)).toBeNull();
    expect(parseSubagent({ id: "x", title: "x", state: "bogus" })).toBeNull();
    expect(
      parseSubagent({ id: "x", title: "x", state: "running" })?.state,
    ).toBe("running");
    expect(
      parseArtifact({
        id: "a",
        filename: "a.txt",
        content: "<script>bad</script>",
      })?.content,
    ).toContain("<script>");
    expect(
      parseArtifact({ id: "a", filename: "a.txt", status: "bogus" })?.status,
    ).toBe("ready");
    expect(parseUsage({ total_tokens: 5, input_tokens: "x" })).toEqual({
      input_tokens: undefined,
      output_tokens: undefined,
      reasoning_tokens: undefined,
      total_tokens: 5,
    });
  });
  it("rebuilds history from the session_history reply", () => {
    const s = historical({
      messages: [
        { role: "system", content: "sys" },
        { role: "user", content: "Find main" },
        {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "c1",
              function: { name: "search", arguments: '{"pattern":"def main"}' },
            },
          ],
        },
        {
          role: "tool",
          tool_call_id: "c1",
          content: "1 content matches\na.py:3:def main():",
        },
        { role: "assistant", content: [{ type: "text", text: "Found it" }] },
      ],
      events: [["agent_spawned", { child_id: "k", label: "Helper" }]],
      children: [],
    });
    expect(s.rows.map((r) => r.role)).toEqual([
      "user",
      "assistant",
      "assistant",
    ]);
    expect(partsOf(s, 1).at(-1)).toMatchObject({
      toolName: "search",
      input: { pattern: "def main" },
      output: { total: 1, results: [{ path: "a.py", line: 3 }] },
    });
    expect(partsOf(s, 2)[0]).toMatchObject({ type: "text", text: "Found it" });
    expect(partsOf(s, 2).some((p) => p.name === "subagent")).toBe(true);
  });
});

it("preserves computed patch widgets after a Symphony status-string result", async () => {
  const { computeToolWidget } = await import("@sarchauhan/chat");
  const state = run([
    event("tool_execution_started", {
      tool_call_id: "patch",
      tool_name: "patch",
      arguments: {
        path: "src/session.ts",
        old_str: "const cursor = 0;",
        new_str: "const cursor = lastEventId;",
      },
    }),
    event("tool_execution_completed", {
      tool_call_id: "patch",
      tool_name: "patch",
      status: "success",
      result: "patched src/session.ts",
    }),
  ]);
  const widget = computeToolWidget(partsOf(state, 0)[0]);
  expect(widget?.name).toBe("patch");
  expect(widget?.props.diff).toContain("+const cursor = lastEventId;");
});

describe("SDK message shape", () => {
  it("streams reasoning and shows usage and context payloads as they come", () => {
    const s = run([
      event("run_started", { prompt: "Plan it" }),
      event("reasoning_delta", { delta: "Consider" }),
      event("reasoning_delta", { delta: " options" }),
      event("text_delta", { delta: "Done." }),
      event("usage", {
        prompt_tokens: 100,
        completion_tokens: 10,
        cumulative_tokens: 110,
      }),
      event("usage", {
        prompt_tokens: 200,
        completion_tokens: 20,
        cumulative_tokens: 330,
      }),
      event("context", { tokens_used: 200, context_limit: 1000 }),
      { type: "done", status: "completed" },
    ]);
    const parts = partsOf(s, 1);
    expect(parts[0]).toEqual({
      type: "reasoning",
      text: "Consider options",
      state: "done",
    });
    expect(parts[1]).toEqual({ type: "text", text: "Done.", state: "done" });
    // The latest cumulative_tokens, not a client-side sum.
    expect(parts.find((p) => p.name === "usage").data).toEqual({
      total_tokens: 330,
    });
    expect(parts.find((p) => p.name === "context").data).toEqual({
      current_tokens: 200,
      context_window: 1000,
    });
    expect(s.busy).toBe(false);
  });
});

describe("protocol 3 widget fields", () => {
  it("streams stdout and stderr, then settles a failed bash with its facts", () => {
    const s = run([
      event("run_started", { prompt: "t" }),
      event("tool_execution_started", {
        tool_call_id: "b",
        tool_name: "bash",
        arguments: { command: "pytest" },
        started_at: "2026-10-18T10:00:00Z",
      }),
      event("tool_execution_output", {
        tool_call_id: "b",
        delta: "ok\n",
        stream: "stdout",
      }),
      event("tool_execution_output", {
        tool_call_id: "b",
        delta: "E boom\n",
        stream: "stderr",
      }),
    ]);
    expect(partsOf(s, 1)[0].output.chunks).toEqual([
      { stream: "stdout", text: "ok\n" },
      { stream: "stderr", text: "E boom\n" },
    ]);
    expect(partsOf(s, 1)[0].output.startedAt).toBe("2026-10-18T10:00:00Z");
    const done = apply(
      s,
      event("tool_execution_completed", {
        tool_call_id: "b",
        tool_name: "bash",
        status: "error",
        result: "exit=1\nE boom",
        duration_ms: 1500,
        exit_code: 1,
        summary: { lines: 2, matches: null, added: null, removed: null },
      }),
      5,
    );
    expect(partsOf(done, 1)[0].errorText).toBeUndefined();
    expect(partsOf(done, 1)[0]).toMatchObject({
      state: "output-error",
      output: {
        output: "exit=1\nE boom",
        exitCode: 1,
        durationMs: 1500,
        startedAt: "2026-10-18T10:00:00Z",
        chunks: [
          { stream: "stdout", text: "ok\n" },
          { stream: "stderr", text: "E boom\n" },
        ],
        summary: { lines: 2, matches: null, added: null, removed: null },
      },
    });
  });

  it("puts summary counts on a finished patch without inventing facts", () => {
    const s = run([
      event("tool_execution_started", {
        tool_call_id: "p",
        tool_name: "patch",
        arguments: { path: "a.py", old_str: "old", new_str: "new" },
      }),
      event("tool_execution_completed", {
        tool_call_id: "p",
        tool_name: "patch",
        status: "success",
        result: "patched a.py",
        duration_ms: 10,
        summary: { lines: null, matches: null, added: 2, removed: 1 },
      }),
    ]);
    expect(partsOf(s, 0)[0].output).toMatchObject({
      message: "patched a.py",
      durationMs: 10,
      summary: { added: 2, removed: 1 },
    });
    expect(partsOf(s, 0)[0].output.exitCode).toBeUndefined();
  });

  it("routes subagent output by parent_call_id and counts subagent steps", () => {
    const s = run([
      event("run_started", { prompt: "t" }),
      event("agent_spawned", { child_id: "kid", label: "Research", tool_call_id: "s1", parent_call_id: "s1" }),
      event("tool_execution_started", {
        agent_id: "kid", parent_id: "root", tool_call_id: "c", tool_name: "bash", parent_call_id: "s1",
      }),
      event("tool_execution_output", { tool_call_id: "c", delta: "hi", parent_call_id: "s1" }),
      event("subagent_step", { agent_id: "kid", parent_id: "root", parent_call_id: "s1", turn: 2 }),
    ]);
    const card = partsOf(s, 1).find((p) => p.name === "subagent");
    expect(card.data.title).toBe("Research · step 2");
    expect(card.data.messages[0].parts[0].output.chunks).toEqual([
      { stream: "stdout", text: "hi" },
    ]);
  });

  it("reads the journaled facts back from session history", () => {
    const s = historical({
      messages: [
        { role: "user", content: "t" },
        {
          role: "assistant",
          content: "",
          tool_calls: [{ id: "b", function: { name: "bash", arguments: '{"command":"make"}' } }],
        },
        { role: "tool", tool_call_id: "b", content: "exit=2\nfail" },
      ],
      events: [
        [
          "tool_execution_completed",
          {
            tool_call_id: "b", tool_name: "bash", status: "error", result: "exit=2\nfail",
            duration_ms: 900, exit_code: 2,
            summary: { lines: 2, matches: null, added: null, removed: null },
          },
        ],
      ],
      children: [],
    });
    const bash = partsOf(s, 1).find((p) => p.type === "tool");
    expect(bash.errorText).toBeUndefined();
    expect(bash).toMatchObject({
      state: "output-error",
      output: {
        output: "exit=2\nfail",
        exitCode: 2,
        durationMs: 900,
        summary: { lines: 2 },
      },
    });
  });
});

describe("tool output guards", () => {
  it("accepts only well-formed summaries", () => {
    expect(isToolSummary({ lines: 2, matches: null, added: null, removed: null })).toBe(true);
    expect(isToolSummary({ lines: "2", matches: null, added: null, removed: null })).toBe(false);
    expect(isToolSummary({ lines: 2 })).toBe(false);
    expect(isToolSummary([1, 2])).toBe(false);
    expect(isToolSummary(null)).toBe(false);
  });

  it("accepts only stdout/stderr chunks with text", () => {
    expect(isTerminalChunk({ stream: "stdout", text: "x" })).toBe(true);
    expect(isTerminalChunk({ stream: "stderr", text: "" })).toBe(true);
    expect(isTerminalChunk({ stream: "stdin", text: "x" })).toBe(false);
    expect(isTerminalChunk({ stream: "stdout", text: 1 })).toBe(false);
    expect(isTerminalChunk("stdout")).toBe(false);
  });

  it("drops malformed live chunks and summaries when a tool settles", () => {
    const s = run([
      event("run_started", { prompt: "t" }),
      event("tool_execution_started", {
        tool_call_id: "b",
        tool_name: "bash",
        arguments: { command: "ls" },
      }),
      event("tool_execution_output", { tool_call_id: "b", delta: "ok\n", stream: "stdout" }),
    ]);
    const part = partsOf(s, 1)[0];
    part.output = {
      ...part.output,
      summary: { lines: "many" },
      chunks: [...part.output.chunks, { stream: "stdin", text: "bad" }, 7],
    };
    const done = apply(
      s,
      event("tool_execution_completed", {
        tool_call_id: "b",
        tool_name: "bash",
        status: "success",
        result: "ok",
      }),
      4,
    );
    const output = partsOf(done, 1)[0].output;
    expect(output.chunks).toEqual([{ stream: "stdout", text: "ok\n" }]);
    expect(output.summary).toBeUndefined();
  });

  it("reads the harness started_at as epoch seconds", () => {
    const s = run([
      event("run_started", { prompt: "t" }),
      event("tool_execution_started", {
        tool_call_id: "b",
        tool_name: "bash",
        arguments: { command: "ls" },
        started_at: 1792396800.5,
      }),
    ]);
    expect(partsOf(s, 1)[0].output.startedAt).toBe(
      new Date(1792396800500).toISOString(),
    );
  });
});

describe("copy-on-write frames", () => {
  it("copies only the row a frame changes and leaves the previous state intact", () => {
    const before = run([
      event("run_started", { prompt: "first" }),
      event("text_delta", { delta: "one" }),
      event("run_started", { prompt: "second" }),
      event("text_delta", { delta: "two" }),
    ]);
    const snapshot = structuredClone(before);
    const after = apply(before, event("text_delta", { delta: " more" }), 5);
    expect(before).toEqual(snapshot);
    before.rows.slice(0, 3).forEach((row, i) => expect(after.rows[i]).toBe(row));
    expect(after.rows[3]).not.toBe(before.rows[3]);
    expect(partsOf(after, 3)[0].text).toBe("two more");
  });

  it("merges consecutive output on one stream", () => {
    const out = (delta: string, stream: string) =>
      event("tool_execution_output", { tool_call_id: "b", delta, stream });
    const s = run([
      event("run_started", { prompt: "t" }),
      event("tool_execution_started", { tool_call_id: "b", tool_name: "bash" }),
      out("a\n", "stdout"),
      out("b\n", "stdout"),
      out("c\n", "stderr"),
      out("d\n", "stdout"),
    ]);
    expect(partsOf(s, 1)[0].output.chunks).toEqual([
      { stream: "stdout", text: "a\nb\n" },
      { stream: "stderr", text: "c\n" },
      { stream: "stdout", text: "d\n" },
    ]);
  });

  it("keeps journaled tool facts that follow a subagent event in history", () => {
    const s = historical({
      messages: [
        { role: "user", content: "t" },
        {
          role: "assistant",
          content: "",
          tool_calls: [{ id: "b", function: { name: "bash", arguments: '{"command":"make"}' } }],
        },
        { role: "tool", tool_call_id: "b", content: "exit=2\nfail" },
      ],
      events: [
        ["agent_spawned", { child_id: "k", label: "Helper" }],
        [
          "tool_execution_completed",
          { tool_call_id: "b", tool_name: "bash", status: "error", result: "exit=2\nfail", exit_code: 2 },
        ],
      ],
      children: [],
    });
    const bash = partsOf(s, 1).find((p) => p.type === "tool");
    expect(bash).toMatchObject({ state: "output-error", output: { exitCode: 2 } });
  });
});
