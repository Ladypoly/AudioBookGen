// Live WYSIWYG timeline playback via the Web Audio API.
//
// Instead of playing a pre-baked chapter MP3, this schedules every timeline
// segment as its own buffer source at its absolute start, applying gain, fades
// (linear ramps) and voice pitch (detune) — so what you hear is exactly the
// current timeline. Edits while playing are picked up by a debounced reschedule.

import { mediaUrl, type TimelineSeg } from "./api";

// Decoded clips cached by URL (URLs carry an mtime ?v= so regenerated clips
// decode fresh). AudioBuffers are portable across contexts.
const bufferCache = new Map<string, Promise<AudioBuffer | null>>();

export class TimelinePlayer {
  private ctx: AudioContext;
  private master: GainNode;
  private segs: TimelineSeg[] = [];
  private sources: AudioBufferSourceNode[] = [];
  private startCtxTime = 0; // ctx.currentTime captured when playback began
  private startOffsetMs = 0; // timeline position at that moment
  private _playing = false;
  private rescheduleTimer: number | null = null;

  constructor() {
    const Ctx = window.AudioContext || (window as any).webkitAudioContext;
    this.ctx = new Ctx();
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
  }

  get playing(): boolean {
    return this._playing;
  }

  /** Current timeline position in ms. */
  positionMs(): number {
    if (!this._playing) return this.startOffsetMs;
    return this.startOffsetMs + (this.ctx.currentTime - this.startCtxTime) * 1000;
  }

  /** Replace the segment set (call on every timeline change). Decodes new clips
   *  and, if playing, reschedules so edits are heard. */
  setSegments(segs: TimelineSeg[]): void {
    this.segs = segs;
    for (const s of segs) {
      const url = mediaUrl(s.audio_url);
      if (url) this.load(url);
    }
    if (this._playing) this.queueReschedule();
  }

  async play(fromMs?: number): Promise<void> {
    if (this._playing) return;
    try { await this.ctx.resume(); } catch { /* ignore */ }
    this.startOffsetMs = Math.max(0, fromMs ?? this.startOffsetMs);
    this.startCtxTime = this.ctx.currentTime + 0.06; // small lead so onset isn't clipped
    this._playing = true;
    this.scheduleAll();
  }

  pause(): void {
    if (!this._playing) return;
    this.startOffsetMs = this.positionMs();
    this._playing = false;
    this.stopSources();
  }

  /** Move the playhead. Cheap when paused (just stores the offset). */
  seek(ms: number): void {
    const was = this._playing;
    this.stopSources();
    this.startOffsetMs = Math.max(0, ms);
    if (was) {
      this.startCtxTime = this.ctx.currentTime + 0.03;
      this.scheduleAll();
    }
  }

  dispose(): void {
    if (this.rescheduleTimer) clearTimeout(this.rescheduleTimer);
    this.stopSources();
    try { this.ctx.close(); } catch { /* ignore */ }
  }

  // --- internals -----------------------------------------------------------

  private load(url: string): Promise<AudioBuffer | null> {
    let p = bufferCache.get(url);
    if (!p) {
      p = fetch(url)
        .then((r) => r.arrayBuffer())
        .then((b) => this.ctx.decodeAudioData(b))
        .catch(() => null);
      bufferCache.set(url, p);
    }
    return p;
  }

  private stopSources(): void {
    for (const s of this.sources) {
      try { s.onended = null; s.stop(); } catch { /* already stopped */ }
    }
    this.sources = [];
  }

  private queueReschedule(): void {
    if (this.rescheduleTimer) clearTimeout(this.rescheduleTimer);
    this.rescheduleTimer = window.setTimeout(() => {
      this.rescheduleTimer = null;
      if (!this._playing) return;
      const pos = this.positionMs();
      this.stopSources();
      this.startOffsetMs = pos;
      this.startCtxTime = this.ctx.currentTime + 0.03;
      this.scheduleAll();
    }, 80);
  }

  private scheduleAll(): void {
    for (const seg of this.segs) this.scheduleSeg(seg);
  }

  private scheduleSeg(seg: TimelineSeg): void {
    const url = mediaUrl(seg.audio_url);
    if (!url) return;
    this.load(url).then((buf) => {
      if (buf && this._playing) this.startSeg(seg, buf);
    });
  }

  private startSeg(seg: TimelineSeg, buf: AudioBuffer): void {
    const segDurS = seg.duration_ms / 1000;
    if (seg.start_ms + seg.duration_ms <= this.positionMs() + 1) return; // already past

    const segStartCtx = this.startCtxTime + (seg.start_ms - this.startOffsetMs) / 1000;
    const startAt = Math.max(this.ctx.currentTime, segStartCtx);
    const intoSeg = Math.max(0, startAt - segStartCtx); // seconds already elapsed in the seg
    const remain = segDurS - intoSeg;
    if (remain <= 0) return;

    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    if (seg.kind === "ambience") src.loop = true; // ambience beds tile to fill the duration
    if (seg.pitch_semitones) src.detune.value = seg.pitch_semitones * 100;

    const g = this.ctx.createGain();
    src.connect(g).connect(this.master);
    this.envelope(g.gain, Math.pow(10, (seg.gain_db || 0) / 20), seg, segStartCtx, startAt);

    if (seg.kind === "ambience") {
      src.start(startAt, intoSeg % buf.duration);
      src.stop(startAt + remain);
    } else {
      if (intoSeg >= buf.duration) return; // seeked past the actual audio
      src.start(startAt, intoSeg);
      src.stop(startAt + Math.min(buf.duration - intoSeg, remain));
    }
    this.sources.push(src);
  }

  /** Schedule base gain + fade-in/out ramps, accounting for a mid-fade start
   *  after a seek. */
  private envelope(gain: AudioParam, base: number, seg: TimelineSeg, segStartCtx: number, startAt: number): void {
    const inS = (seg.fade_in_ms || 0) / 1000;
    const outS = (seg.fade_out_ms || 0) / 1000;
    const durS = seg.duration_ms / 1000;
    const inEnd = segStartCtx + inS;
    const outStart = segStartCtx + durS - outS;
    const end = segStartCtx + durS;

    let v0 = base;
    if (inS > 0 && startAt < inEnd) v0 = base * Math.max(0, (startAt - segStartCtx) / inS);
    else if (outS > 0 && startAt >= outStart) v0 = base * Math.max(0, (end - startAt) / outS);
    gain.setValueAtTime(v0, startAt);

    if (inS > 0 && inEnd > startAt) gain.linearRampToValueAtTime(base, inEnd);
    if (outS > 0) {
      if (outStart > startAt && outStart > inEnd) gain.setValueAtTime(base, outStart);
      gain.linearRampToValueAtTime(0, end);
    }
  }
}
