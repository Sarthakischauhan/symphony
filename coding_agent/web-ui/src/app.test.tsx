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
it("loads history, streams a task, renders SDK tool/approval/subagent widgets", async () => {
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
            ? { session_id: "session-1", model: "local:test" }
            : path === "/api/sessions"
              ? []
              : path === "/api/models"
                ? { defaultProviderId: "", default: "", providers: [] }
                : path === "/api/commands"
                  ? [
                      {
                        name: "help",
                        description: "Show commands",
                        inputHint: null,
                        options: [],
                      },
                    ]
                  : {
                      owned: true,
                      messages: [],
                      events: [],
                      children: [],
                      model: "",
                    },
      };
    }),
  );
  render(<App />);
  // The SDK composer starts the session on the first prompt.
  const input = await screen.findByLabelText("Coding task");
  fireEvent.change(input, { target: { value: "Build a report" } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await screen.findByText("Connected");
  await waitFor(() =>
    expect(calls.some(([url]) => url.endsWith("/prompt"))).toBe(true),
  );
  expect(calls.findIndex(([url]) => url === "/api/sessions")).toBeLessThan(
    calls.findIndex(([url]) => url.endsWith("/prompt")),
  );
  const frames = [
    {
      type: "event",
      event: "run_started",
      payload: { prompt: "Build a report" },
    },
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
      payload: {
        tool_call_id: "w",
        status: "success",
        result: "wrote report.md",
      },
    },
    {
      type: "event",
      event: "usage",
      payload: {
        prompt_tokens: 1200,
        completion_tokens: 80,
        cumulative_tokens: 1280,
      },
    },
    {
      type: "input_requested",
      request_id: "q",
      question: "Allow writing?",
      choices: ["Allow once", "Deny"],
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
  // The user turn comes from the protocol's run_started prompt.
  expect(screen.getAllByText("Build a report").length).toBeGreaterThan(0);
  expect(screen.getByText("Working on it")).toBeTruthy();
  expect(screen.getByText("Allow writing?")).toBeTruthy();
  expect(screen.getByText("Research")).toBeTruthy();
  // A written file renders as its own tool event, with no artifact card.
  expect(screen.getByText("write_file")).toBeTruthy();
  expect(
    screen.getByLabelText("Context and token usage").textContent,
  ).toContain("total 1,280");
  // While the run is live the SDK send button becomes the stop control.
  expect(screen.getByRole("button", { name: "Stop response" })).toBeTruthy();
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
  // The question closes locally; the protocol has no answered frame.
  await waitFor(() => expect(screen.queryByText("Allow writing?")).toBeNull());
  // Replaying the same SSE id must not append duplicate text.
  await act(async () =>
    source.onmessage({ lastEventId: "2", data: JSON.stringify(frames[1]) }),
  );
  expect(screen.getAllByText("Working on it")).toHaveLength(1);
  await act(async () =>
    source.onmessage({
      lastEventId: String(frames.length + 1),
      data: JSON.stringify({ type: "done", status: "completed" }),
    }),
  );
  await screen.findByRole("button", { name: "Send message" });
});

it("answers an approval card with the chosen choice through the answer frame", async () => {
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
          options?.method === "POST"
            ? { session_id: "session-1", model: "local:test" }
            : path === "/api/sessions"
              ? []
              : path === "/api/models"
                ? { defaultProviderId: "", default: "", providers: [] }
                : path === "/api/commands"
                  ? []
                  : { owned: true, messages: [], events: [], children: [], model: "" },
      };
    }),
  );
  render(<App />);
  const input = await screen.findByLabelText("Coding task");
  fireEvent.change(input, { target: { value: "Fix health" } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await screen.findByText("Connected");
  await act(async () => {
    source.onmessage({
      lastEventId: "1",
      data: JSON.stringify({ type: "event", event: "run_started", payload: { prompt: "Fix health" } }),
    });
    source.onmessage({
      lastEventId: "2",
      data: JSON.stringify({
        type: "input_requested",
        request_id: "q-7",
        question: "Overwrite existing file `app/api.py`?",
        choices: ["Allow once", "Always allow", "Deny"],
        default: "Allow once",
        kind: "approval",
        target: "app/api.py",
        detail: "Overwrite existing file `app/api.py`?",
        bytes: 29,
      }),
    });
  });
  const card = screen.getByRole("region", { name: "Approval required" });
  expect(card.textContent).toContain("app/api.py");
  expect(card.textContent).toContain("29 bytes");
  const posted = () => calls.filter(([url]) => String(url).endsWith("/prompt")).length;
  const before = posted();
  fireEvent.click(screen.getByRole("button", { name: "Always allow" }));
  await waitFor(() =>
    expect(calls.some(([url]) => String(url).endsWith("/answer"))).toBe(true),
  );
  const [, options] = calls.find(([url]) => String(url).endsWith("/answer"));
  expect(JSON.parse(options.body)).toEqual({ request_id: "q-7", value: "Always allow" });
  // An approval is never sent as a chat message.
  expect(posted()).toBe(before);
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: "Approval required" })).toBeNull(),
  );
});
