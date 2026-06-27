import { useState } from "react";
import { api, type CharacterView, type ChapterDetail, type ScriptLine } from "../lib/api";
import { DELIVERY_COLOR, speakerColor } from "../lib/labels";
import { TagPopup, type TagApply } from "./TagPopup";
import { SfxPopup, type SfxAdd } from "./SfxPopup";

interface TagSel {
  lineId: string;
  start: number;
  end: number;
  text: string;
  rect: { left: number; top: number; bottom: number };
  initial: Partial<TagApply>;
}

function InlineChips({ d }: { d: ScriptLine["delivery"] }) {
  const chips: { t: string; c: string }[] = [];
  if (d.emotion) chips.push({ t: d.emotion, c: DELIVERY_COLOR.emotion });
  if (d.style) chips.push({ t: d.style, c: DELIVERY_COLOR.style });
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

export function TagEditor({
  cid,
  chapter,
  characters,
  onChange,
}: {
  cid: string;
  chapter: ChapterDetail;
  characters: CharacterView[];
  onChange: (c: ChapterDetail) => void;
}) {
  const [tagSel, setTagSel] = useState<TagSel | null>(null);
  const [sfxFor, setSfxFor] = useState<{ lineId: string; rect: { left: number; top: number; bottom: number } } | null>(null);

  const onMouseUp = () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    const range = sel.getRangeAt(0);
    const startEl = (range.startContainer.parentElement as HTMLElement | null)?.closest("[data-line-id]");
    if (!startEl) return; // selection didn't begin inside a line — ignore
    const endEl = (range.endContainer.parentElement as HTMLElement | null)?.closest("[data-line-id]");
    const lineId = startEl.getAttribute("data-line-id")!;
    const lineText = startEl.textContent ?? "";

    // Offsets within the start line. A selection that runs past this line (too
    // much selected) is clamped to the end of the start line so the popup still
    // appears and tags the words from the selection start onward.
    let start = range.startContainer.nodeType === Node.TEXT_NODE ? range.startOffset : 0;
    let end = endEl === startEl && range.endContainer.nodeType === Node.TEXT_NODE
      ? range.endOffset
      : lineText.length;
    if (start > end) [start, end] = [end, start];
    if (start === end) return;

    const line = chapter.lines_data.find((l) => l.line_id === lineId);
    const r = range.getBoundingClientRect();
    setTagSel({
      lineId,
      start,
      end,
      text: lineText.slice(start, end),
      rect: { left: r.left, top: r.top, bottom: r.bottom },
      initial: line
        ? { emotion: line.delivery.emotion ?? null, style: line.delivery.style ?? null }
        : {},
    });
  };

  const applyTag = async (a: TagApply) => {
    if (!tagSel) return;
    const updated = await api.tagSpan(cid, {
      line_id: tagSel.lineId,
      start: tagSel.start,
      end: tagSel.end,
      ...a,
    });
    window.getSelection()?.removeAllRanges();
    setTagSel(null);
    onChange(updated);
  };

  const addSfx = async (a: SfxAdd) => {
    if (!sfxFor) return;
    const updated =
      a.kind === "prompt"
        ? await api.addSfx(cid, sfxFor.lineId, { prompt: a.prompt!, placement: a.placement })
        : await api.addSfxFile(cid, sfxFor.lineId, a.file!, a.placement);
    setSfxFor(null);
    onChange(updated);
  };

  const removeSfx = async (lineId: string, idx: number) => onChange(await api.removeSfx(cid, lineId, idx));

  if (!chapter.lines_data.length) {
    return <p className="py-6 text-center text-sm text-faint">No script yet — produce this chapter first.</p>;
  }

  return (
    <div>
      <p className="mb-2 text-xs text-faint">
        Select words to tag an emotion or assign a voice · hover a line for <span className="text-muted">+ SFX</span>.
      </p>
      <div className="mb-2 text-[12px]">
        <span className="font-semibold text-good">AMBIENCE</span>{" "}
        <span className="text-muted">{chapter.ambience || "—"}</span>
      </div>

      <div onMouseUp={onMouseUp} className="flex flex-col gap-1.5 text-sm leading-relaxed">
        {chapter.lines_data.map((ln) => {
          const col = speakerColor(ln.speaker_id);
          return (
            <div key={ln.line_id} className="group relative rounded px-1 -mx-1 hover:bg-surface-2">
              <span style={{ color: col }} className="font-semibold">
                {ln.speaker_name}
              </span>
              {ln.type !== "dialogue" && <span className="text-faint"> ({ln.type})</span>}{" "}
              <span data-line-id={ln.line_id} className="text-text/90 selection:bg-accent/40">
                {ln.text}
              </span>
              {ln.pitch_semitones ? (
                <span className="ml-1 text-[11px] text-faint">·pitch {ln.pitch_semitones > 0 ? "+" : ""}{ln.pitch_semitones}</span>
              ) : null}
              <InlineChips d={ln.delivery} />

              {/* hover + SFX */}
              <button
                onClick={(e) => {
                  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  setSfxFor({ lineId: ln.line_id, rect: { left: r.left, top: r.top, bottom: r.bottom } });
                }}
                className="ml-2 rounded border border-border-strong px-1.5 text-[10px] text-faint opacity-0 transition group-hover:opacity-100 hover:text-text"
              >
                + SFX
              </button>

              {ln.sfx.map((cue, i) => (
                <div key={i} className="ml-6 flex items-center gap-1 text-[11px]" style={{ color: DELIVERY_COLOR.sfx }}>
                  SFX <i>{cue.placement}</i> · {cue.prompt}
                  <button onClick={() => removeSfx(ln.line_id, i)} className="text-faint hover:text-bad">
                    ✕
                  </button>
                </div>
              ))}
            </div>
          );
        })}
      </div>

      {tagSel && (
        <TagPopup
          rect={tagSel.rect}
          selectedText={tagSel.text}
          characters={characters}
          initial={tagSel.initial}
          onApply={applyTag}
          onClose={() => setTagSel(null)}
        />
      )}
      {sfxFor && <SfxPopup rect={sfxFor.rect} onAdd={addSfx} onClose={() => setSfxFor(null)} />}
    </div>
  );
}
