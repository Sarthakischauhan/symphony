// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  act,
} from "@testing-library/react";
import { App } from "./main";
let source: any;
class Stream {
  onopen: any;
  onmessage: any;
  onerror: any;
  constructor() {
    source = this;
    queueMicrotask(() => this.onopen?.());
  }
  close() {}
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
it("loads history, streams a task, renders SDK tool/approval/artifact/subagent widgets", async () => {
  vi.stubGlobal("EventSource", Stream);
  const calls: any[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, options) => {
      calls.push([url, options]);
      const path = String(url);
      return {
        ok: true,
        json: async () =>
          options.method === "POST"
            ? { session_id: "session-1" }
            : path === "/api/sessions"
              ? []
              : { owned: true, messages: [], events: [] },
      };
    }),
  );
  render(<App />);
  fireEvent.click(screen.getByRole("button", { name: "New session" }));
  await screen.findByText("Connected");
  fireEvent.change(screen.getByLabelText("Coding task"), {
    target: { value: "Build a report" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() =>
    expect(calls.some(([url]) => url.endsWith("/prompt"))).toBe(true),
  );
  const frames = [
    { type: "user", text: "Build a report" },
    { type: "event", event: "text_delta", payload: { delta: "Working on it" } },
    {
      type: "event",
      event: "tool_execution_started",
      payload: {
        tool_call_id: "p",
        tool_name: "patch",
        arguments: { path: "a.py", old_str: "old", new_str: "new" },
      },
    },
    {
      type: "input_requested",
      request_id: "q",
      question: "Allow writing?",
      choices: ["Allow once", "Deny"],
    },
    {
      type: "event",
      event: "agent_spawned",
      payload: { child_id: "c", label: "Research", prompt: "Inspect code" },
    },
    {
      type: "event",
      event: "tool_execution_started",
      payload: {
        tool_call_id: "w",
        tool_name: "write_file",
        arguments: { path: "report.md", content: "# Done" },
      },
    },
    {
      type: "event",
      event: "tool_execution_completed",
      payload: { tool_call_id: "w", status: "success" },
    },
  ];
  await act(async () => {
    frames.forEach((frame, i) =>
      source.onmessage({
        lastEventId: String(i + 1),
        data: JSON.stringify(frame),
      }),
    );
  });
  expect(screen.getByText("Working on it")).toBeTruthy();
  expect(screen.getByText("Allow writing?")).toBeTruthy();
  expect(screen.getByText("Research")).toBeTruthy();
  expect(screen.getAllByText("report.md").length).toBeGreaterThan(0);
  fireEvent.click(screen.getByText("Allow once"));
  const confirm = screen.getByRole("button", {
    name: /confirm|submit|send answer/i,
  });
  fireEvent.click(confirm);
  await waitFor(() =>
    expect(
      calls.some(
        ([url, options]) =>
          url.endsWith("/answer") && options.body.includes("Allow once"),
      ),
    ).toBe(true),
  );
  // Replaying the same SSE id must not append duplicate text.
  await act(async () =>
    source.onmessage({ lastEventId: "2", data: JSON.stringify(frames[1]) }),
  );
  expect(screen.getAllByText("Working on it")).toHaveLength(1);
});
