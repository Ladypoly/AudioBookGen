// REST client for the FastAPI bridge.
// In dev, Vite proxies "/api" + "/ws" to the sidecar, so relative URLs work.
// In Electron, the main process injects window.__API_BASE__ (e.g. http://127.0.0.1:8765).

const BASE: string = (window as any).__API_BASE__ ?? "";

export const apiBase = BASE;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`);
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? await res.json() : (await res.text())) as T;
}

// Map an /api/media URL to an absolute URL the browser can load.
export const mediaUrl = (u: string | null | undefined): string | undefined =>
  u ? BASE + u : undefined;

export const wsUrl = (path: string): string => {
  if (BASE) return BASE.replace(/^http/, "ws") + path;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}${path}`;
};

// --- types ----------------------------------------------------------------
export interface ProjectSummary {
  id: string;
  title: string;
  author: string;
  character_count: number;
  cover?: string | null;
}

export interface Health {
  ollama: boolean;
  comfy: boolean;
}

export interface SetupStatus {
  comfy_dir: string;
  comfy_dir_valid: boolean;
  node_installed: boolean;
  git_available: boolean;
  node_repo: string;
  ollama: boolean;
  comfy_running: boolean;
}

export interface SettingField {
  label: string;
  path: string;
  kind: string;
  choices: string[] | null;
  value: unknown;
}
export interface SettingsSchema {
  sections: { name: string; fields: SettingField[] }[];
}

export interface ProviderInfo {
  id: string;
  label: string;
  base_url: string;
}
export interface CloudModel {
  id: string;
  prompt: number | null;
  completion: number | null;
  tier: "cheap" | "medium" | "expensive" | "unknown";
}

export interface JobView {
  id: string;
  kind: string;
  title: string;
  state: "pending" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  detail: string;
  error: string | null;
  meta: Record<string, unknown>;
}

export interface Inspected {
  token: string;
  title: string;
  author: string;
  subtitle: string;
  cover: string | null;
  filename: string;
}

export interface VariantView {
  age_band: string;
  label: string;
  appearance_description: string;
  portrait_prompt: string;
  portrait_path: string | null;
  voice_sample: string | null;
  custom_voice: boolean;
  voice_hint: string;
  portrait_url?: string | null;
  voice_url?: string | null;
}

export interface CharacterView {
  character_id: string;
  display_name: string;
  aliases: string[];
  gender_guess: string;
  age_band: string;
  role_importance: string;
  voice_hint: string;
  personality_notes: string;
  vocal_traits: string[];
  appearance_traits: string[];
  appearance_description: string;
  context: string;
  sample_line: string;
  tts_workflow: string;
  total_mentions: number;
  spoken_lines: number;
  needs_review: boolean;
  custom_voice: boolean;
  active: boolean;
  portrait_url?: string | null;
  voice_url?: string | null;
  variants: VariantView[];
}

export interface ChapterInfo {
  chapter_id: string;
  number: number;
  title: string;
  lines: number;
  rendered: boolean;
  audio_url: string | null;
}

export interface ScriptLine {
  line_id: string;
  index: number;
  type: string;
  speaker_id: string;
  speaker_name: string;
  text: string;
  delivery: {
    emotion?: string | null;
    style?: string | null;
    prosody?: string[];
    nonverbal?: string[];
    pre_pause_ms?: number;
    post_pause_ms?: number;
  };
  sfx: { prompt: string; placement: string; length_s: number; gain_db: number; custom?: boolean }[];
  pitch_semitones?: number;
}

export interface ChapterDetail extends ChapterInfo {
  text: string;
  summary: string;
  location: string;
  curated: boolean;
  lines_data: ScriptLine[];
  ambience: string;
  music: string;
}

export interface TimelineSeg {
  id: string;
  kind: "voice" | "ambience" | "sfx";
  lane: string;
  start_ms: number;
  duration_ms: number;
  gain_db: number;
  fade_in_ms: number;
  fade_out_ms: number;
  line_id: string | null;
  speaker_id: string | null;
  text: string;
  prompt: string;
  pitch_semitones: number;
  custom: boolean;
  estimated: boolean;
  edited: boolean;
  audio_url: string | null;
}

export interface TimelineData {
  chapter_id: string;
  duration_ms: number;
  lanes: string[];
  segments: TimelineSeg[];
}

// Electron exposes a native file picker + an absolute API base.
export const isElectron = (): boolean => !!(window as any).electronAPI;
export const pickBookFile = (): Promise<string | null> =>
  (window as any).electronAPI?.openBook?.() ?? Promise.resolve(null);
export const pickFolder = (): Promise<string | null> =>
  (window as any).electronAPI?.chooseFolder?.() ?? Promise.resolve(null);

// --- endpoints ------------------------------------------------------------
export const api = {
  ping: () => req<{ ok: boolean }>("/api/ping"),
  health: () => req<Health>("/api/health"),
  launchComfy: () => req<{ ok: boolean; launching?: boolean; already_running?: boolean; error?: string }>(
    "/api/health/comfy/launch", { method: "POST" }),

  // --- first-run setup ---
  setupStatus: () => req<SetupStatus>("/api/setup/status"),
  setComfyDir: (path: string) =>
    req<SetupStatus>("/api/setup/comfy-dir", { method: "POST", body: JSON.stringify({ path }) }),
  installNode: () => req<{ job_id: string }>("/api/setup/install-node", { method: "POST" }),
  listProjects: () => req<ProjectSummary[]>("/api/projects"),
  activeProject: () => req<{ active: { id: string; title: string } | null }>("/api/projects/active"),
  openProject: (id: string) =>
    req<{ id: string; title: string }>(`/api/projects/${id}/open`, { method: "POST" }),
  updateProject: (id: string, body: { title?: string; author?: string; subtitle?: string }) =>
    req<ProjectSummary>(`/api/projects/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteProject: (id: string) =>
    req<{ ok: boolean }>(`/api/projects/${encodeURIComponent(id)}`, { method: "DELETE" }),
  duplicateProject: (id: string) =>
    req<ProjectSummary>(`/api/projects/${encodeURIComponent(id)}/duplicate`, { method: "POST" }),
  setProjectCover: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(BASE + `/api/projects/${encodeURIComponent(id)}/cover`, { method: "POST", body: fd })
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return (await r.json()) as ProjectSummary;
      });
  },
  settingsSchema: () => req<SettingsSchema>("/api/settings/schema"),
  getSettings: () => req<Record<string, unknown>>("/api/settings"),
  listWorkflows: () => req<{ workflows: string[]; default_tts: string }>("/api/settings/workflows"),
  saveSettings: (values: Record<string, unknown>) =>
    req<{ ok: boolean }>("/api/settings", { method: "POST", body: JSON.stringify({ values }) }),
  providers: () => req<{ local: ProviderInfo[]; cloud: ProviderInfo[] }>("/api/settings/providers"),
  localModels: (provider: string, url: string) =>
    req<string[]>(`/api/settings/local-models?provider=${encodeURIComponent(provider)}&url=${encodeURIComponent(url)}`),
  cloudModels: (base_url: string, api_key: string) =>
    req<CloudModel[]>(`/api/settings/cloud-models?base_url=${encodeURIComponent(base_url)}&api_key=${encodeURIComponent(api_key)}`),
  jobs: () => req<JobView[]>("/api/jobs"),
  cancelJob: (id: string) => req<{ ok: boolean }>(`/api/jobs/${id}/cancel`, { method: "POST" }),

  // --- New-AudioDrama ingestion ---
  inspectPath: (path: string) =>
    req<Inspected>("/api/ingest/inspect-path", { method: "POST", body: JSON.stringify({ path }) }),
  inspectUpload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(BASE + "/api/ingest/inspect", { method: "POST", body: fd }).then(async (r) => {
      if (!r.ok) throw new Error(await r.text());
      return (await r.json()) as Inspected;
    });
  },
  replaceCover: (token: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(BASE + `/api/ingest/${token}/cover`, { method: "POST", body: fd }).then(async (r) => {
      if (!r.ok) throw new Error(await r.text());
      return (await r.json()) as { cover: string };
    });
  },
  createProject: (body: { token: string; title: string; author: string; subtitle: string }) =>
    req<{ project_id: string; job_id: string }>("/api/ingest/create", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // --- characters ---
  listCharacters: () => req<CharacterView[]>("/api/characters"),
  generateMissing: (body: { images?: boolean; voices?: boolean } = {}) =>
    req<{ job_id: string }>("/api/characters/generate-missing", { method: "POST", body: JSON.stringify(body) }),
  updateCharacter: (cid: string, patch: Partial<CharacterView>) =>
    req<CharacterView>(`/api/characters/${encodeURIComponent(cid)}`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  mergeCharacter: (cid: string, source: string) =>
    req<CharacterView & { repointed_lines: number }>(
      `/api/characters/${encodeURIComponent(cid)}/merge`,
      { method: "POST", body: JSON.stringify({ source }) },
    ),
  uploadVoice: (cid: string, file: File, variant?: number) => {
    const fd = new FormData();
    fd.append("file", file);
    if (variant != null) fd.append("variant", String(variant));
    return fetch(BASE + `/api/characters/${encodeURIComponent(cid)}/voice`, {
      method: "POST",
      body: fd,
    }).then(async (r) => {
      if (!r.ok) throw new Error(await r.text());
      return (await r.json()) as CharacterView;
    });
  },
  generatePortrait: (cid: string, variant?: number) =>
    req<{ job_id: string }>(`/api/characters/${encodeURIComponent(cid)}/portrait`, {
      method: "POST",
      body: JSON.stringify({ variant: variant ?? null }),
    }),
  designVoice: (cid: string, opts: { variant?: number; description?: string; language?: string } = {}) =>
    req<{ job_id: string }>(`/api/characters/${encodeURIComponent(cid)}/voice/design`, {
      method: "POST",
      body: JSON.stringify({ variant: opts.variant ?? null, description: opts.description ?? null, language: opts.language ?? null }),
    }),
  voiceOptions: () =>
    req<{
      genders: string[]; ages: string[]; pitches: string[]; speeds: string[];
      energies: string[]; emotions: string[]; styles: string[]; timbres: string[];
      languages: string[]; accents: { id: string; label: string; accent: string }[];
    }>("/api/characters/voice/options"),
  voicePrompt: (
    cid: string,
    body: { variant?: number; gender?: string; age?: string; pitch?: string; speed?: string; energy?: string; emotion?: string; style?: string; timbre?: string[]; language?: string; accent?: string },
  ) =>
    req<{ prompt: string; gender: string; age: string; accent: string; language: string }>(
      `/api/characters/${encodeURIComponent(cid)}/voice/prompt`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  // --- chapters ---
  listChapters: () => req<ChapterInfo[]>("/api/chapters"),
  getChapter: async (cid: string): Promise<ChapterDetail> => {
    const d = await req<any>(`/api/chapters/${encodeURIComponent(cid)}`);
    return { ...d, lines_data: d.lines as ScriptLine[], lines: d.lines.length };
  },
  updateChapterText: async (cid: string, text: string): Promise<ChapterDetail> => {
    const d = await req<any>(`/api/chapters/${encodeURIComponent(cid)}/text`, {
      method: "PUT",
      body: JSON.stringify({ text }),
    });
    return { ...d, lines_data: d.lines as ScriptLine[], lines: d.lines.length };
  },
  renderChapter: (cid: string, mode: string) =>
    req<{ job_id: string }>(`/api/chapters/${encodeURIComponent(cid)}/render`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  produceChapters: (mode: string) =>
    req<{ job_id: string }>("/api/chapters/produce", { method: "POST", body: JSON.stringify({ mode }) }),
  exportAudiobook: (folder: string) =>
    req<{ job_id: string }>("/api/chapters/export", { method: "POST", body: JSON.stringify({ folder }) }),

  // --- script tag editor ---
  ensureDefaultVoices: () => req<CharacterView[]>("/api/characters/defaults", { method: "POST" }),
  tagSpan: async (
    cid: string,
    body: { line_id: string; start: number; end: number; emotion: string | null; style: string | null; speaker_id: string | null; pitch_semitones: number },
  ): Promise<ChapterDetail> => {
    const d = await req<any>(`/api/chapters/${encodeURIComponent(cid)}/lines/tag`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    return { ...d, lines_data: d.lines as ScriptLine[], lines: d.lines.length };
  },
  addSfx: async (
    cid: string,
    lineId: string,
    body: { prompt: string; placement: string; position?: number },
  ): Promise<ChapterDetail> => {
    const d = await req<any>(`/api/chapters/${encodeURIComponent(cid)}/lines/${encodeURIComponent(lineId)}/sfx`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    return { ...d, lines_data: d.lines as ScriptLine[], lines: d.lines.length };
  },
  addSfxFile: async (cid: string, lineId: string, file: File, placement: string): Promise<ChapterDetail> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("placement", placement);
    const r = await fetch(BASE + `/api/chapters/${encodeURIComponent(cid)}/lines/${encodeURIComponent(lineId)}/sfx-file`, {
      method: "POST",
      body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    return { ...d, lines_data: d.lines as ScriptLine[], lines: d.lines.length };
  },
  removeSfx: async (cid: string, lineId: string, idx: number): Promise<ChapterDetail> => {
    const d = await req<any>(`/api/chapters/${encodeURIComponent(cid)}/lines/${encodeURIComponent(lineId)}/sfx/${idx}`, {
      method: "DELETE",
    });
    return { ...d, lines_data: d.lines as ScriptLine[], lines: d.lines.length };
  },
  summarizeChapter: (cid: string) =>
    req<{ job_id: string }>(`/api/chapters/${encodeURIComponent(cid)}/summarize`, { method: "POST" }),

  // --- timeline ---
  getTimeline: (cid: string) => req<TimelineData>(`/api/chapters/${encodeURIComponent(cid)}/timeline`),
  putTimeline: (cid: string, tl: TimelineData) =>
    req<TimelineData>(`/api/chapters/${encodeURIComponent(cid)}/timeline`, { method: "PUT", body: JSON.stringify(tl) }),
  renderTimeline: (cid: string) =>
    req<{ job_id: string }>(`/api/chapters/${encodeURIComponent(cid)}/timeline/render`, { method: "POST" }),
  addSegment: (cid: string, body: { kind: string; lane: string; start_ms: number; duration_ms: number; prompt: string; gain_db?: number }) =>
    req<TimelineData>(`/api/chapters/${encodeURIComponent(cid)}/timeline/segment`, { method: "POST", body: JSON.stringify(body) }),
  deleteSegment: (cid: string, segId: string) =>
    req<TimelineData>(`/api/chapters/${encodeURIComponent(cid)}/timeline/segment/${encodeURIComponent(segId)}`, { method: "DELETE" }),
  regenerateSegment: (cid: string, segId: string, body: { prompt?: string; duration_ms?: number }) =>
    req<{ job_id: string }>(`/api/chapters/${encodeURIComponent(cid)}/timeline/segment/${encodeURIComponent(segId)}/regenerate`, { method: "POST", body: JSON.stringify(body) }),
};
