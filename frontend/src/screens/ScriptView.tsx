import type { ChapterDetail, ScriptLine } from "../lib/api";
import { DELIVERY_COLOR, speakerColor } from "../lib/labels";

function DeliveryChips({ d }: { d: ScriptLine["delivery"] }) {
  const chips: { t: string; c: string }[] = [];
  if (d.emotion) chips.push({ t: d.emotion, c: DELIVERY_COLOR.emotion });
  if (d.style) chips.push({ t: d.style, c: DELIVERY_COLOR.style });
  (d.prosody ?? []).forEach((p) => chips.push({ t: p, c: DELIVERY_COLOR.prosody }));
  (d.nonverbal ?? []).forEach((n) => chips.push({ t: n, c: DELIVERY_COLOR.nonverbal }));
  return (
    <>
      {chips.map((ch, i) => (
        <span key={i} style={{ color: ch.c }} className="ml-1 text-[11px]">
          ·{ch.t}
        </span>
      ))}
    </>
  );
}

function Legend() {
  const items: [string, string][] = [
    ["emotion", DELIVERY_COLOR.emotion],
    ["style", DELIVERY_COLOR.style],
    ["prosody", DELIVERY_COLOR.prosody],
    ["nonverbal", DELIVERY_COLOR.nonverbal],
    ["SFX", DELIVERY_COLOR.sfx],
  ];
  return (
    <div className="mb-2 flex gap-3 text-[11px]">
      {items.map(([t, c]) => (
        <span key={t} style={{ color: c }}>
          {t}
        </span>
      ))}
    </div>
  );
}

export function ScriptView({ chapter }: { chapter: ChapterDetail }) {
  if (!chapter.lines_data.length) {
    return <p className="py-6 text-center text-sm text-faint">No script yet — produce this chapter first.</p>;
  }
  return (
    <div className="text-sm leading-relaxed">
      <div className="mb-1 text-[12px]">
        <span className="font-semibold text-good">AMBIENCE</span>{" "}
        <span className="text-muted">{chapter.ambience || "—"}</span>
      </div>
      {chapter.music && (
        <div className="mb-1 text-[12px]">
          <span className="font-semibold" style={{ color: "#9DAAF2" }}>
            MUSIC
          </span>{" "}
          <span className="text-muted">{chapter.music}</span>
        </div>
      )}
      <Legend />
      <div className="h-px bg-border" />
      <div className="mt-2 flex flex-col gap-1.5">
        {chapter.lines_data.map((ln) => {
          const col = speakerColor(ln.speaker_id);
          return (
            <div key={ln.line_id}>
              <span style={{ color: col }} className="font-semibold">
                {ln.speaker_name}
              </span>
              {ln.type !== "dialogue" && <span className="text-faint"> ({ln.type})</span>}{" "}
              <span className="text-text/90">{ln.text}</span>
              <DeliveryChips d={ln.delivery} />
              {ln.sfx.map((cue, i) => (
                <div key={i} className="ml-6 text-[11px]" style={{ color: DELIVERY_COLOR.sfx }}>
                  SFX <i>{cue.placement}</i> · {cue.prompt}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
