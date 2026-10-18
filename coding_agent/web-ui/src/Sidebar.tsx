import { useEffect, useRef, useState } from "react";

export type Session = {
  session_id: string;
  first_message: string;
  updated_at: string;
  message_count: number;
  active: boolean;
  owned: boolean;
};
type Props = {
  mobile?: boolean;
  sessions: Session[];
  selected: string;
  open: boolean;
  onToggle: () => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRefresh: () => void;
};
function stored<T>(key: string, fallback: T): T {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}
export function sessionGroups(
  sessions: Session[],
  pins: string[],
  query: string,
  now = new Date(),
) {
  const day = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const groups = new Map<string, Session[]>([
    ["Pinned", []],
    ["Active", []],
    ["Today", []],
    ["Previous 7 days", []],
    ["Older", []],
  ]);
  for (const session of [...sessions].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at),
  )) {
    if (
      !`${session.first_message} ${session.session_id}`
        .toLowerCase()
        .includes(query.toLowerCase().trim())
    )
      continue;
    const time = Date.parse(session.updated_at);
    const group = pins.includes(session.session_id)
      ? "Pinned"
      : session.active
        ? "Active"
        : time >= day
          ? "Today"
          : time >= day - 7 * 86400000
            ? "Previous 7 days"
            : "Older";
    groups.get(group)!.push(session);
  }
  return [...groups].filter(([, items]) => items.length);
}
function age(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Saved session"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
export function Sidebar({
  mobile = false,
  sessions,
  selected,
  open,
  onToggle,
  onSelect,
  onCreate,
  onRefresh,
}: Props) {
  const [query, setQuery] = useState("");
  const [pins, setPins] = useState<string[]>(() =>
    stored("symphony-pinned-sessions", []),
  );
  const [width, setWidth] = useState<number>(() =>
    Math.max(240, Math.min(400, stored("symphony-sidebar-width", 288))),
  );
  const search = useRef<HTMLInputElement>(null);
  const panel = useRef<HTMLElement>(null);
  const groups = sessionGroups(sessions, pins, query);
  useEffect(() => {
    localStorage.setItem("symphony-pinned-sessions", JSON.stringify(pins));
  }, [pins]);
  useEffect(() => {
    localStorage.setItem("symphony-sidebar-width", JSON.stringify(width));
  }, [width]);
  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (!open) onToggle();
        requestAnimationFrame(() => search.current?.focus());
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
        event.preventDefault();
        onToggle();
      }
      if (event.key === "Escape" && open && window.innerWidth <= 760)
        onToggle();
      // Keep keyboard focus inside the mobile navigation drawer.
      if (event.key === "Tab" && open && window.innerWidth <= 760) {
        const controls = panel.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input",
        );
        if (!controls?.length) return;
        const first = controls[0],
          last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", keys);
    return () => document.removeEventListener("keydown", keys);
  }, [open, onToggle]);
  useEffect(() => {
    if (open && window.innerWidth <= 760) {
      const previous = document.activeElement as HTMLElement | null;
      search.current?.focus();
      return () => previous?.focus();
    }
  }, [open]);
  const pin = (id: string) =>
    setPins((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : [...current, id],
    );
  return (
    <>
      {open && (
        <button
          className="sidebar-backdrop"
          aria-label="Close session navigation"
          onClick={onToggle}
        />
      )}
      <aside
        id="session-navigation"
        role={mobile && open ? "dialog" : undefined}
        aria-modal={mobile && open ? true : undefined}
        ref={panel}
        className={`sidebar ${open ? "is-open" : "is-collapsed"}`}
        aria-label="Session navigation"
        style={{ "--sidebar-width": `${width}px` } as React.CSSProperties}
      >
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">
            S
          </span>
          <div className="sidebar-label">
            <strong>Symphony</strong>
            <span>YOUR CODING WORKSPACE</span>
          </div>
          <button
            className="icon-button collapse-button"
            onClick={onToggle}
            aria-label={open ? "Collapse sidebar" : "Expand sidebar"}
            title="Toggle sidebar (⌘/Ctrl B)"
          >
            {open ? "‹" : "›"}
          </button>
        </div>
        <div className="sidebar-actions">
          <button
            className="new-session"
            onClick={onCreate}
            title="New session"
          >
            <span aria-hidden="true">＋</span>
            <span className="sidebar-label">New session</span>
          </button>
        </div>
        <div className="sidebar-content">
          <label className="session-search">
            <span aria-hidden="true">⌕</span>
            <input
              ref={search}
              aria-label="Search sessions"
              placeholder="Search sessions…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <kbd>⌘ K</kbd>
          </label>
          <div className="session-list-heading">
            <span>
              SESSIONS <span className="session-total">{sessions.length}</span>
            </span>
            <button
              className="icon-button"
              onClick={onRefresh}
              aria-label="Refresh sessions"
              title="Refresh sessions"
            >
              ↻
            </button>
          </div>
          <nav
            className="session-list"
            aria-label="Sessions"
            onKeyDown={(event) => {
              if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key))
                return;
              const buttons = Array.from(
                event.currentTarget.querySelectorAll<HTMLButtonElement>(
                  ".session-select",
                ),
              );
              const index = buttons.indexOf(
                document.activeElement as HTMLButtonElement,
              );
              if (index < 0) return;
              event.preventDefault();
              buttons[
                event.key === "Home"
                  ? 0
                  : event.key === "End"
                    ? buttons.length - 1
                    : Math.max(
                        0,
                        Math.min(
                          buttons.length - 1,
                          index + (event.key === "ArrowDown" ? 1 : -1),
                        ),
                      )
              ]?.focus();
            }}
          >
            {!groups.length && (
              <div className="sidebar-empty">
                <span aria-hidden="true">◇</span>
                <strong>
                  {query
                    ? "No matching sessions"
                    : "Your next idea starts here"}
                </strong>
                <p>
                  {query
                    ? "Try another title or session ID."
                    : "Create a session to work with your code."}
                </p>
                {query && (
                  <button onClick={() => setQuery("")}>Clear search</button>
                )}
              </div>
            )}
            {groups.map(([name, items]) => (
              <section className="session-group" key={name} aria-label={name}>
                <h2>{name}</h2>
                {items.map((session) => (
                  <div
                    className={`session-item ${session.session_id === selected ? "is-selected" : ""}`}
                    key={session.session_id}
                  >
                    <button
                      className="session-select"
                      aria-current={
                        session.session_id === selected ? "page" : undefined
                      }
                      onClick={() => onSelect(session.session_id)}
                      title={session.first_message || session.session_id}
                    >
                      <span
                        className={`session-status ${session.active ? (session.owned ? "status-web" : "status-locked") : ""}`}
                        aria-hidden="true"
                      >
                        {session.active && !session.owned ? "▣" : "◇"}
                      </span>
                      <span className="session-copy">
                        <span className="session-title">
                          {session.first_message || "Untitled session"}
                        </span>
                        <span className="session-meta">
                          <span>
                            {session.active
                              ? session.owned
                                ? "Active in Web"
                                : "Active in TUI · read only"
                              : age(session.updated_at)}
                          </span>
                          <span>· {session.message_count} messages</span>
                        </span>
                      </span>
                    </button>
                    <button
                      className={`pin-session ${pins.includes(session.session_id) ? "is-pinned" : ""}`}
                      aria-label={`${pins.includes(session.session_id) ? "Unpin" : "Pin"} ${session.first_message || "session"}`}
                      aria-pressed={pins.includes(session.session_id)}
                      onClick={() => pin(session.session_id)}
                      title="Pin session"
                    >
                      {pins.includes(session.session_id) ? "★" : "☆"}
                    </button>
                  </div>
                ))}
              </section>
            ))}
          </nav>
          <footer className="sidebar-footer">
            <span className="local-indicator" />
            <div>
              <strong>Local workspace</strong>
              <small>Runs on your machine</small>
            </div>
            <span className="footer-lock" aria-label="Localhost protected">
              ▣
            </span>
          </footer>
        </div>
        <div
          className="sidebar-resizer"
          role="separator"
          aria-label="Resize sidebar"
          aria-orientation="vertical"
          aria-valuemin={240}
          aria-valuemax={400}
          aria-valuenow={width}
          tabIndex={open ? 0 : -1}
          onKeyDown={(event) => {
            if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
              event.preventDefault();
              setWidth((w) =>
                Math.max(
                  240,
                  Math.min(400, w + (event.key === "ArrowRight" ? 16 : -16)),
                ),
              );
            }
          }}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId))
              setWidth(Math.max(240, Math.min(400, event.clientX)));
          }}
        />
      </aside>
    </>
  );
}
