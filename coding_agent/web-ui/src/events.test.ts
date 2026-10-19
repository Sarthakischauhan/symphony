import { describe, it, expect } from "vitest";
import { initial, reduce } from "./events";
import { parseArtifact, parseSubagent } from "./protocol-compat";
describe("Symphony event adapter", () => {
  it("streams ordered deltas and correlates approvals", () => {
    let s = reduce(initial(), { type: "user", text: "task" }, 1);
    s = reduce(
      s,
      { type: "event", event: "text_delta", payload: { delta: "Hello " } },
      2,
    );
    s = reduce(
      s,
      { type: "event", event: "text_delta", payload: { delta: "world" } },
      3,
    );
    expect(s.rows[1].parts[0].text).toBe("Hello world");
    s = reduce(
      s,
      { type: "input_requested", request_id: "q", question: "Allow?" },
      4,
    );
    expect(s.pending.q.question).toBe("Allow?");
    s = reduce(s, { type: "answered", request_id: "q" }, 5);
    expect(s.pending).toEqual({});
    expect(reduce(s, { type: "done" }, 6).busy).toBe(false);
  });
  it("renders patch tool payloads and generated artifacts", () => {
    let s = reduce(
      initial(),
      {
        type: "event",
        event: "tool_execution_started",
        payload: {
          tool_call_id: "p",
          tool_name: "patch",
          arguments: { path: "a.py", old_str: "old", new_str: "new" },
        },
      },
      1,
    );
    expect(s.rows[0].parts[0].input).toMatchObject({
      before: "old",
      after: "new",
    });
    s = reduce(
      s,
      {
        type: "event",
        event: "tool_execution_completed",
        payload: {
          tool_call_id: "p",
          tool_name: "patch",
          status: "error",
          result: "failed",
        },
      },
      2,
    );
    expect(s.rows[0].parts[0]).toMatchObject({
      state: "output-error",
      output: "failed",
    });
    s = reduce(
      s,
      {
        type: "event",
        event: "tool_execution_started",
        payload: {
          tool_call_id: "w",
          tool_name: "write_file",
          arguments: { path: "report.md", content: "# Done" },
        },
      },
      3,
    );
    s = reduce(
      s,
      {
        type: "event",
        event: "tool_execution_completed",
        payload: { tool_call_id: "w", status: "success" },
      },
      4,
    );
    expect(s.rows[0].parts.at(-1).output.artifact.content).toBe("# Done");
  });
  it("routes child text into subagent views", () => {
    let s = reduce(
      initial(),
      {
        type: "event",
        event: "agent_spawned",
        payload: { child_id: "child", label: "Research", prompt: "Inspect" },
      },
      1,
    );
    s = reduce(
      s,
      {
        type: "event",
        event: "text_delta",
        payload: {
          parent_id: "parent",
          agent_id: "child",
          delta: "Child reply",
        },
      },
      2,
    );
    expect(s.rows[0].parts[0].data.messages[0].parts[0].text).toBe(
      "Child reply",
    );
    expect(s.rows[0].parts.some((p) => p.type === "text")).toBe(false);
  });
  it("validates compatibility envelopes", () => {
    expect(parseArtifact(null)).toBeNull();
    expect(parseSubagent({ id: "x", title: "x", state: "bogus" })).toBeNull();
    expect(
      parseArtifact({
        id: "a",
        filename: "a.txt",
        content: "<script>bad</script>",
      })?.content,
    ).toContain("<script>");
  });
});

it("preserves computed patch widgets after a Symphony status-string result", async () => {
  const { computeToolWidget } = await import("@sarchauhan/chat");
  let state = reduce(
    initial(),
    {
      type: "event",
      event: "tool_execution_started",
      payload: {
        tool_call_id: "patch",
        tool_name: "patch",
        arguments: {
          path: "src/session.ts",
          old_str: "const cursor = 0;",
          new_str: "const cursor = lastEventId;",
        },
      },
    },
    1,
  );
  state = reduce(
    state,
    {
      type: "event",
      event: "tool_execution_completed",
      payload: {
        tool_call_id: "patch",
        tool_name: "patch",
        status: "success",
        result: "patched src/session.ts",
      },
    },
    2,
  );
  const widget = computeToolWidget(state.rows[0].parts[0]);
  expect(widget?.name).toBe("patch");
  expect(widget?.props.diff).toContain("+const cursor = lastEventId;");
});

describe("SDK message shape", () => {
  it("streams reasoning, settles it, and meters usage and context", () => {
    const frames = [
      { type: "user", text: "Plan it" },
      {
        type: "event",
        event: "reasoning_delta",
        payload: { delta: "Consider" },
      },
      {
        type: "event",
        event: "reasoning_delta",
        payload: { delta: " options" },
      },
      { type: "event", event: "text_delta", payload: { delta: "Done." } },
      {
        type: "event",
        event: "usage",
        payload: {
          prompt_tokens: 100,
          completion_tokens: 10,
          cumulative_tokens: 110,
        },
      },
      {
        type: "event",
        event: "usage",
        payload: {
          prompt_tokens: 200,
          completion_tokens: 20,
          cumulative_tokens: 330,
        },
      },
      {
        type: "event",
        event: "context",
        payload: { tokens_used: 200, context_limit: 1000 },
      },
      { type: "done", status: "completed" },
    ];
    const s = frames.reduce(
      (state, frame, i) => reduce(state, frame, i + 1),
      initial(),
    );
    const parts = s.rows[1].parts;
    expect(parts[0]).toEqual({
      type: "reasoning",
      text: "Consider options",
      state: "done",
    });
    expect(parts[1]).toEqual({ type: "text", text: "Done.", state: "done" });
    expect(parts.find((p: any) => p.name === "usage").data).toEqual({
      input_tokens: 300,
      output_tokens: 30,
      total_tokens: 330,
    });
    expect(parts.find((p: any) => p.name === "context").data).toEqual({
      current_tokens: 200,
      context_window: 1000,
    });
    expect(s.busy).toBe(false);
  });
});
