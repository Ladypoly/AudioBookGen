import { useEffect, useRef, useState } from "react";
import type { ActiveProject } from "../app/App";
import { api, isElectron, pickFolder, type CharacterView, type ChapterInfo, type JobView } from "../lib/api";
import { ChapterRow } from "./ChapterRow";
import { TimelineEditor } from "./TimelineEditor";
import { Placeholder } from "./Placeholder";

const MODES: [string, string][] = [
  ["continue", "Continue — only what's missing"],
  ["full", "Full — regenerate everything"],
  ["voices", "Voices only"],
  ["voices_chars", "Character voices (no narrator)"],
  ["ambience", "Ambience only"],
  ["sfx", "SFX only"],
  ["mix", "Mix only (re-assemble)"],
];

export function Chapters({
  project,
  jobs,
}: {
  project: ActiveProject | null;
  jobs: JobView[];
}) {
  const [chapters, setChapters] = useState<ChapterInfo[] | null>(null);
  const [characters, setCharacters] = useState<CharacterView[]>([]);
  const [mode, setMode] = useState("continue");
  const [error, setError] = useState<string | null>(null);
  const [timelineCid, setTimelineCid] = useState<string | null>(null);

  const load = () => api.listChapters().then(setChapters).catch((e) => setError(String(e)));

  useEffect(() => {
    if (!project) return;
    load();
    // load the cast for the voice picker (default one-off voices are created
    // lazily on the backend only when actually assigned).
    api.listCharacters().then(setCharacters).catch(() => {});
  }, [project]);

  // Refresh the list when a render/produce job finishes.
  const prevDone = useRef(0);
  useEffect(() => {
    const done = jobs.filter(
      (j) => ["render", "produce", "export"].includes(j.kind) && j.state === "done",
    ).length;
    if (done !== prevDone.current) {
      prevDone.current = done;
      if (project) load();
    }
  }, [jobs, project]);

  if (!project) return <Placeholder title="Chapters" note="Open a project from the Dashboard first." />;

  const allRendered = !!chapters?.length && chapters.every((c) => c.rendered);

  const produce = () => api.produceChapters(mode).catch((e) => setError(String(e)));
  const exportBook = async () => {
    let folder: string | null = null;
    if (isElectron()) folder = await pickFolder();
    else folder = window.prompt("Export folder (absolute path):");
    if (folder) api.exportAudiobook(folder).catch((e) => setError(String(e)));
  };

  return (
    <div className="mx-auto max-w-5xl px-8 py-7">
      <div className="mb-5 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Chapters</h1>
          <p className="mt-1 text-sm text-muted">
            {chapters ? `${chapters.length} chapters` : "Loading…"} — script & timeline, editable text.
          </p>
        </div>
      </div>

      {/* toolbar */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-xs text-faint">Mode</span>
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className="rounded-lg border border-border-strong bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
        >
          {MODES.map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <button
          onClick={produce}
          className="rounded-lg border border-border-strong px-4 py-2 text-sm text-muted transition hover:text-text"
        >
          Produce chapters
        </button>
        <button
          onClick={exportBook}
          disabled={!allRendered}
          title={allRendered ? "Export the audiobook" : "Available once every chapter is rendered"}
          className="rounded-lg bg-accent-strong px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent disabled:opacity-40"
        >
          Export audiobook
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad">{error}</div>
      )}

      <div className="flex flex-col gap-2">
        {chapters?.map((c) => (
          <ChapterRow
            key={c.chapter_id}
            info={c}
            mode={mode}
            characters={characters}
            jobs={jobs}
            onRendered={load}
            onOpenTimeline={setTimelineCid}
          />
        ))}
        {chapters && !chapters.length && (
          <p className="py-10 text-center text-sm text-faint">
            No chapters yet — they're detected during extraction.
          </p>
        )}
      </div>

      {timelineCid && <TimelineEditor cid={timelineCid} jobs={jobs} onClose={() => setTimelineCid(null)} />}
    </div>
  );
}
