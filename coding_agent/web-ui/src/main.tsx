import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArtifactWidget,
  MessageContent,
  QuestionWidget,
  SubagentWidget,
  ThemeProvider,
} from "@sarchauhan/chat";
import "@sarchauhan/chat/styles.css";
import "./style.css";
import { historical, initial, reduce, type State } from "./events";
import { Sidebar } from "./Sidebar";
const token =
  location.hash.slice(1) || sessionStorage.getItem("symphony-token") || "";
if (location.hash) {
  sessionStorage.setItem("symphony-token", token);
  history.replaceState(null, "", location.pathname);
}
async function api(path: string, data?: object) {
  const r = await fetch("/api/" + path, {
    method: data ? "POST" : "GET",
    headers: {
      "X-Symphony-Token": token,
      ...(data ? { "Content-Type": "application/json" } : {}),
    },
    body: data ? JSON.stringify(data) : undefined,
  });
  const value = await r.json();
  if (!r.ok) throw new Error(value.error || r.statusText);
  return value;
}
export function App() {
  const [sessions, setSessions] = useState<any[]>([]),
    [selected, setSelected] = useState(
      sessionStorage.getItem("symphony-session") || "",
    );
  const [state, setState] = useState<State>(initial),
    [prompt, setPrompt] = useState(""),
    [owned, setOwned] = useState(false),
    [connected, setConnected] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 760);
  const toggleSidebar = () => setSidebarOpen((value) => !value);
  const [mobile, setMobile] = useState(() => window.innerWidth <= 760);
  useEffect(() => {
    const resize = () => setMobile(window.innerWidth <= 760);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const stream = useRef<EventSource | null>(null),
    generation = useRef(0);
  const error = (e: any) =>
    setState((s) => ({ ...s, error: String(e.message || e) }));
  const refresh = () => api("sessions").then(setSessions).catch(error);
  async function open(id: string) {
    const current = ++generation.current;
    stream.current?.close();
    setConnected(false);
    setOwned(false);
    setSelected(id);
    sessionStorage.setItem("symphony-session", id);
    try {
      const data = await api(`sessions/${id}`);
      if (current !== generation.current) return;
      setState(historical(data));
      setOwned(data.owned);
      if (data.owned) {
        let cursor = 0;
        const source = new EventSource(
          `/api/sessions/${id}/events?token=${encodeURIComponent(token)}`,
        );
        stream.current = source;
        source.onopen = () => setConnected(true);
        source.onerror = () => setConnected(false);
        source.onmessage = (e) => {
          if (current !== generation.current) return;
          const seq = Number(e.lastEventId);
          if (seq <= cursor) return;
          if (seq !== cursor + 1) {
            source.close();
            error(new Error("Event gap; reopen session to recover"));
            return;
          }
          cursor = seq;
          const frame = JSON.parse(e.data);
          setState((s) => reduce(s, frame, seq));
          if (frame.status === "worker_exited") {
            source.close();
            setOwned(false);
            setConnected(false);
          }
        };
      }
    } catch (e) {
      error(e);
    }
  }
  useEffect(() => {
    refresh();
    if (selected) void open(selected);
    return () => {
      ++generation.current;
      stream.current?.close();
    };
  }, []);
  async function create() {
    try {
      const data = await api("sessions", {});
      await open(data.session_id);
      refresh();
    } catch (e) {
      error(e);
    }
  }
  async function resume() {
    try {
      await api(`sessions/${selected}/resume`, {});
      await open(selected);
      refresh();
    } catch (e) {
      error(e);
    }
  }
  return (
    <ThemeProvider defaultTheme="dark">
      <div className="shell chat-root" data-theme="dark">
        <Sidebar
          mobile={mobile}
          sessions={sessions}
          selected={selected}
          open={sidebarOpen}
          onToggle={toggleSidebar}
          onCreate={create}
          onRefresh={refresh}
          onSelect={(id) => {
            void open(id);
            if (window.innerWidth <= 760) setSidebarOpen(false);
          }}
        />
        <main inert={mobile && sidebarOpen}>
          <header>
            <button
              className="icon-button mobile-menu"
              onClick={toggleSidebar}
              aria-label="Open session navigation"
              aria-expanded={sidebarOpen}
              aria-controls="session-navigation"
            >
              ☰
            </button>
            <div className="conversation-heading">
              <span className="eyebrow">SYMPHONY WEB</span>
              <strong>
                {sessions.find((s) => s.session_id === selected)
                  ?.first_message ||
                  (selected
                    ? "New coding session"
                    : "Your workspace, in conversation")}
              </strong>
            </div>
            <span
              className={`connection-badge ${connected ? "is-connected" : ""}`}
            >
              {owned ? (connected ? "Connected" : "Reconnecting…") : "History"}
            </span>
            {selected && !owned && (
              <button onClick={resume}>Resume session</button>
            )}
            {owned && (
              <button
                onClick={() =>
                  api(`sessions/${selected}/cancel`, {}).catch(error)
                }
              >
                Cancel execution
              </button>
            )}
          </header>
          {state.error && <p role="alert">{state.error}</p>}
          <section aria-live="polite" className="transcript">
            {!selected && (
              <div className="welcome">
                <span className="welcome-icon" aria-hidden="true">
                  S
                </span>
                <span className="eyebrow">MEET YOUR CODING PARTNER</span>
                <h1>What are we building?</h1>
                <p>
                  Explore your code, work through a problem, or bring your next
                  idea to life.
                </p>
                <button onClick={create}>
                  Start a session <span aria-hidden="true">↗</span>
                </button>
                <div className="welcome-capabilities">
                  <span>◇ Your existing sessions</span>
                  <span>◎ Live tool activity</span>
                  <span>▣ You stay in control</span>
                </div>
              </div>
            )}

            {state.rows.map((row) => (
              <article key={row.id}>
                <small>{row.role}</small>
                {row.parts.map((part, i) =>
                  part.type === "web-artifact" ? (
                    <ArtifactWidget
                      key={i}
                      artifact={{
                        ...part.artifact,
                        url: `/api/sessions/${selected}/artifacts/${encodeURIComponent(part.artifact.id)}?token=${encodeURIComponent(token)}`,
                      }}
                    />
                  ) : part.type === "web-subagent" ? (
                    <SubagentWidget key={i} subagent={part.subagent} />
                  ) : (
                    <MessageContent
                      key={i}
                      parts={[part]}
                      isUser={row.role === "user"}
                    />
                  ),
                )}
              </article>
            ))}
            {Object.values(state.pending).map((q) => (
              <QuestionWidget
                key={q.request_id}
                prompt={q.question}
                options={q.choices || []}
                allowCustom
                onSubmit={async (answer) => {
                  await api(`sessions/${selected}/answer`, {
                    request_id: q.request_id,
                    value: answer.text || answer.values.join(", "),
                  });
                }}
              />
            ))}
          </section>
          <form
            className="composer"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api(`sessions/${selected}/prompt`, { prompt });
                setPrompt("");
                refresh();
              } catch (e) {
                error(e);
              }
            }}
          >
            <textarea
              aria-label="Coding task"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe a coding task…"
            />
            <button
              aria-label="Send"
              disabled={!owned || !connected || state.busy || !prompt.trim()}
            >
              Send ↗
            </button>
          </form>
        </main>
      </div>
    </ThemeProvider>
  );
}
const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
