import { useEffect, useMemo, useRef, useState } from "react";
import { api, isElectron, mediaUrl, pickBookFile, type Inspected, type JobView } from "../lib/api";

type Phase = "pick" | "loading" | "confirm" | "extracting";

// Emoji per extraction step — shown inside an animated spinner badge.
const STEP_ICON: Record<string, string> = {
  prepare: "🧹",
  cast: "📖",
  research: "🔎",
  style: "🎨",
  portraits: "🖼️",
  voicelines: "💬",
  finalize: "🧩",
  done: "✅",
};

function Bar({ label, frac, indeterminate, color }: {
  label: string;
  frac: number;            // 0..1
  indeterminate?: boolean;
  color?: string;
}) {
  const c = color ?? "var(--color-accent)";
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px]">
        <span className="text-muted">{label}</span>
        {!indeterminate && <span className="font-mono text-faint">{Math.round(frac * 100)}%</span>}
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-elevated">
        {indeterminate ? (
          <div className="h-full w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] rounded-full" style={{ background: c }} />
        ) : (
          <div className="h-full rounded-full transition-[width] duration-300" style={{ width: `${Math.max(2, frac * 100)}%`, background: c }} />
        )}
      </div>
    </div>
  );
}

function Backdrop({ children }: { children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-[560px] max-w-[92vw] rounded-2xl border border-border bg-surface shadow-2xl">
        {children}
      </div>
    </div>
  );
}

export function NewAudioDrama({
  jobs,
  onClose,
  onCreated,
}: {
  jobs: JobView[];
  onClose: () => void;
  onCreated: (projectId: string) => void;
}) {
  const [phase, setPhase] = useState<Phase>("pick");
  const [error, setError] = useState<string | null>(null);
  const [inspected, setInspected] = useState<Inspected | null>(null);
  const [title, setTitle] = useState("");
  const [author, setAuthor] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [autoGen, setAutoGen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const coverRef = useRef<HTMLInputElement>(null);

  const applyInspected = (d: Inspected) => {
    setInspected(d);
    setTitle(d.title);
    setAuthor(d.author);
    setPhase("confirm");
  };

  const pickViaElectron = async () => {
    const path = await pickBookFile();
    if (!path) return;
    setPhase("loading");
    try {
      applyInspected(await api.inspectPath(path));
    } catch (e) {
      setError(String(e));
      setPhase("pick");
    }
  };

  const onFileChosen = async (file: File) => {
    setPhase("loading");
    try {
      applyInspected(await api.inspectUpload(file));
    } catch (e) {
      setError(String(e));
      setPhase("pick");
    }
  };

  const onCoverChosen = async (file: File) => {
    if (!inspected) return;
    try {
      const { cover } = await api.replaceCover(inspected.token, file);
      setInspected({ ...inspected, cover: cover + `?t=${Date.now()}` });
    } catch (e) {
      setError(String(e));
    }
  };

  const confirm = async () => {
    if (!inspected) return;
    try {
      const { job_id } = await api.createProject({
        token: inspected.token,
        title,
        author,
        subtitle: inspected.subtitle,
      });
      setJobId(job_id);
      setPhase("extracting");
    } catch (e) {
      setError(String(e));
    }
  };

  // Watch the extraction job; on completion, enter the project.
  const job = useMemo(() => jobs.find((j) => j.id === jobId) ?? null, [jobs, jobId]);
  useEffect(() => {
    if (phase === "extracting" && job?.state === "done") {
      const pid = (job.meta?.project_id as string) || "";
      if (autoGen) api.generateMissing().catch(() => {});   // batch portraits + voices
      const t = setTimeout(() => onCreated(pid), 700);
      return () => clearTimeout(t);
    }
  }, [phase, job, onCreated, autoGen]);

  return (
    <Backdrop>
      {/* header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <h2 className="text-lg font-semibold">New AudioDrama</h2>
        {phase !== "extracting" && (
          <button onClick={onClose} className="text-faint transition hover:text-text">
            ✕
          </button>
        )}
      </div>

      <div className="p-6">
        {error && (
          <div className="mb-4 rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{error}</div>
        )}

        {(phase === "pick" || phase === "loading") && (
          <div className="flex flex-col items-center gap-4 py-6 text-center">
            <p className="text-sm text-muted">Choose a book file — PDF, EPUB, TXT or DOCX.</p>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.epub,.txt,.docx,.doc,.md"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && onFileChosen(e.target.files[0])}
            />
            <button
              disabled={phase === "loading"}
              onClick={() => (isElectron() ? pickViaElectron() : fileRef.current?.click())}
              className="rounded-lg bg-accent-strong px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-accent disabled:opacity-50"
            >
              {phase === "loading" ? "Reading file…" : "Choose file…"}
            </button>
          </div>
        )}

        {phase === "confirm" && inspected && (
          <div className="flex gap-5">
            <div className="shrink-0">
              <div className="h-[220px] w-[165px] overflow-hidden rounded-lg border border-border bg-elevated">
                {inspected.cover ? (
                  <img src={mediaUrl(inspected.cover)} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-4xl text-faint">📖</div>
                )}
              </div>
              <input
                ref={coverRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && onCoverChosen(e.target.files[0])}
              />
              <button
                onClick={() => coverRef.current?.click()}
                className="mt-2 w-full rounded-lg border border-border-strong py-1.5 text-xs text-muted transition hover:text-text"
              >
                Change cover…
              </button>
            </div>

            <div className="flex flex-1 flex-col gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-faint">Title</span>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="rounded-lg border border-border-strong bg-bg px-3 py-2 text-sm outline-none focus:border-accent"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-faint">Author</span>
                <input
                  value={author}
                  onChange={(e) => setAuthor(e.target.value)}
                  className="rounded-lg border border-border-strong bg-bg px-3 py-2 text-sm outline-none focus:border-accent"
                />
              </label>
              {inspected.subtitle && (
                <p className="text-xs text-faint">Subtitle: {inspected.subtitle}</p>
              )}
              <label className="mt-auto flex cursor-pointer items-start gap-2 rounded-lg border border-border bg-surface-2 p-2.5">
                <input
                  type="checkbox"
                  checked={autoGen}
                  onChange={(e) => setAutoGen(e.target.checked)}
                  className="mt-0.5 accent-[var(--color-accent)]"
                />
                <span className="text-xs text-muted">
                  Auto-generate character portraits &amp; voices after extraction
                  <span className="block text-faint">Needs ComfyUI running · runs in the background (GPU-heavy)</span>
                </span>
              </label>
              <p className="text-xs text-faint">From {inspected.filename}</p>
            </div>
          </div>
        )}

        {phase === "extracting" && (
          <ExtractingView job={job} />
        )}
      </div>

      {/* footer */}
      {phase === "confirm" && (
        <div className="flex justify-end gap-3 border-t border-border px-6 py-4">
          <button onClick={onClose} className="rounded-lg border border-border-strong px-4 py-2 text-sm text-muted transition hover:text-text">
            Cancel
          </button>
          <button
            disabled={!title.trim()}
            onClick={confirm}
            className="rounded-lg bg-accent-strong px-5 py-2 text-sm font-semibold text-white transition hover:bg-accent disabled:opacity-50"
          >
            Create & extract
          </button>
        </div>
      )}
    </Backdrop>
  );
}

function ExtractingView({ job }: { job: JobView | null }) {
  const steps = (job?.meta?.steps as { key: string; label: string }[]) ?? [];
  const activeKey = (job?.meta?.step as string) ?? "prepare";
  const activeIdx = Math.max(0, steps.findIndex((s) => s.key === activeKey));
  const active = steps[activeIdx];
  const failed = job?.state === "failed";
  const done = job?.state === "done";

  // Current-task progress: backend sends a fraction (e.g. chapter 39/59) or -1
  // for indeterminate. Overall progress spans the steps + the within-step fraction.
  const within = job && job.progress >= 0 ? Math.min(1, job.progress) : 0;
  const hasTaskFrac = !!job && job.progress >= 0 && !done;
  const denom = Math.max(1, steps.length - 1);   // last step ("done") = 100%
  const overall = done ? 1 : Math.min(1, (activeIdx + within) / denom);

  return (
    <div className="py-2">
      {/* animated status badge */}
      <div className="mb-5 flex items-center justify-center">
        <div className="relative flex h-28 w-28 items-center justify-center">
          {!done && !failed && (
            <span
              className="absolute inset-0 animate-spin rounded-full"
              style={{ background: "conic-gradient(var(--color-accent), transparent 70%)", WebkitMask: "radial-gradient(closest-side, transparent 78%, black 80%)", mask: "radial-gradient(closest-side, transparent 78%, black 80%)" }}
            />
          )}
          <div className={`flex h-24 w-24 items-center justify-center rounded-full border ${failed ? "border-bad/50" : "border-border"} bg-elevated`}>
            <span className={`text-4xl ${done || failed ? "" : "animate-pulse"}`}>
              {failed ? "⚠️" : STEP_ICON[activeKey] ?? "⏳"}
            </span>
          </div>
        </div>
      </div>
      <p className="mb-4 text-center text-sm font-medium text-text">{active?.label ?? activeKey}</p>

      {/* two progress bars */}
      <div className="mb-5 flex flex-col gap-3">
        <Bar label="Overall" frac={overall} color="var(--color-good)" />
        <Bar
          label={job?.detail || (done ? "Finished" : "Working…")}
          frac={within}
          indeterminate={!hasTaskFrac && !done}
        />
      </div>

      <ol className="flex flex-col gap-2">
        {steps.map((s, i) => {
          const sdone = i < activeIdx || done;
          const current = i === activeIdx && !done;
          return (
            <li key={s.key} className="flex items-center gap-3 text-sm">
              <span
                className={[
                  "flex h-5 w-5 items-center justify-center rounded-full text-[10px]",
                  sdone ? "bg-good text-black" : current ? "bg-accent text-white" : "bg-elevated text-faint",
                  current && !failed ? "animate-pulse" : "",
                ].join(" ")}
              >
                {sdone ? "✓" : i + 1}
              </span>
              <span className={sdone ? "text-muted" : current ? "text-text" : "text-faint"}>{s.label}</span>
            </li>
          );
        })}
      </ol>

      {failed && <p className="mt-3 text-sm text-bad">Extraction failed: {job?.error}</p>}
    </div>
  );
}
