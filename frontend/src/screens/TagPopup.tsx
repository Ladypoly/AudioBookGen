import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { type CharacterView } from "../lib/api";
import { DELIVERY_COLOR, EMOTIONS, STYLES } from "../lib/labels";

export interface TagApply {
  emotion: string | null;
  style: string | null;
  speaker_id: string | null;
  pitch_semitones: number;
}

const KEEP = "__keep__";

function Chip({
  label,
  active,
  color,
  onClick,
}: {
  label: string;
  active: boolean;
  color: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="rounded-full border px-2 py-0.5 text-[11px] capitalize transition"
      style={{
        borderColor: active ? color : "var(--color-border-strong)",
        background: active ? `${color}26` : "transparent",
        color: active ? color : "var(--color-muted)",
      }}
    >
      {label}
    </button>
  );
}

export function TagPopup({
  rect,
  selectedText,
  characters,
  initial,
  onApply,
  onClose,
}: {
  rect: { left: number; top: number; bottom: number };
  selectedText: string;
  characters: CharacterView[];
  initial?: Partial<TagApply>;
  onApply: (a: TagApply) => void;
  onClose: () => void;
}) {
  const [emotion, setEmotion] = useState<string | null>(initial?.emotion ?? null);
  const [style, setStyle] = useState<string | null>(initial?.style ?? null);
  const [speaker, setSpeaker] = useState<string>(initial?.speaker_id ?? KEEP);
  const [pitch, setPitch] = useState<number>(initial?.pitch_semitones ?? 0);

  const isDefault = speaker === "default_male" || speaker === "default_female";

  const ref = useRef<HTMLDivElement>(null);
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - 332));
  const [top, setTop] = useState(Math.max(8, rect.bottom + 8));

  // Keep the whole popup (incl. the footer buttons) inside the viewport even
  // when the pitch slider grows it.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const h = el.offsetHeight;
    const desired = rect.bottom + 8;
    const maxTop = window.innerHeight - h - 8;
    setTop(Math.max(8, Math.min(desired, maxTop)));
  }, [isDefault, emotion, style, rect.bottom]);

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-40" onMouseDown={onClose} />
      <div
        ref={ref}
        className="fixed z-50 flex max-h-[85vh] w-[320px] flex-col rounded-xl border border-border-strong bg-surface shadow-2xl"
        style={{ left, top }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <p className="mb-2 truncate text-[11px] text-faint">“{selectedText}”</p>

          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-faint">Emotion</div>
          <div className="mb-3 flex flex-wrap gap-1">
            <Chip label="none" active={!emotion} color="#9aa3b2" onClick={() => setEmotion(null)} />
            {EMOTIONS.map((e) => (
              <Chip key={e} label={e} active={emotion === e} color={DELIVERY_COLOR.emotion} onClick={() => setEmotion(e)} />
            ))}
          </div>

          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-faint">Style</div>
          <div className="mb-3 flex flex-wrap gap-1">
            <Chip label="none" active={!style} color="#9aa3b2" onClick={() => setStyle(null)} />
            {STYLES.map((s) => (
              <Chip key={s} label={s} active={style === s} color={DELIVERY_COLOR.style} onClick={() => setStyle(s)} />
            ))}
          </div>

          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-faint">Voice</div>
          <select
            value={speaker}
            onChange={(e) => setSpeaker(e.target.value)}
            className="w-full rounded-lg border border-border-strong bg-bg px-2 py-1.5 text-sm text-text outline-none focus:border-accent"
          >
            <option value={KEEP}>— keep current speaker —</option>
            <optgroup label="One-off voices">
              <option value="default_male">Default male voice</option>
              <option value="default_female">Default female voice</option>
            </optgroup>
            <optgroup label="Characters">
              {characters
                .filter((c) => c.character_id !== "default_male" && c.character_id !== "default_female")
                .map((c) => (
                  <option key={c.character_id} value={c.character_id}>
                    {c.display_name}
                  </option>
                ))}
            </optgroup>
          </select>

          {isDefault && (
            <div className="mt-2">
              <div className="flex items-center justify-between text-[11px] text-faint">
                <span>Pitch</span>
                <span className="text-muted">{pitch > 0 ? `+${pitch}` : pitch} st</span>
              </div>
              <input
                type="range"
                min={-6}
                max={6}
                step={0.5}
                value={pitch}
                onChange={(e) => setPitch(parseFloat(e.target.value))}
                className="w-full accent-[var(--color-accent)]"
              />
              <p className="text-[10px] text-faint">Shift the shared voice to vary unnamed speakers.</p>
            </div>
          )}
        </div>

        {/* footer stays pinned + always visible */}
        <div className="flex shrink-0 justify-end gap-2 border-t border-border p-2">
          <button onClick={onClose} className="rounded-lg border border-border-strong px-3 py-1 text-xs text-muted hover:text-text">
            Cancel
          </button>
          <button
            onClick={() =>
              onApply({
                emotion,
                style,
                speaker_id: speaker === KEEP ? null : speaker,
                pitch_semitones: isDefault ? pitch : 0,
              })
            }
            className="rounded-lg bg-accent-strong px-3 py-1 text-xs font-semibold text-white hover:bg-accent"
          >
            Apply
          </button>
        </div>
      </div>
    </>
  );
}
