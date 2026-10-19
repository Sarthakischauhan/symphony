import {
  Cpu,
  FileDiff,
  Folder,
  GitBranch,
  History,
  ShieldCheck,
  SquareTerminal,
  Workflow,
} from "lucide-react";
import logo from "./assets/symphony-logo.svg";
import type { SlashCommand } from "./frames";

export type Workspace = {
  path: string;
  display: string;
  name: string;
  branch: string;
};
const FEATURES = [
  {
    icon: FileDiff,
    title: "Edits with diffs",
    copy: "Reads files and applies patches you can inspect inline.",
  },
  {
    icon: SquareTerminal,
    title: "Runs commands",
    copy: "Builds, tests and scripts run in this workspace.",
  },
  {
    icon: ShieldCheck,
    title: "Asks before risky steps",
    copy: "Approvals pause the run until you decide.",
  },
  {
    icon: Workflow,
    title: "Delegates to subagents",
    copy: "Focused helpers report back with their activity.",
  },
  {
    icon: History,
    title: "Continues web sessions",
    copy: "Every Symphony Web session is here to read or resume.",
  },
  {
    icon: Cpu,
    title: "Switches models",
    copy: "Pick any configured model from the composer.",
  },
];
export function Welcome({
  workspace,
  model,
  resuming,
  commands = [],
}: {
  workspace: Workspace | null;
  model?: string;
  resuming: boolean;
  commands?: SlashCommand[];
}) {
  return (
    <section className="welcome" aria-label="Welcome">
      <img className="welcome-logo" src={logo} alt="Symphony" />
      <h1 className="welcome-title">
        {resuming
          ? "This session is ready for its next task."
          : "What should we work on?"}
      </h1>
      {workspace && (
        <dl className="workspace-card" aria-label="Workspace">
          <div>
            <dt>
              <Folder aria-hidden="true" /> Workspace
            </dt>
            <dd title={workspace.path}>{workspace.display}</dd>
          </div>
          {workspace.branch && (
            <div>
              <dt>
                <GitBranch aria-hidden="true" /> Branch
              </dt>
              <dd>{workspace.branch}</dd>
            </div>
          )}
          {model && (
            <div>
              <dt>
                <Cpu aria-hidden="true" /> Model
              </dt>
              <dd>{model}</dd>
            </div>
          )}
        </dl>
      )}
      <ul className="feature-grid">
        {FEATURES.map(({ icon: Icon, title, copy }) => (
          <li key={title}>
            <Icon aria-hidden="true" />
            <strong>{title}</strong>
            <span>{copy}</span>
          </li>
        ))}
      </ul>
      {commands.length > 0 && (
        <p className="welcome-commands" aria-label="Slash commands">
          {commands.map((command) => (
            <code key={command.name} title={command.description}>
              /{command.name}
            </code>
          ))}
        </p>
      )}
    </section>
  );
}
