import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ChapterDetail, type JobView, type TimelineData, type TimelineSeg } from "../lib/api";
import { speakerColor } from "../lib/labels";
import { TimelinePlayer } from "../lib/timelineAudio";
import { TimelineClip } from "./TimelineClip";
import { ClipInspector } from "./ClipInspector";

// Lanes stacked top -> bottom (bottom group: narrator, speaker, ambience, sfx; music on top).
const LANES: { key: string; label: string; color: string }[] = [
  { key: "music", label: "Music", color: "#9DAAF2" },
  { key: "sfx", label: "SFX", color: "#f4db7d" },
  { key: "ambience", label: "Ambient", color: "#27c498" },
  { key: "characters", label: "Speaker", color: "#5b8cff" },
  { key: "narrator", label: "Narrator", color: "#9aa3b2" },
];
const LABEL_W = 110;
const LANE_H = 78;

function fmtTime(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function TimelineEditor({ cid, jobs, onClose }: { cid: string; jobs: JobView[]; onClose: () => void }) {
  const [chapter, setChapter] = useState<ChapterDetail | null>(null);
  const [tl, setTl] = useState<TimelineData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [zoom, setZoom] = useState(4);
  const [playing, setPlaying] = useState(false);
  const [curMs, setCurMs] = useState(0);
  const [showWave, setShowWave] = useState(true);
  const [waveAlpha, setWaveAlpha] = useState(0.25);

  const playerRef = useRef<TimelinePlayer | null>(null);
  const getPlayer = () => (playerRef.current ??= new TimelinePlayer());
  const rafRef = useRef<number>(0);
  const totalRef = useRef(0);

  const reload = useCallback(() => api.getTimeline(cid).then(setTl).catch(() => {}), [cid]);

  useEffect(() => {
    api.getChapter(cid).then(setChapter).catch(() => {});
    reload();
    api.getSettings().then((s) => {
      setShowWave(s["ui.show_waveforms"] !== false);
      const op = Number(s["ui.waveform_opacity"]);
      if (!Number.isNaN(op)) setWaveAlpha(Math.max(0, Math.min(1, op / 100)));
    }).catch(() => {});
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [cid, reload]);

  // refetch when a render/audio job for this chapter completes
  const lastSig = useRef("");
  useEffect(() => {
    const mine = jobs.filter((j) => j.meta?.chapter_id === cid && (j.state === "done" || j.state === "failed"));
    const sig = mine.map((j) => j.id + j.state).join(",");
    if (sig && sig !== lastSig.current) {
      lastSig.current = sig;
      reload();
      api.getChapter(cid).then(setChapter).catch(() => {});
    }
  }, [jobs, cid, reload]);

  const pxPerMs = (zoom * 12) / 1000;
  const totalMs = tl?.duration_ms ?? 0;
  totalRef.current = totalMs;
  const width = Math.max(900, totalMs * pxPerMs);
  const ticks = useMemo(
    () => Array.from({ length: Math.ceil(totalMs / 1000 / 10) + 1 }, (_, i) => i * 10),
    [totalMs],
  );

  // Live playback driven by the Web Audio mixer (no baked MP3).
  const tick = useCallback(() => {
    const p = playerRef.current;
    if (p) {
      const ms = p.positionMs();
      setCurMs(ms);
      if (p.playing && totalRef.current && ms >= totalRef.current) {
        p.pause();
        setPlaying(false);
        setCurMs(0);
        p.seek(0);
        return;
      }
    }
    rafRef.current = requestAnimationFrame(tick);
  }, []);
  const togglePlay = () => {
    const p = getPlayer();
    if (p.playing) {
      p.pause();
      setPlaying(false);
      cancelAnimationFrame(rafRef.current);
    } else {
      p.play(curMs).then(() => {
        setPlaying(true);
        rafRef.current = requestAnimationFrame(tick);
      });
    }
  };

  // Keep the mixer's segment set in sync with the timeline (edits heard live).
  useEffect(() => {
    if (tl) getPlayer().setSegments(tl.segments);
  }, [tl]);

  useEffect(() => () => {
    cancelAnimationFrame(rafRef.current);
    playerRef.current?.dispose();
  }, []);

  // Spacebar toggles play/pause (ignored while typing in an input/textarea).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" && e.key !== " ") return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      e.preventDefault();
      togglePlay();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Scrub: press-and-drag anywhere on the seek bar / empty lane to drag the
  // playhead. Cheap when paused; while playing we resync the mix on release.
  const beginScrub = (clientX: number, el: HTMLElement) => {
    const rect = el.getBoundingClientRect();
    const p = getPlayer();
    const toMs = (cx: number) => Math.max(0, Math.min(totalRef.current || Infinity, (cx - rect.left) / pxPerMs));
    const apply = (cx: number) => {
      const ms = toMs(cx);
      setCurMs(ms);
      if (!p.playing) p.seek(ms);
    };
    apply(clientX);
    const move = (ev: MouseEvent) => apply(ev.clientX);
    const up = (ev: MouseEvent) => {
      if (p.playing) p.seek(toMs(ev.clientX));
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const persist = (next: TimelineData) => {
    setTl(next);
    api.putTimeline(cid, next).catch(() => {});
  };

  const patchSeg = (id: string, patch: Partial<TimelineSeg>) => {
    if (!tl) return;
    persist({ ...tl, segments: tl.segments.map((s) => (s.id === id ? { ...s, ...patch, edited: true } : s)) });
  };

  // Flag a segment edited + persist the current (post-drag) state to disk.
  const commitSeg = (id: string) => {
    setTl((cur) => {
      if (!cur) return cur;
      const next = { ...cur, segments: cur.segments.map((s) => (s.id === id ? { ...s, edited: true } : s)) };
      api.putTimeline(cid, next).catch(() => {});
      return next;
    });
  };

  // Generic horizontal drag helper: live-updates a segment, commits on release.
  const dragSeg = (e: React.MouseEvent, id: string, onMove: (deltaMs: number) => Partial<TimelineSeg>) => {
    e.stopPropagation();
    setSelected(id);
    const startX = e.clientX;
    const move = (ev: MouseEvent) => {
      const deltaMs = (ev.clientX - startX) / pxPerMs;
      const patch = onMove(deltaMs);
      setTl((cur) => cur && { ...cur, segments: cur.segments.map((s) => (s.id === id ? { ...s, ...patch } : s)) });
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      commitSeg(id);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const MIN_DUR = 200; // ms — smallest clip you can trim to

  // drag the body to move horizontally
  const onClipDown = (e: React.MouseEvent, seg: TimelineSeg) => {
    const orig = seg.start_ms;
    dragSeg(e, seg.id, (d) => ({ start_ms: Math.max(0, orig + d) }));
  };

  // drag a left/right edge to trim length (DaVinci-style)
  const onClipResize = (e: React.MouseEvent, seg: TimelineSeg, edge: "l" | "r") => {
    const oStart = seg.start_ms;
    const oDur = seg.duration_ms;
    dragSeg(e, seg.id, (d) => {
      if (edge === "r") return { duration_ms: Math.max(MIN_DUR, oDur + d) };
      const ns = Math.max(0, Math.min(oStart + d, oStart + oDur - MIN_DUR));
      return { start_ms: ns, duration_ms: oStart + oDur - ns };
    });
  };

  // drag a top-corner handle to set fade in / out
  const onClipFade = (e: React.MouseEvent, seg: TimelineSeg, side: "in" | "out") => {
    const oIn = seg.fade_in_ms;
    const oOut = seg.fade_out_ms;
    dragSeg(e, seg.id, (d) => {
      if (side === "in") {
        const v = Math.max(0, Math.min(seg.duration_ms - seg.fade_out_ms, oIn + d));
        return { fade_in_ms: Math.round(v) };
      }
      const v = Math.max(0, Math.min(seg.duration_ms - seg.fade_in_ms, oOut - d));
      return { fade_out_ms: Math.round(v) };
    });
  };

  const addClip = async (kind: string, lane: string) => {
    const next = await api.addSegment(cid, { kind, lane, start_ms: curMs, duration_ms: 4000, prompt: "" });
    setTl(next);
    setSelected(next.segments[next.segments.length - 1]?.id ?? null);
  };

  // Map segment_id -> live progress for in-flight audio generation jobs.
  // null = not generating, -1 = indeterminate, 0..1 = fraction done.
  const genProgress = useMemo(() => {
    const m = new Map<string, number>();
    for (const j of jobs) {
      const sid = j.meta?.segment_id as string | undefined;
      if (sid && (j.state === "running" || j.state === "pending")) m.set(sid, j.progress);
    }
    return m;
  }, [jobs]);

  const selSeg = tl?.segments.find((s) => s.id === selected) ?? null;
  const hasAudio = !!tl?.segments.some((s) => s.audio_url);

  // Playback is a live mix, so there's no manual "re-render" — but the exported
  // audiobook still reads the baked chapter master. Bake it from the (edited)
  // timeline in the background on close so export stays in sync.
  const closeEditor = () => {
    if (tl?.segments.some((s) => s.edited)) api.renderTimeline(cid).catch(() => {});
    onClose();
  };
  const closeRef = useRef(closeEditor);
  closeRef.current = closeEditor;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-bg">
      <header className="relative flex h-12 shrink-0 items-center gap-3 border-b border-border bg-surface px-4">
        <button onClick={closeEditor} className="rounded-md border border-border-strong px-3 py-1 text-sm text-muted hover:text-text">
          ← Back
        </button>

        {/* round play/pause, centered over the header */}
        <button
          onClick={togglePlay}
          disabled={!hasAudio}
          title="Play / pause (Space)"
          className="absolute left-1/2 top-1/2 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-accent-strong text-sm text-white shadow-md transition hover:bg-accent disabled:opacity-40"
        >
          {playing ? "⏸" : <span className="ml-0.5">▶</span>}
        </button>

        <span className="font-mono text-xs text-muted">
          {fmtTime(curMs)} / {fmtTime(totalMs)}
        </span>
        <span className="text-sm font-semibold">{chapter ? `${chapter.number}. ${chapter.title}` : cid}</span>
        <div className="ml-auto flex items-center gap-3 text-xs text-faint">
          <button onClick={() => addClip("ambience", "ambience")} className="rounded border border-border-strong px-2 py-1 hover:text-text">+ Ambient</button>
          <button onClick={() => addClip("sfx", "sfx")} className="rounded border border-border-strong px-2 py-1 hover:text-text">+ SFX</button>
          <button onClick={() => addClip("music", "music")} className="rounded border border-border-strong px-2 py-1 hover:text-text">+ Music</button>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={showWave} onChange={(e) => setShowWave(e.target.checked)} /> wave
          </label>
          <span>zoom</span>
          <input type="range" min={1} max={12} value={zoom} onChange={(e) => setZoom(parseInt(e.target.value))} className="w-24 accent-[var(--color-accent)]" />
        </div>
      </header>

      {/* seek bar — press and drag to scrub */}
      <div
        className="relative h-6 shrink-0 cursor-ew-resize border-b border-border bg-surface-2"
        style={{ marginLeft: LABEL_W }}
        onMouseDown={(e) => beginScrub(e.clientX, e.currentTarget)}
      >
        <div className="absolute inset-0" style={{ width }}>
          <div className="absolute top-0 h-full bg-accent/15" style={{ width: curMs * pxPerMs }} />
          <div className="absolute top-0 h-full w-0.5 bg-accent" style={{ left: curMs * pxPerMs }} />
          {/* grabbable playhead knob */}
          <div
            className="absolute top-0 h-0 w-0 -translate-x-1/2 border-x-[5px] border-t-[7px] border-x-transparent border-t-accent"
            style={{ left: curMs * pxPerMs }}
          />
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 overflow-auto">
            <div style={{ width: width + LABEL_W }}>
            {/* ruler */}
            <div className="sticky top-0 z-10 flex h-6 items-end border-b border-border bg-surface-2" style={{ paddingLeft: LABEL_W }}>
              <div className="relative h-full" style={{ width }}>
                {ticks.map((t) => (
                  <div key={t} className="absolute top-0 h-full border-l border-border pl-1 text-[10px] text-faint" style={{ left: t * (zoom * 12) }}>
                    {t}s
                  </div>
                ))}
              </div>
            </div>

            {/* lanes */}
            <div className="relative">
              {/* global playhead across lanes */}
              <div className="pointer-events-none absolute top-0 z-20 w-0.5 bg-accent" style={{ left: LABEL_W + curMs * pxPerMs, height: LANES.length * LANE_H }} />
              {LANES.map((lane) => {
                const segs = tl?.segments.filter((s) => s.lane === lane.key) ?? [];
                return (
                  <div key={lane.key} className="flex border-b border-border" style={{ height: LANE_H }}>
                    <div className="sticky left-0 z-10 flex w-[110px] shrink-0 items-center border-r border-border bg-surface px-3 text-xs font-medium" style={{ color: lane.color }}>
                      {lane.label}
                    </div>
                    <div
                      className="relative flex-1"
                      style={{ width }}
                      onMouseDown={(e) => {
                        setSelected(null);
                        beginScrub(e.clientX, e.currentTarget);
                      }}
                    >
                      {segs.map((s) => (
                        <TimelineClip
                          key={s.id}
                          seg={s}
                          color={lane.key === "characters" ? speakerColor(s.speaker_id ?? "") : lane.color}
                          pxPerMs={pxPerMs}
                          laneH={LANE_H}
                          selected={selected === s.id}
                          showWave={showWave}
                          waveAlpha={waveAlpha}
                          onDown={(e) => onClipDown(e, s)}
                          onResize={(e, edge) => onClipResize(e, s, edge)}
                          onFade={(e, side) => onClipFade(e, s, side)}
                          genProgress={genProgress.get(s.id) ?? null}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          </div>

          <footer className="flex h-9 shrink-0 items-center border-t border-border bg-surface px-4 text-xs text-faint">
            <span>{tl ? `${tl.segments.length} clips` : "loading…"} · drag to move · drag edges to trim · drag corner knobs to fade · drag the ruler to scrub · plays live</span>
          </footer>
        </div>

        {/* inspector */}
        {selSeg && (
          <ClipInspector
            cid={cid}
            seg={selSeg}
            genProgress={genProgress.get(selSeg.id) ?? null}
            onPatch={(patch) => patchSeg(selSeg.id, patch)}
            onDelete={async () => {
              setSelected(null);
              setTl(await api.deleteSegment(cid, selSeg.id));
            }}
            onRegenerate={(prompt, duration_ms) => api.regenerateSegment(cid, selSeg.id, { prompt, duration_ms })}
            onClose={() => setSelected(null)}
          />
        )}
      </div>
    </div>
  );
}
