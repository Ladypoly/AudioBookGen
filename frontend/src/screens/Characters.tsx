import { useEffect, useRef, useState } from "react";
import type { ActiveProject } from "../app/App";
import { api, type CharacterView, type JobView } from "../lib/api";
import { CharacterCard } from "./CharacterCard";
import { CharacterEditModal } from "./CharacterEditModal";
import { Placeholder } from "./Placeholder";

export function Characters({
  project,
  jobs,
}: {
  project: ActiveProject | null;
  jobs: JobView[];
}) {
  const [chars, setChars] = useState<CharacterView[] | null>(null);
  const [editing, setEditing] = useState<CharacterView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.listCharacters().then(setChars).catch((e) => setError(String(e)));

  useEffect(() => {
    if (project) load();
  }, [project]);

  // Refetch when a portrait/voice/batch job advances (paths get written as they
  // complete, so cards fill in progressively).
  const refetchSig = useRef("");
  const batch = jobs.find((j) => j.kind === "batch");
  const batching = batch?.state === "running" || batch?.state === "pending";
  useEffect(() => {
    const done = jobs.filter(
      (j) => (j.kind === "portrait" || j.kind === "voice") && j.state === "done",
    ).length;
    const sig = `${done}|${batch?.state ?? ""}|${batch ? Math.round(batch.progress * 100) : ""}`;
    if (sig !== refetchSig.current) {
      refetchSig.current = sig;
      if (project) load();
    }
  }, [jobs, project, batch?.state, batch?.progress]);

  if (!project) return <Placeholder title="Characters" note="Open a project from the Dashboard first." />;

  return (
    <div className="mx-auto max-w-[1800px] px-8 py-7">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Characters</h1>
          <p className="mt-1 text-sm text-muted">
            {chars ? `${chars.length} characters` : "Loading…"} — edit any card, add age variations, assign voices.
          </p>
        </div>
        <button
          onClick={() => api.generateMissing().catch((e) => setError(String(e)))}
          disabled={batching}
          title="Generate every missing portrait, then every missing voice"
          className="rounded-lg bg-accent-strong px-4 py-2 text-sm font-semibold text-white hover:bg-accent disabled:opacity-50"
        >
          {batching
            ? `Generating… ${batch ? Math.round(batch.progress * 100) : 0}%`
            : "Generate missing"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad">{error}</div>
      )}

      <div className="grid gap-5 [grid-template-columns:repeat(auto-fill,minmax(290px,1fr))]">
        {chars
          ?.slice()
          .sort((a, b) => b.spoken_lines - a.spoken_lines)
          .map((c) => (
            <CharacterCard key={c.character_id} c={c} onEdit={() => setEditing(c)} onChanged={load} />
          ))}
      </div>

      {editing && (
        <CharacterEditModal
          c={editing}
          others={(chars ?? []).filter((x) => x.character_id !== editing.character_id)}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}
    </div>
  );
}
