// Decode an audio URL to downsampled peak data for drawing clip waveforms.
// Results are cached by URL; decoding happens once per file.

const cache = new Map<string, number[]>();
const pending = new Map<string, Promise<number[]>>();

let ctx: AudioContext | null = null;
function audioCtx(): AudioContext {
  if (!ctx) ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
  return ctx;
}

const BUCKETS = 240; // peaks per clip (downsampled)

// Limit concurrent decodes so a chapter with 100+ clips doesn't freeze the tab.
const MAX_CONCURRENT = 3;
let active = 0;
const queue: (() => void)[] = [];
function acquire(): Promise<void> {
  if (active < MAX_CONCURRENT) {
    active++;
    return Promise.resolve();
  }
  return new Promise((res) => queue.push(res));
}
function release() {
  active--;
  const next = queue.shift();
  if (next) {
    active++;
    next();
  }
}

async function decode(url: string): Promise<number[]> {
  await acquire();
  try {
    const buf = await fetch(url).then((r) => r.arrayBuffer());
    const audio = await audioCtx().decodeAudioData(buf);
    const data = audio.getChannelData(0);
    const block = Math.max(1, Math.floor(data.length / BUCKETS));
    const peaks: number[] = [];
    for (let i = 0; i < BUCKETS; i++) {
      let max = 0;
      const start = i * block;
      for (let j = 0; j < block; j++) {
        const v = Math.abs(data[start + j] || 0);
        if (v > max) max = v;
      }
      peaks.push(max);
    }
    cache.set(url, peaks);
    return peaks;
  } catch {
    cache.set(url, []);
    return [];
  } finally {
    release();
  }
}

export async function getPeaks(url: string): Promise<number[]> {
  if (cache.has(url)) return cache.get(url)!;
  if (pending.has(url)) return pending.get(url)!;
  const p = decode(url).finally(() => pending.delete(url));
  pending.set(url, p);
  return p;
}

// Draw peaks into a canvas (full width/height), tinted + alpha. `scale` lifts or
// drops the amplitude so the waveform reflects the clip's gain (1 = unity).
// `fadeInPx`/`fadeOutPx` taper the amplitude toward the clip edges so fades have
// a visible impact on the waveform (it pinches to the centerline at the edge).
export function drawPeaks(
  canvas: HTMLCanvasElement,
  peaks: number[],
  color: string,
  alpha: number,
  scale = 1,
  fadeInPx = 0,
  fadeOutPx = 0,
) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (!w || !h || !peaks.length) return;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const g = canvas.getContext("2d")!;
  g.scale(dpr, dpr);
  g.clearRect(0, 0, w, h);
  g.globalAlpha = alpha;
  g.fillStyle = color;
  const mid = h / 2;
  const bw = w / peaks.length;
  for (let i = 0; i < peaks.length; i++) {
    const x = i * bw + bw / 2; // bar center
    let env = 1;
    if (fadeInPx > 0 && x < fadeInPx) env = Math.min(env, x / fadeInPx);
    if (fadeOutPx > 0 && x > w - fadeOutPx) env = Math.min(env, (w - x) / fadeOutPx);
    const amp = Math.min(mid - 1, peaks[i] * (mid - 1) * scale * Math.max(0, env));
    g.fillRect(i * bw, mid - amp, Math.max(1, bw * 0.8), amp * 2);
  }
}
