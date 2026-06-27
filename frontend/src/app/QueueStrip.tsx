import { api, type JobView } from "../lib/api";

const STATE_COLOR: Record<JobView["state"], string> = {
  pending: "text-muted",
  running: "text-accent",
  done: "text-good",
  failed: "text-bad",
  cancelled: "text-faint",
};

function JobChip({ job }: { job: JobView }) {
  const pct = job.progress < 0 ? null : Math.round(job.progress * 100);
  const active = job.state === "running" || job.state === "pending";
  return (
    <div className="flex min-w-[200px] items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 py-1.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-xs font-medium text-text">{job.title}</span>
          <span className={`text-[10px] uppercase tracking-wide ${STATE_COLOR[job.state]}`}>
            {job.state}
          </span>
          {(() => {
            const est = job.meta?.est as { usd: number; free: boolean } | undefined;
            if (!est) return null;
            return (
              <span className="shrink-0 rounded bg-elevated px-1.5 text-[9px] font-semibold text-warn" title="estimated LLM cost">
                {est.free ? "free" : `~$${est.usd.toFixed(2)}`}
              </span>
            );
          })()}
        </div>
        <div className="mt-1 h-1 overflow-hidden rounded-full bg-elevated">
          <div
            className={`h-full rounded-full transition-all ${job.state === "failed" ? "bg-bad" : "bg-accent"} ${
              pct == null && active ? "animate-pulse w-1/3" : ""
            }`}
            style={pct == null ? undefined : { width: `${pct}%` }}
          />
        </div>
        {job.detail && <div className="mt-0.5 truncate text-[10px] text-faint">{job.detail}</div>}
      </div>
      {active && (
        <button
          onClick={() => api.cancelJob(job.id).catch(() => {})}
          className="text-faint transition hover:text-bad"
          title="Cancel"
        >
          ✕
        </button>
      )}
    </div>
  );
}

export function QueueStrip({ jobs }: { jobs: JobView[] }) {
  // Show active and recently-failed jobs; completed ones drop off.
  const list = jobs.filter(
    (j) => j.state === "running" || j.state === "pending" || j.state === "failed",
  );

  if (!list.length) {
    return (
      <footer className="flex h-9 shrink-0 items-center border-t border-border bg-surface px-4 text-xs text-faint">
        Queue idle
      </footer>
    );
  }

  return (
    <footer className="flex h-14 shrink-0 items-center gap-2 overflow-x-auto border-t border-border bg-surface px-4">
      {list.map((j) => (
        <JobChip key={j.id} job={j} />
      ))}
    </footer>
  );
}
