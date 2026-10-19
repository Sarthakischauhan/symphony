import { Settings } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { SidebarMenuButton } from "@/components/ui/sidebar";
import { Switch } from "@/components/ui/switch";
import type { Workspace } from "./Welcome";

export type Preferences = { showUsage: boolean };
type Props = {
  workspace?: Workspace | null;
  defaultModel?: string;
  preferences: Preferences;
  onPreferencesChange: (preferences: Preferences) => void;
  pinned: number;
  onClearPins: () => void;
};
const mac = /Mac|iPhone|iPad/.test(navigator.platform);

// Browser-local preferences plus the read-only facts of this server's launch.
export function SettingsDialog({
  workspace,
  defaultModel,
  preferences,
  onPreferencesChange,
  pinned,
  onClearPins,
}: Props) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <SidebarMenuButton title={workspace?.path}>
          <Settings />
          <span>Settings</span>
          {workspace && (
            <span className="settings-trigger-meta">{workspace.name}</span>
          )}
        </SidebarMenuButton>
      </DialogTrigger>
      <DialogContent className="settings">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Preferences are saved in this browser.
          </DialogDescription>
        </DialogHeader>
        <section aria-labelledby="settings-workspace">
          <h3 id="settings-workspace">Workspace</h3>
          <dl>
            <div>
              <dt>Folder</dt>
              <dd title={workspace?.path}>{workspace?.display || "—"}</dd>
            </div>
            <div>
              <dt>Branch</dt>
              <dd>{workspace?.branch || "—"}</dd>
            </div>
            <div>
              <dt>Default model</dt>
              <dd>{defaultModel || "—"}</dd>
            </div>
          </dl>
        </section>
        <section aria-labelledby="settings-display">
          <h3 id="settings-display">Display</h3>
          <label className="settings-row">
            <span>
              <strong>Show token usage</strong>
              <small>Token totals under each reply.</small>
            </span>
            <Switch
              checked={preferences.showUsage}
              onCheckedChange={(showUsage) =>
                onPreferencesChange({ ...preferences, showUsage })
              }
            />
          </label>
        </section>
        <section aria-labelledby="settings-sessions">
          <h3 id="settings-sessions">Sessions</h3>
          <div className="settings-row">
            <span>
              <strong>Pinned sessions</strong>
              <small>
                {pinned
                  ? `${pinned} pinned in this browser.`
                  : "Nothing pinned yet."}
              </small>
            </span>
            <Button
              variant="outline"
              size="sm"
              className="pill"
              disabled={!pinned}
              onClick={onClearPins}
            >
              Clear pins
            </Button>
          </div>
        </section>
        <section aria-labelledby="settings-shortcuts">
          <h3 id="settings-shortcuts">Shortcuts</h3>
          <div className="settings-row">
            <strong>Toggle sidebar</strong>
            <kbd>{mac ? "⌘ B" : "Ctrl B"}</kbd>
          </div>
        </section>
      </DialogContent>
    </Dialog>
  );
}
