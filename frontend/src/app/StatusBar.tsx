import { useEffect, useRef, useState } from "react";
import { api, type Health } from "../lib/api";
import type { ActiveProject } from "./App";

function Dot({ ok, label, busy, onClick, title }: {
  ok: boolean | null;
  label: string;
  busy?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  const color = busy ? "bg-warn" : ok == null ? "bg-faint" : ok ? "bg-good" : "bg-bad";
  const inner = (
    <>
      <span className={`h-2 w-2 rounded-full ${color} ${busy ? "animate-pulse" : ""} ${ok ? "shadow-[0_0_6px] shadow-good/60" : ""}`} />
      {busy ? `${label}…` : label}
    </>
  );
  if (onClick) {
    return (
      <button
        onClick={onClick}
        disabled={busy}
        title={title}
        className="flex items-center gap-1.5 rounded text-xs text-muted hover:text-text disabled:cursor-default"
      >
        {inner}
      </button>
    );
  }
  return <span className="flex items-center gap-1.5 text-xs text-muted">{inner}</span>;
}

export function StatusBar({ project }: { project: ActiveProject | null }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [launching, setLaunching] = useState(false);
  const alive = useRef(true);

  const poll = () => api.health().then((h) => alive.current && setHealth(h)).catch(() => alive.current && setHealth(null));

  useEffect(() => {
    alive.current = true;
    poll();
    // Poll faster while a launch is in flight so the dot flips green promptly.
    const t = setInterval(poll, launching ? 2500 : 8000);
    return () => {
      alive.current = false;
      clearInterval(t);
    };
  }, [launching]);

  // Clear the launching state once ComfyUI reports healthy.
  useEffect(() => {
    if (launching && health?.comfy) setLaunching(false);
  }, [health?.comfy, launching]);

  const launchComfy = () => {
    if (launching || health?.comfy) return;
    setLaunching(true);
    api.launchComfy()
      .then((r) => {
        if (!r.ok) {
          setLaunching(false);
          alert(`ComfyUI launch failed: ${r.error ?? "unknown error"}`);
        } else {
          poll();
        }
      })
      .catch(() => setLaunching(false));
  };

  return (
    <header className="flex h-10 shrink-0 items-center gap-4 border-b border-border bg-surface px-4">
      <span className="text-xs font-medium text-faint">
        {project ? (
          <>
            <span className="text-muted">Project</span>{" "}
            <span className="text-text">{project.title}</span>
          </>
        ) : (
          "No project open"
        )}
      </span>
      <div className="ml-auto flex items-center gap-4">
        <Dot ok={health?.ollama ?? null} label="Ollama" />
        <Dot
          ok={health?.comfy ?? null}
          label="ComfyUI"
          busy={launching}
          onClick={health?.comfy ? undefined : launchComfy}
          title={health?.comfy ? undefined : "Launch ComfyUI (headless, tts_audio_suite)"}
        />
      </div>
    </header>
  );
}
