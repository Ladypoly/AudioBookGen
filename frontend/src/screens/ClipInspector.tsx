import { useEffect, useState } from "react";
import type { TimelineSeg } from "../lib/api";

const num = "w-full rounded-md border border-border-strong bg-bg px-2 py-1 text-sm text-text outline-none focus:border-accent";

export function ClipInspector({
  seg,
  genProgress,
  onPatch,
  onDelete,
  onRegenerate,
  onClose,
}: {
  cid: string;
  seg: TimelineSeg;
  genProgress: number | null; // null=idle, -1=indeterminate, 0..1=fraction
  onPatch: (patch: Partial<TimelineSeg>) => void;
  onDelete: () => void;
  onRegenerate: (prompt: string, durationMs: number) => void;
  onClose: () => void;
}) {
  const isVoice = seg.kind === "voice";
  const [prompt, setPrompt] = useState(seg.prompt);
  const [durS, setDurS] = useState((seg.duration_ms / 1000).toFixed(1));

  useEffect(() => {
    setPrompt(seg.prompt);
  }, [seg.id]);

  // Keep the Length field in sync when the clip is resized by dragging its edge.
  useEffect(() => {
    setDurS((seg.duration_ms / 1000).toFixed(1));
  }, [seg.duration_ms]);

  return (
    <aside className="flex w-72 shrink-0 flex-col gap-3 overflow-y-auto border-l border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-accent">{seg.kind} clip</span>
        <button onClick={onClose} className="text-faint hover:text-text">✕</button>
      </div>

      {isVoice ? (
        <div className="rounded-lg border border-border bg-surface-2 p-2 text-xs">
          <div className="mb-1 text-faint">{seg.speaker_id}</div>
          <div className="text-muted">{seg.text}</div>
        </div>
      ) : (
        <label className="flex flex-col gap-1">
          <span className="text-xs text-faint">Prompt</span>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onBlur={() => prompt !== seg.prompt && onPatch({ prompt })}
            placeholder="describe the sound (English)…"
            className={`${num} h-20 resize-none`}
          />
        </label>
      )}

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-faint">Start (s)</span>
          <input className={num} type="number" step="0.1" value={(seg.start_ms / 1000).toFixed(1)}
            onChange={(e) => onPatch({ start_ms: parseFloat(e.target.value) * 1000 })} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-faint">Length (s)</span>
          <input className={num} type="number" step="0.1" min="0.2" value={durS}
            onChange={(e) => {
              setDurS(e.target.value);
              const v = parseFloat(e.target.value);
              if (!Number.isNaN(v) && v > 0) onPatch({ duration_ms: v * 1000 });
            }} />
        </label>
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-faint">Gain · {seg.gain_db} dB</span>
        <input type="range" min={-30} max={6} step={0.5} value={seg.gain_db}
          onChange={(e) => onPatch({ gain_db: parseFloat(e.target.value) })}
          className="w-full accent-[var(--color-accent)]" />
      </label>

      <div className="grid grid-cols-2 gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-faint">Fade in (ms)</span>
          <input className={num} type="number" step="50" value={seg.fade_in_ms}
            onChange={(e) => onPatch({ fade_in_ms: parseInt(e.target.value) || 0 })} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-faint">Fade out (ms)</span>
          <input className={num} type="number" step="50" value={seg.fade_out_ms}
            onChange={(e) => onPatch({ fade_out_ms: parseInt(e.target.value) || 0 })} />
        </label>
      </div>

      <div className="mt-1 flex flex-col gap-2">
        {isVoice ? (
          <p className="rounded-lg border border-border bg-surface-2 p-2 text-[11px] leading-snug text-faint">
            Gain, fades and position play live. To change the spoken audio, edit the line in the script.
          </p>
        ) : genProgress != null ? (
          <div className="rounded-lg border border-border bg-surface-2 p-3">
            <div className="mb-1.5 flex items-center justify-between text-xs text-muted">
              <span>Generating audio…</span>
              {genProgress >= 0 && <span className="font-mono">{Math.round(genProgress * 100)}%</span>}
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
              {genProgress < 0 ? (
                <div className="h-full w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-accent" />
              ) : (
                <div className="h-full rounded-full bg-accent transition-[width] duration-200" style={{ width: `${Math.max(4, genProgress * 100)}%` }} />
              )}
            </div>
          </div>
        ) : (
          <button
            onClick={() => onRegenerate(prompt, parseFloat(durS) * 1000)}
            disabled={!prompt.trim()}
            className="rounded-lg bg-accent-strong px-3 py-2 text-sm font-semibold text-white hover:bg-accent disabled:opacity-50"
          >
            ↻ Regenerate audio
          </button>
        )}
        {!isVoice && (
          <button onClick={onDelete} className="rounded-lg border border-bad/50 px-3 py-2 text-sm text-bad hover:bg-bad/10">
            Delete clip
          </button>
        )}
      </div>
    </aside>
  );
}
