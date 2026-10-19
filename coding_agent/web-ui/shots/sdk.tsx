// Local-only: renders chat-sdk pieces without Symphony's stylesheet, in either theme.
import { createRoot } from "react-dom/client";
import {
  ChatComposer,
  ChatContextProvider,
  MessageContent,
  ThemeProvider,
  type ChatAdapter,
} from "@sarchauhan/chat";
import "@sarchauhan/chat/styles.css";
import type { AgentPart } from "@sarchauhan/protocol";

const params = new URLSearchParams(location.search);
const theme = params.get("theme") === "light" ? "light" : "dark";
const view = params.get("view") || "ask";
const adapter: ChatAdapter = { async *sendMessage() {} };
const question =
  "The commit hook blocked the push: 1,135 tests passed, but two failed (model default mismatch and missing Playwright browser). Should I bypass the hook and push these changes?";
const askInput = {
  question,
  choices: ["Bypass the hook and push", "Stop without pushing"],
  default: "Bypass the hook and push",
  activity: { verb: "Asking", reason: "Get approval to bypass failed repository checks", group: "push" },
};
const done: AgentPart[] = [
  { type: "text", text: "The hook blocked the push, so I asked before bypassing it." },
  {
    type: "tool",
    toolCallId: "ask1",
    toolName: "ask_user",
    state: "output-available",
    input: askInput,
    output: { output: "Bypass the hook and push", durationMs: 9100, summary: { lines: null, matches: null, added: null, removed: null } },
  },
];
const pending: AgentPart[] = [
  { type: "tool", toolCallId: "ask2", toolName: "ask_user", state: "input-available", input: askInput },
];
const long = `Here is the pytest output:

coding_agent/tests/test_tui.py::test_dropped_image_becomes_clickable_chip_and_opens_the_preview_modal_on_click
/Users/sarthak/personal/symphony/.venv/lib/python3.11/site-packages/textual_image/_pixeldata.py:141: DeprecationWarning
=========================================================================================== short test summary info ===========================================================================================
FAILED coding_agent/tests/test_web.py::test_workspace_info_models_and_commands_come_from_the_worker_protocol_over_stdio_frames

\`\`\`
$ uv run --no-sync pytest coding_agent/tests/test_web.py -k test_workspace_info_models_and_commands_come_from_the_worker_protocol_over_stdio_frames --maxfail=1 -q --tb=long
\`\`\`

======= Full log: /Users/sarthak/.symphony/sessions/jobs/faabce59-0d1c-4f3e-9a7e-1b2c3d4e5f60/output.log`;

// Same rows as the model/list frame gives the host; ?reg=before mirrors the old host.
const before = params.get("reg") === "before";
const m = (id: string, label: string, limit: number) => ({
  id, label, ...(before ? { description: `${limit / 1000}k context` } : { contextWindow: limit }),
});
const registry = {
  defaultProviderId: "openai",
  providers: [
    { id: "openai", label: "openai", defaultModel: "openai:gpt-6.1", models: [m("openai:gpt-6.1", "gpt-6.1", 400000), m("openai:gpt-6.1-mini", "gpt-6.1-mini", 400000)] },
    { id: "anthropic", label: "anthropic", defaultModel: "anthropic:claude-opus-5-5", models: [m("anthropic:claude-opus-5-5", "claude-opus-5-5", 1000000), m("anthropic:claude-sonnet-5-5", "claude-sonnet-5-5", 1000000)] },
    { id: "gemini", label: "gemini", defaultModel: "gemini:gemini-3-pro", models: [m("gemini:gemini-3-pro", "gemini-3-pro", 1048576)] },
    { id: "local", label: "local", defaultModel: "local:qwen3-coder", models: [{ id: "local:qwen3-coder", label: "qwen3-coder" }] },
  ],
};
const registryUrl = `data:application/json,${encodeURIComponent(JSON.stringify(registry))}`;

// The protocol payload for an edit at line 41 of app.py (as Symphony Web relays it).
const patchParts: AgentPart[] = [
  {
    type: "tool",
    toolCallId: "p1",
    toolName: "patch",
    state: "output-available",
    input: {
      path: "app.py",
      old_str: "line_41 = 41\nline_42 = 42\nline_43 = 43\n",
      new_str: "line_41 = 41\nline_42 = 4200\nline_43 = 43\n",
      before: "line_41 = 41\nline_42 = 42\nline_43 = 43\n",
      after: "line_41 = 41\nline_42 = 4200\nline_43 = 43\n",
    },
    output: {
      output: "patched app.py at line 41 (1 replacement(s), +2 bytes)",
      durationMs: 4,
      summary: { lines: null, matches: null, added: 1, removed: 1, start_line: 41 },
    },
  },
];

function Page() {
  return (
    <ThemeProvider defaultTheme={theme}>
      <div className="chat-root" data-theme={theme} style={{ minHeight: "100vh", padding: 24, boxSizing: "border-box" }}>
        <div style={{ width: 760, maxWidth: "100%", margin: "0 auto" }} id="shot">
          {view === "ask" && (
            <div className="chat-message chat-message-assistant">
              <div className="chat-message-assistant-inner">
                <MessageContent parts={done} />
                <MessageContent parts={pending} />
              </div>
            </div>
          )}
          {view === "bubble" && (
            <div className="chat-message chat-message-user">
              <div className="chat-message-user-inner">
                <div className="chat-message-bubble">
                  <MessageContent parts={[{ type: "text", text: long }]} isUser />
                </div>
              </div>
            </div>
          )}
          {view === "picker" && (
            <ChatContextProvider adapter={adapter} defaultThreadId="t" registryUrl={registryUrl}>
              <div style={{ paddingTop: 460 }}>
                <ChatComposer showModelSelector collapsedVariant="circle" defaultExpanded />
              </div>
            </ChatContextProvider>
          )}
          {view === "patch" && (
            <div className="chat-message chat-message-assistant">
              <div className="chat-message-assistant-inner">
                <MessageContent parts={patchParts} />
              </div>
            </div>
          )}
          {view === "composer" && (
            <ChatContextProvider adapter={adapter} defaultThreadId="t" defaultProvider="">
              <ChatComposer showModelSelector={false} collapsedVariant="circle" defaultExpanded />
            </ChatContextProvider>
          )}
        </div>
      </div>
    </ThemeProvider>
  );
}
createRoot(document.getElementById("root")!).render(<Page />);
