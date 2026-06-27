import { useEffect, useRef, useState } from "react";
import { api, mediaUrl, type CharacterView } from "../lib/api";
import { AGE_LABEL, GENDER_LABEL, ROLE_COLOR } from "../lib/labels";
import { playingUrl, subscribeVoice, toggleVoice } from "../lib/voicePreview";
import { VoiceDesignPopup } from "./VoiceDesignPopup";

// A "stage" is one age view of the character: stage 0 = base, 1.. = variants.
interface Stage {
  variantIdx: number | null; // null = base
  ageBand: string;
  description: string;
  portraitUrl?: string | null;
  voiceUrl?: string | null;
  customVoice: boolean;
  voiceHint: string;
}

function stagesOf(c: CharacterView): Stage[] {
  const base: Stage = {
    variantIdx: null,
    ageBand: c.age_band,
    description: c.appearance_description,
    portraitUrl: c.portrait_url,
    voiceUrl: c.voice_url,
    customVoice: c.custom_voice,
    voiceHint: c.voice_hint,
  };
  const vs: Stage[] = c.variants.map((v, i) => ({
    variantIdx: i,
    ageBand: v.age_band,
    description: v.appearance_description || c.appearance_description,
    portraitUrl: v.portrait_url,
    voiceUrl: v.voice_url,
    customVoice: v.custom_voice,
    voiceHint: v.voice_hint || c.voice_hint,
  }));
  return [base, ...vs];
}

export function CharacterCard({
  c,
  onEdit,
  onChanged,
}: {
  c: CharacterView;
  onEdit: () => void;
  onChanged: () => void;
}) {
  const stages = stagesOf(c);
  const [stageIdx, setStageIdx] = useState(0);
  const stage = stages[Math.min(stageIdx, stages.length - 1)];
  const hasVariants = c.variants.length > 0;
  const roleColor = ROLE_COLOR[c.role_importance] ?? "#9aa3b2";
  const voiceFileRef = useRef<HTMLInputElement>(null);
  const [showDesign, setShowDesign] = useState(false);
  const [, setTick] = useState(0);
  useEffect(() => subscribeVoice(() => setTick((t) => t + 1)), []);

  const portrait = mediaUrl(stage.portraitUrl);
  const voice = mediaUrl(stage.voiceUrl);
  const isPlaying = !!voice && playingUrl() === voice;

  const play = () => {
    if (voice) toggleVoice(voice);
  };

  const uploadVoice = async (file: File) => {
    await api.uploadVoice(c.character_id, file, stage.variantIdx ?? undefined);
    onChanged();
  };
  const designVoice = () => setShowDesign(true);
  const genPortrait = async () => {
    await api.generatePortrait(c.character_id, stage.variantIdx ?? undefined);
  };

  return (
    <div className="flex w-full flex-col overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface">
      {/* header strip — like an ID card */}
      <div className="flex items-center justify-between px-3 py-2" style={{ background: `${roleColor}1a` }}>
        <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: roleColor }}>
          {c.role_importance}
        </span>
        <button onClick={onEdit} className="text-faint transition hover:text-text" title="Edit">
          ✎
        </button>
      </div>

      <div className="flex gap-3 p-3">
        {/* portrait */}
        <div className="relative h-[150px] w-[112px] shrink-0 overflow-hidden rounded-lg border border-border bg-elevated">
          {portrait ? (
            <img src={portrait} alt="" className="h-full w-full object-cover" />
          ) : (
            <button
              onClick={genPortrait}
              className="flex h-full w-full flex-col items-center justify-center gap-1 text-faint transition hover:text-muted"
              title="Generate portrait"
            >
              <span className="text-2xl">🎨</span>
              <span className="text-[10px]">Generate</span>
            </button>
          )}
          {c.needs_review && (
            <span className="absolute left-1 top-1 rounded bg-warn/90 px-1 text-[9px] font-bold text-black">
              review
            </span>
          )}
        </div>

        {/* identity */}
        <div className="flex min-w-0 flex-1 flex-col">
          <h3 className="truncate text-sm font-semibold text-text">{c.display_name}</h3>
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-muted">
            <span>{GENDER_LABEL[c.gender_guess]}</span>
            <span>· {AGE_LABEL[stage.ageBand]}</span>
            <span>· {c.spoken_lines} {c.spoken_lines === 1 ? "line" : "lines"}</span>
          </div>
          {stage.description && (
            <p className="mt-1.5 line-clamp-3 text-[11px] leading-snug text-faint">{stage.description}</p>
          )}
          {!!c.vocal_traits.length && (
            <div className="mt-auto flex flex-wrap gap-1 pt-2">
              {c.vocal_traits.slice(0, 3).map((t) => (
                <span key={t} className="rounded-full bg-elevated px-2 py-0.5 text-[10px] text-muted">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* age slide-dots */}
      {hasVariants && (
        <div className="flex items-center justify-center gap-1.5 pb-1">
          {stages.map((s, i) => (
            <button
              key={i}
              onClick={() => setStageIdx(i)}
              title={AGE_LABEL[s.ageBand]}
              className={`h-2 w-2 rounded-full transition ${i === stageIdx ? "bg-accent" : "bg-border-strong hover:bg-muted"}`}
            />
          ))}
        </div>
      )}

      {/* voice row */}
      <div className="flex items-center gap-2 border-t border-border px-3 py-2">
        <button
          disabled={!voice}
          onClick={play}
          className="rounded-md border border-border-strong px-2 py-1 text-xs text-muted transition enabled:hover:text-text disabled:opacity-40"
          title={voice ? (isPlaying ? "Stop" : "Play voice sample") : "No voice yet"}
        >
          {isPlaying ? "◼" : "▶"}
        </button>
        <span className="min-w-0 flex-1 truncate text-[11px] text-faint">
          {voice ? (stage.customVoice ? "custom voice" : "designed voice") : stage.voiceHint || "no voice"}
        </span>
        <input
          ref={voiceFileRef}
          type="file"
          accept="audio/*"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && uploadVoice(e.target.files[0])}
        />
        <button
          onClick={() => voiceFileRef.current?.click()}
          className="rounded-md border border-border-strong px-2 py-1 text-[11px] text-muted transition hover:text-text"
          title="Upload a voice sample to clone"
        >
          Upload
        </button>
        <button
          onClick={designVoice}
          className="rounded-md border border-border-strong px-2 py-1 text-[11px] text-muted transition hover:text-text"
          title="Design a voice from the profile"
        >
          Design
        </button>
      </div>

      {showDesign && (
        <VoiceDesignPopup
          cid={c.character_id}
          name={c.display_name}
          variant={stage.variantIdx ?? undefined}
          onClose={() => setShowDesign(false)}
          onStarted={onChanged}
        />
      )}
    </div>
  );
}
