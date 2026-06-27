import type { Route } from "./App";

interface Props {
  route: Route;
  setRoute: (r: Route) => void;
  hasProject: boolean;
}

const ICONS: Record<string, string> = {
  dashboard: "M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm9 0h7V11h-7v9Zm0-16v5h7V4h-7Z",
  characters:
    "M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4Zm0 2c-3 0-8 1.5-8 4.5V21h16v-2.5c0-3-5-4.5-8-4.5Z",
  chapters: "M4 4h16v4H4V4Zm0 6h16v4H4v-4Zm0 6h10v4H4v-4Z",
  settings:
    "M12 8a4 4 0 1 0 4 4 4 4 0 0 0-4-4Zm8.4 4 1.5-1.2-1.5-2.6-1.9.6a6.9 6.9 0 0 0-1.6-.9L16 5.5h-3l-.4 2a6.9 6.9 0 0 0-1.6.9l-1.9-.6L7.1 10 8.6 12l-1.5 1.2 1.5 2.6 1.9-.6c.5.4 1 .7 1.6.9l.4 2h3l.4-2c.6-.2 1.1-.5 1.6-.9l1.9.6 1.5-2.6Z",
};

function NavItem({
  id,
  label,
  active,
  disabled,
  onClick,
}: {
  id: string;
  label: string;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={[
        "group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition",
        disabled
          ? "cursor-not-allowed text-faint/60"
          : active
            ? "bg-elevated text-text"
            : "text-muted hover:bg-surface-2 hover:text-text",
      ].join(" ")}
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="currentColor">
        <path d={ICONS[id]} />
      </svg>
      <span className="truncate">{label}</span>
      {active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-accent" />}
    </button>
  );
}

export function Sidebar({ route, setRoute, hasProject }: Props) {
  return (
    <aside className="flex w-[200px] shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-strong text-sm font-bold text-white">
          ◉
        </div>
        <span className="text-sm font-semibold tracking-tight">AudioBookGen</span>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-3">
        <NavItem id="dashboard" label="Dashboard" active={route === "dashboard"} onClick={() => setRoute("dashboard")} />
        <NavItem
          id="characters"
          label="Characters"
          active={route === "characters"}
          disabled={!hasProject}
          onClick={() => setRoute("characters")}
        />
        <NavItem
          id="chapters"
          label="Chapters"
          active={route === "chapters"}
          disabled={!hasProject}
          onClick={() => setRoute("chapters")}
        />
      </nav>

      {/* Settings lives in the bottom-left corner. */}
      <div className="border-t border-border px-3 py-3">
        <NavItem id="settings" label="Settings" active={route === "settings"} onClick={() => setRoute("settings")} />
      </div>
    </aside>
  );
}
