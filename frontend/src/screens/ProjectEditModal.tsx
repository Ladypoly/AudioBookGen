import { useRef, useState } from "react";
import { api, mediaUrl, type ProjectSummary } from "../lib/api";

const inp = "w-full rounded-md border border-border-strong bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent";

export function ProjectEditModal({
  project,
  onClose,
  onChanged,
  onDuplicated,
}: {
  project: ProjectSummary;
  onClose: () => void;
  onChanged: () => void;            // refetch the list after edit/cover/delete
  onDuplicated: (p: ProjectSummary) => void;
}) {
  const [title, setTitle] = useState(project.title);
  const [author, setAuthor] = useState(project.author);
  const [cover, setCover] = useState(mediaUrl(project.cover));
  const [busy, setBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const wrap = async (fn: () => Promise<void>) => {
    setErr(null);
    setBusy(true);
    try {
      await fn();
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const pickCover = (file: File) =>
    wrap(async () => {
      const p = await api.setProjectCover(project.id, file);
      setCover(mediaUrl(p.cover));
      onChanged();
    });

  const save = () =>
    wrap(async () => {
      await api.updateProject(project.id, { title: title.trim(), author: author.trim() });
      onChanged();
      onClose();
    });

  const duplicate = () =>
    wrap(async () => {
      const p = await api.duplicateProject(project.id);
      onChanged();
      onDuplicated(p);
      onClose();
    });

  const del = () =>
    wrap(async () => {
      await api.deleteProject(project.id);
      onChanged();
      onClose();
    });

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-base font-semibold">Edit project</h2>
          <button onClick={onClose} className="text-faint hover:text-text">✕</button>
        </header>

        <div className="flex gap-4 p-5">
          {/* cover */}
          <div className="shrink-0">
            <div className="h-[180px] w-[135px] overflow-hidden rounded-lg border border-border bg-elevated">
              {cover ? (
                <img src={cover} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-3xl text-faint">📖</div>
              )}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && pickCover(e.target.files[0])}
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              className="mt-2 w-full rounded-md border border-border-strong px-2 py-1 text-xs text-muted hover:text-text disabled:opacity-50"
            >
              Change cover…
            </button>
          </div>

          {/* fields */}
          <div className="flex min-w-0 flex-1 flex-col gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-faint">Title</span>
              <input className={inp} value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-faint">Author</span>
              <input className={inp} value={author} onChange={(e) => setAuthor(e.target.value)} />
            </label>
            {err && <p className="text-xs text-bad">{err}</p>}
          </div>
        </div>

        <footer className="flex items-center justify-between gap-2 border-t border-border px-5 py-3">
          <div className="flex gap-2">
            <button
              onClick={duplicate}
              disabled={busy}
              className="rounded-md border border-border-strong px-3 py-1.5 text-sm text-muted hover:text-text disabled:opacity-50"
            >
              Duplicate
            </button>
            {confirmDel ? (
              <button
                onClick={del}
                disabled={busy}
                className="rounded-md border border-bad bg-bad/15 px-3 py-1.5 text-sm font-semibold text-bad hover:bg-bad/25 disabled:opacity-50"
              >
                Confirm delete?
              </button>
            ) : (
              <button
                onClick={() => setConfirmDel(true)}
                disabled={busy}
                className="rounded-md border border-bad/50 px-3 py-1.5 text-sm text-bad hover:bg-bad/10 disabled:opacity-50"
              >
                Delete
              </button>
            )}
          </div>
          <button
            onClick={save}
            disabled={busy || !title.trim()}
            className="rounded-md bg-accent-strong px-4 py-1.5 text-sm font-semibold text-white hover:bg-accent disabled:opacity-50"
          >
            Save
          </button>
        </footer>
      </div>
    </div>
  );
}
