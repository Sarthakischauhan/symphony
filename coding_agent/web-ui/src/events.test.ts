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
    expect(s.rows[0].parts.at(-1).artifact.content).toBe("# Done");
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
    expect(s.rows[0].parts[0].subagent.messages[0].parts[0].text).toBe(
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
