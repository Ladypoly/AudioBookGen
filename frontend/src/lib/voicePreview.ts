// Single shared audio element for voice-sample previews, so only one character
// voice plays at a time — starting another (or replaying the same) stops the
// current one. Components subscribe to re-render their play/stop button.

let el: HTMLAudioElement | null = null;
let currentUrl: string | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function audio(): HTMLAudioElement {
  if (!el) {
    el = new Audio();
    el.onended = () => { currentUrl = null; emit(); };
    el.onpause = () => { if (el && el.ended) { currentUrl = null; emit(); } };
  }
  return el;
}

/** Toggle playback for a URL: play it (stopping whatever was playing), or stop
 *  it if it's the one currently playing. */
export function toggleVoice(url: string): void {
  const a = audio();
  if (currentUrl === url && !a.paused) {
    a.pause();
    currentUrl = null;
    emit();
    return;
  }
  a.src = url;
  a.currentTime = 0;
  a.play().catch(() => { currentUrl = null; emit(); });
  currentUrl = url;
  emit();
}

export function stopVoice(): void {
  if (el && !el.paused) el.pause();
  currentUrl = null;
  emit();
}

export function playingUrl(): string | null {
  return currentUrl;
}

export function subscribeVoice(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
