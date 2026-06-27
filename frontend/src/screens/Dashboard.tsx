import { useEffect, useState } from "react";
import { api, mediaUrl, type JobView, type ProjectSummary } from "../lib/api";
import { NewAudioDrama } from "./NewAudioDrama";
import { ProjectEditModal } from "./ProjectEditModal";

function ProjectCard({ p, onOpen, onEdit }: {
  p: ProjectSummary;
  onOpen: (p: ProjectSummary) => void;
  onEdit: (p: ProjectSummary) => void;
}) {
  const cover = mediaUrl(p.cover);
  return (
    <div className="group relative flex w-[230px] flex-col overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface transition hover:border-border-strong hover:bg-surface-2">
      <button
        onClick={(e) => { e.stopPropagation(); onEdit(p); }}
        title="Edit / delete / duplicate"
        className="absolute right-2 top-2 z-10 flex h-7 w-7 items-center justify-center rounded-md border border-border-strong bg-surface/80 text-faint opacity-0 backdrop-blur transition hover:text-text group-hover:opacity-100"
      >
        ✎
      </button>
      <button onClick={() => onOpen(p)} className="flex flex-1 flex-col text-left">
        <div className="aspect-[3/4] w-full overflow-hidden bg-elevated">
          {cover ? (
            <img
              src={cover}
              alt=""
              className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-4xl text-faint">📖</div>
          )}
        </div>
        <div className="flex flex-1 flex-col gap-1 p-3">
          <span className="line-clamp-2 text-sm font-semibold leading-snug text-text">{p.title}</span>
          {p.author && <span className="text-xs text-muted">{p.author}</span>}
          <span className="mt-auto pt-1 text-xs text-faint">{p.character_count} characters</span>
        </div>
      </button>
    </div>
  );
}

export function Dashboard({
  onOpen,
  jobs,
  onCreated,
}: {
  onOpen: (p: ProjectSummary) => void;
  jobs: JobView[];
  onCreated: (projectId: string) => void;
}) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<ProjectSummary | null>(null);

  const reload = () => api.listProjects().then(setProjects).catch((e) => setError(String(e)));
  useEffect(() => { reload(); }, []);

  return (
    <div className="mx-auto max-w-6xl px-8 py-7">
      <div className="mb-7 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-1 text-sm text-muted">Your audio drama projects</p>
        </div>
        <button
          className="flex items-center gap-2 rounded-lg bg-accent-strong px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-accent-strong/20 transition hover:bg-accent"
          onClick={() => setShowNew(true)}
        >
          <span className="text-lg leading-none">+</span> New AudioDrama
        </button>
      </div>

      {showNew && (
        <NewAudioDrama jobs={jobs} onClose={() => setShowNew(false)} onCreated={onCreated} />
      )}

      {error && (
        <div className="rounded-lg border border-bad/40 bg-bad/10 px-4 py-3 text-sm text-bad">
          Could not reach backend: {error}
        </div>
      )}

      {projects && projects.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed border-border-strong py-20 text-center">
          <div className="text-4xl">🎙️</div>
          <p className="mt-3 text-sm text-muted">No projects yet — create one from a book file.</p>
        </div>
      )}

      {projects === null && !error && <p className="text-sm text-faint">Loading…</p>}

      <div className="flex flex-wrap gap-5">
        {projects?.map((p) => (
          <ProjectCard key={p.id} p={p} onOpen={onOpen} onEdit={setEditing} />
        ))}
      </div>

      {editing && (
        <ProjectEditModal
          project={editing}
          onClose={() => setEditing(null)}
          onChanged={reload}
          onDuplicated={() => reload()}
        />
      )}
    </div>
  );
}
