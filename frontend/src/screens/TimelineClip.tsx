import { useEffect, useRef } from "react";
import { mediaUrl, type TimelineSeg } from "../lib/api";
import { drawPeaks, getPeaks } from "../lib/waveform";

const FADE_BAND = 16; // px — top strip of each side that grabs the fade handle

export function TimelineClip({
  seg,
  color,
  pxPerMs,
  laneH,
  selected,
  showWave,
  waveAlpha,
  onDown,
  onResize,
  onFade,
  genProgress,
}: {
  seg: TimelineSeg;
  color: string;
  pxPerMs: number;
  laneH: number;
  selected: boolean;
  showWave: boolean;
  waveAlpha: number;
  onDown: (e: React.MouseEvent) => void;
  onResize: (e: React.MouseEvent, edge: "l" | "r") => void;
  onFade: (e: React.MouseEvent, side: "in" | "out") => void;
  genProgress: number | null; // null=idle, -1=indeterminate, 0..1=fraction
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const url = mediaUrl(seg.audio_url);
  const width = Math.max(4, seg.duration_ms * pxPerMs);
  const h = laneH - 8;
  const gainScale = Math.pow(10, seg.gain_db / 20); // dB -> linear amplitude

  // Fade ramp widths in px, clamped so the two ramps never cross.
  const fadeInW = Math.min(seg.fade_in_ms * pxPerMs, width);
  const fadeOutW = Math.min(seg.fade_out_ms * pxPerMs, width - fadeInW);

  useEffect(() => {
    if (!showWave || !url || !canvasRef.current) return;
    let alive = true;
    getPeaks(url).then((peaks) => {
      if (alive && canvasRef.current) drawPeaks(canvasRef.current, peaks, color, waveAlpha, gainScale, fadeInW, fadeOutW);
    });
    return () => {
      alive = false;
    };
  }, [url, showWave, color, waveAlpha, width, gainScale, fadeInW, fadeOutW]);

  const stop = (e: React.MouseEvent) => e.stopPropagation();

  return (
    <div
      onMouseDown={onDown}
      className="group absolute top-1 cursor-grab overflow-hidden rounded-md border active:cursor-grabbing"
      style={{
        left: seg.start_ms * pxPerMs,
        width,
        height: h,
        background: `${color}1f`,
        borderColor: selected ? color : `${color}66`,
        boxShadow: selected ? `0 0 0 1.5px ${color}` : "none",
        opacity: seg.audio_url ? 1 : 0.5,
      }}
    >
      {showWave && url && <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" />}

      {/* fade ramps — the waveform itself tapers via drawPeaks; here we add a
          bright curve outline, plus a darkened wedge only when there's no
          waveform to carry the fade visually. */}
      {(fadeInW > 0 || fadeOutW > 0) && (() => {
        const wedge = !(showWave && url); // waveform already shows the taper
        return (
        <svg className="pointer-events-none absolute inset-0" width={width} height={h}>
          {fadeInW > 0 && (
            <>
              {wedge && <path d={`M0,0 L${fadeInW},0 Q${fadeInW * 0.35},${h * 0.35} 0,${h} Z`} fill="rgba(0,0,0,0.5)" />}
              <path d={`M0,${h} Q${fadeInW * 0.35},${h * 0.35} ${fadeInW},0`} fill="none" stroke="#fff" strokeWidth={1.5} strokeOpacity={0.85} />
            </>
          )}
          {fadeOutW > 0 && (
            <>
              {wedge && <path d={`M${width},0 L${width},${h} Q${width - fadeOutW * 0.35},${h * 0.35} ${width - fadeOutW},0 Z`} fill="rgba(0,0,0,0.5)" />}
              <path d={`M${width - fadeOutW},0 Q${width - fadeOutW * 0.35},${h * 0.35} ${width},${h}`} fill="none" stroke="#fff" strokeWidth={1.5} strokeOpacity={0.85} />
            </>
          )}
        </svg>
        );
      })()}

      <div className="pointer-events-none relative px-1.5 py-1 text-[10px] leading-tight" style={{ color, paddingTop: FADE_BAND }}>
        <span className="line-clamp-2">{seg.text || seg.prompt || seg.kind}</span>
      </div>

      {/* resize edges (trim) — sit BELOW the fade band so the top of the side always fades */}
      <div
        onMouseDown={(e) => { stop(e); onResize(e, "l"); }}
        className="absolute bottom-0 left-0 w-2 cursor-ew-resize opacity-0 group-hover:opacity-100"
        style={{ top: FADE_BAND, background: `linear-gradient(90deg, ${color}, transparent)` }}
      />
      <div
        onMouseDown={(e) => { stop(e); onResize(e, "r"); }}
        className="absolute bottom-0 right-0 w-2 cursor-ew-resize opacity-0 group-hover:opacity-100"
        style={{ top: FADE_BAND, background: `linear-gradient(270deg, ${color}, transparent)` }}
      />

      {/* fade grab zones — top strip of each side. Always grabbable, even at fade 0:
          the zone spans from the corner out to the current ramp end. Drag inward. */}
      <div
        onMouseDown={(e) => { stop(e); onFade(e, "in"); }}
        title="Drag to fade in"
        className="absolute left-0 top-0 cursor-ew-resize"
        style={{ width: Math.max(FADE_BAND, fadeInW), height: FADE_BAND }}
      />
      <div
        onMouseDown={(e) => { stop(e); onFade(e, "out"); }}
        title="Drag to fade out"
        className="absolute right-0 top-0 cursor-ew-resize"
        style={{ width: Math.max(FADE_BAND, fadeOutW), height: FADE_BAND }}
      />
      {/* fade knobs (visual handles at the ramp ends) */}
      <div
        className="pointer-events-none absolute z-20 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/80 opacity-0 group-hover:opacity-100"
        style={{ left: Math.min(width - 5, Math.max(5, fadeInW)), top: FADE_BAND / 2, background: color }}
      />
      <div
        className="pointer-events-none absolute z-20 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/80 opacity-0 group-hover:opacity-100"
        style={{ left: Math.max(5, Math.min(width - 5, width - fadeOutW)), top: FADE_BAND / 2, background: color }}
      />

      {/* generation progress overlay */}
      {genProgress != null && (
        <div className="pointer-events-none absolute inset-0 z-30 flex flex-col items-center justify-center gap-1 bg-black/55 px-2">
          <span className="text-[9px] font-medium text-white">
            {genProgress < 0 ? "generating…" : `${Math.round(genProgress * 100)}%`}
          </span>
          <div className="h-1 w-full max-w-[120px] overflow-hidden rounded-full bg-white/20">
            {genProgress < 0 ? (
              <div className="h-full w-1/3 animate-[indeterminate_1.2s_ease-in-out_infinite] rounded-full" style={{ background: color }} />
            ) : (
              <div className="h-full rounded-full transition-[width] duration-200" style={{ width: `${Math.max(4, genProgress * 100)}%`, background: color }} />
            )}
          </div>
        </div>
      )}

      {seg.estimated && <span className="pointer-events-none absolute bottom-0.5 right-1 text-[8px] text-faint">est</span>}
      {seg.edited && <span className="pointer-events-none absolute right-1 top-0.5 text-[8px]" style={{ color }}>●</span>}
    </div>
  );
}
