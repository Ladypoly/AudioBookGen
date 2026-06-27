import { useEffect, useState } from "react";
import { api } from "../lib/api";

const LABELS: Record<string, string> = {
  very_low: "Very Low", low: "Low", moderate: "Moderate", high: "High", very_high: "Very High",
  very_slow: "Very Slow", slow: "Slow", normal: "Normal", fast: "Fast", very_fast: "Very Fast",
  young_adult: "Young Adult", middle_aged: "Middle-aged", whisper: "Whisper", soft: "Soft",
  energetic: "Energetic", calm: "Calm", dramatic: "Dramatic", conversational: "Conversational",
  authoritative: "Authoritative", narration: "Narration", intense: "Intense",
  male: "Male", female: "Female", ambiguous: "Neutral",
  child: "Child", teen: "Teen", adult: "Adult", elderly: "Elderly",
  neutral: "Neutral", happy: "Happy", sad: "Sad", angry: "Angry", excited: "Excited",
  fearful: "Fearful", tender: "Tender", serious: "Serious", playful: "Playful",
};
const cap = (s: string) => LABELS[s] ?? s.charAt(0).toUpperCase() + s.slice(1);

type Opts = Awaited<ReturnType<typeof api.voiceOptions>>;

function Group({
  title, items, value, onPick, labelOf,
}: {
  title: string; items: string[]; value: string; onPick: (v: string) => void; labelOf?: (v: string) => string;
}) {
  return (
    <div>
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-faint">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((it) => (
          <button
            key={it}
            onClick={() => onPick(it)}
            className={`rounded-lg border px-2.5 py-1 text-xs transition ${
              value === it ? "border-accent bg-accent/15 text-accent" : "border-border-strong text-muted hover:text-text"
            }`}
          >
            {labelOf ? labelOf(it) : cap(it)}
          </button>
        ))}
      </div>
    </div>
  );
}

function MultiGroup({
  title, items, values, onToggle,
}: {
  title: string; items: string[]; values: string[]; onToggle: (v: string) => void;
}) {
  return (
    <div className="col-span-2">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-faint">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((it) => (
          <button
            key={it}
            onClick={() => onToggle(it)}
            className={`rounded-lg border px-2.5 py-1 text-xs transition ${
              values.includes(it) ? "border-accent bg-accent/15 text-accent" : "border-border-strong text-muted hover:text-text"
            }`}
          >
            {cap(it)}
          </button>
        ))}
      </div>
    </div>
  );
}

const DEFAULT_SEL = {
  gender: "male", age: "adult", pitch: "moderate", speed: "normal", energy: "moderate",
  emotion: "neutral", style: "normal", language: "English", accent: "British English",
};

export function VoiceDesignPopup({
  cid, name, variant, onClose, onStarted,
}: {
  cid: string; name: string; variant?: number; onClose: () => void; onStarted: () => void;
}) {
  const [opts, setOpts] = useState<Opts | null>(null);
  const [sel, setSel] = useState({ ...DEFAULT_SEL });
  const [timbre, setTimbre] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [edited, setEdited] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.voiceOptions().then(setOpts).catch(() => {});
    api.voicePrompt(cid, { variant }).then((r) => {
      setSel((s) => ({ ...s, gender: r.gender, age: r.age, accent: r.accent, language: r.language || s.language }));
      setPrompt(r.prompt);
    }).catch(() => {});
  }, [cid, variant]);

  const recompose = (nextSel: typeof sel, nextTimbre: string[]) => {
    api.voicePrompt(cid, { variant, ...nextSel, timbre: nextTimbre })
      .then((r) => { if (!edited) setPrompt(r.prompt); })
      .catch(() => {});
  };

  const pick = (key: string, v: string) =>
    setSel((prev) => {
      const next = { ...prev, [key]: v };
      recompose(next, timbre);
      return next;
    });

  const toggleTimbre = (v: string) =>
    setTimbre((prev) => {
      const next = prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v];
      recompose(sel, next);
      return next;
    });

  const regenerate = async () => {
    setBusy(true);
    await api.designVoice(cid, { variant, description: prompt, language: sel.language }).catch(() => {});
    onStarted();
    onClose();
  };

  const outLine = `${cap(sel.gender)}, ${cap(sel.age)}, ${cap(sel.pitch)} pitch, ${cap(sel.speed)} speed, ${cap(sel.energy)}, ${cap(sel.emotion)}, ${cap(sel.style)}${timbre.length ? `, ${timbre.join("/")}` : ""}, ${sel.language}, ${sel.accent}`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onMouseDown={onClose}>
      <div className="flex max-h-[90vh] w-[680px] max-w-[95vw] flex-col rounded-2xl border border-border bg-surface shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold">Design voice · {name}</h2>
          <button onClick={onClose} className="text-faint hover:text-text">✕</button>
        </div>

        <div className="border-b border-border bg-surface-2 px-6 py-2 font-mono text-[11px]">
          <span className="text-faint">OUT &gt; </span>
          <span className="text-accent">{outLine}</span>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {!opts ? (
            <p className="text-sm text-faint">Loading…</p>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <Group title="Gender" items={opts.genders} value={sel.gender} onPick={(v) => pick("gender", v)} />
              <Group title="Age" items={opts.ages} value={sel.age} onPick={(v) => pick("age", v)} />
              <Group title="Pitch" items={opts.pitches} value={sel.pitch} onPick={(v) => pick("pitch", v)} />
              <Group title="Speed" items={opts.speeds} value={sel.speed} onPick={(v) => pick("speed", v)} />
              <Group title="Energy" items={opts.energies} value={sel.energy} onPick={(v) => pick("energy", v)} />
              <Group title="Emotion" items={opts.emotions} value={sel.emotion} onPick={(v) => pick("emotion", v)} />
              <Group title="Style" items={opts.styles} value={sel.style} onPick={(v) => pick("style", v)} />
              <Group title="Language" items={opts.languages} value={sel.language} onPick={(v) => pick("language", v)} labelOf={(v) => v} />
              <MultiGroup title="Timbre / texture" items={opts.timbres} values={timbre} onToggle={toggleTimbre} />
              <div className="col-span-2">
                <Group
                  title="Accent"
                  items={opts.accents.map((a) => a.accent)}
                  value={sel.accent}
                  onPick={(v) => pick("accent", v)}
                  labelOf={(v) => opts.accents.find((a) => a.accent === v)?.label ?? v}
                />
              </div>
            </div>
          )}

          <div className="mt-4">
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-faint">Prompt (editable, free-form)</span>
              {edited && (
                <button
                  onClick={() => { setEdited(false); api.voicePrompt(cid, { variant, ...sel, timbre }).then((r) => setPrompt(r.prompt)).catch(() => {}); }}
                  className="text-[10px] text-faint hover:text-text"
                >
                  ↺ reset to selectors
                </button>
              )}
            </div>
            <textarea
              value={prompt}
              onChange={(e) => { setPrompt(e.target.value); setEdited(true); }}
              className="h-28 w-full resize-none rounded-lg border border-border-strong bg-bg px-3 py-2 text-sm leading-relaxed text-text outline-none focus:border-accent"
            />
            <p className="mt-1 text-[11px] text-faint">
              Qwen voice design is fully natural-language — tweak the selectors or edit the prompt directly, then regenerate.
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-3 border-t border-border px-6 py-4">
          <button onClick={onClose} className="rounded-lg border border-border-strong px-4 py-2 text-sm text-muted hover:text-text">Cancel</button>
          <button
            onClick={regenerate}
            disabled={busy || !prompt.trim()}
            className="rounded-lg bg-accent-strong px-5 py-2 text-sm font-semibold text-white hover:bg-accent disabled:opacity-50"
          >
            {busy ? "Starting…" : "🎙 Regenerate voice"}
          </button>
        </div>
      </div>
    </div>
  );
}
