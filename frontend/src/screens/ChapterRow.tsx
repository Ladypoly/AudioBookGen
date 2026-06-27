import { useEffect, useRef, useState } from "react";
import { api, mediaUrl, type CharacterView, type ChapterDetail, type ChapterInfo, type JobView } from "../lib/api";
import { TagEditor } from "./TagEditor";

export function ChapterRow({
  info,
  mode,
  characters,
  jobs,
  onRendered,
  onOpenTimeline,
}: {
  info: ChapterInfo;
  mode: string;
  characters: CharacterView[];
  jobs: JobView[];
  onRendered: () => void;
  onOpenTimeline: (cid: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ChapterDetail | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !detail) setDetail(await api.getChapter(info.chapter_id));
  };

  // Refetch detail when a summary/render job for this chapter completes.
  const lastDone = useRef("");
  useEffect(() => {
    if (!open) return;
    const mine = jobs.filter(
      (j) => j.meta?.chapter_id === info.chapter_id && (j.state === "done" || j.state === "failed"),
    );
    const sig = mine.map((j) => j.id + j.state).join(",");
    if (sig && sig !== lastDone.current) {
      lastDone.current = sig;
      setSummarizing(false);
      api.getChapter(info.chapter_id).then(setDetail).catch(() => {});
    }
  }, [jobs, open, info.chapter_id]);

  const summarize = async () => {
    setSummarizing(true);
    await api.summarizeChapter(info.chapter_id).catch(() => setSummarizing(false));
  };

  const render = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await api.renderChapter(info.chapter_id, mode);
  };

  const play = (e: React.MouseEvent) => {
    e.stopPropagation();
    const url = mediaUrl(info.audio_url);
    if (url && audioRef.current) {
      audioRef.current.src = url;
      audioRef.current.play().catch(() => {});
    }
  };

  return (
    <div className="overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface">
      <div
        onClick={toggle}
        className="flex cursor-pointer items-center gap-3 px-4 py-3 transition hover:bg-surface-2"
      >
        <span className="text-faint">{open ? "▾" : "▸"}</span>
        <span className={`font-semibold ${info.rendered ? "text-good" : "text-text"}`}>
          {info.number}. {info.title}
        </span>
        <span className="text-xs text-faint">{info.rendered ? "✓ rendered" : `${info.lines} lines`}</span>
        <div className="ml-auto flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          {info.rendered && (
            <button onClick={play} className="rounded-md border border-border-strong px-2 py-1 text-xs text-muted hover:text-text">
              ▶ Play
            </button>
          )}
          <button onClick={render} className="rounded-md border border-border-strong px-3 py-1 text-xs text-muted hover:text-text">
            Render
          </button>
        </div>
      </div>

      {open && (
        <div className="border-t border-border px-4 py-3">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide text-accent">Script · tag editor</span>
            <button
              onClick={() => onOpenTimeline(info.chapter_id)}
              className="rounded-lg bg-accent-strong px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent"
            >
              ⧉ Open timeline editor
            </button>
          </div>
          {/* summary + location header */}
          {detail && (
            <div className="mb-3 rounded-lg border border-border bg-surface-2 px-3 py-2">
              {detail.summary || detail.location ? (
                <div className="flex flex-col gap-1">
                  {detail.location && (
                    <div className="text-xs">
                      <span className="font-semibold text-good">📍 {detail.location}</span>
                    </div>
                  )}
                  {detail.summary && <p className="text-xs text-muted">{detail.summary}</p>}
                  <button onClick={summarize} disabled={summarizing} className="self-start text-[10px] text-faint hover:text-text">
                    {summarizing ? "regenerating…" : "↻ regenerate"}
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-faint">No summary yet.</span>
                  <button
                    onClick={summarize}
                    disabled={summarizing}
                    className="rounded-md border border-border-strong px-2 py-1 text-[11px] text-muted hover:text-text disabled:opacity-50"
                  >
                    {summarizing ? "Summarizing…" : "✨ Generate summary"}
                  </button>
                </div>
              )}
            </div>
          )}

          {!detail ? (
            <p className="text-sm text-faint">Loading…</p>
          ) : (
            <TagEditor
              cid={info.chapter_id}
              chapter={detail}
              characters={characters}
              onChange={(c) => {
                setDetail(c);
                onRendered(); // line count may have changed
              }}
            />
          )}
        </div>
      )}
      <audio ref={audioRef} className="hidden" />
    </div>
  );
}
