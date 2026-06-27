import { useEffect, useState } from "react";
import { api, type CloudModel, type ProviderInfo } from "../lib/api";
import { CloudModelPicker } from "./CloudModelPicker";

const inputCls =
  "w-full rounded-lg border border-border-strong bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent";
const labelCls = "text-xs text-faint";

interface Llm {
  backend: string;
  local_provider: string;
  base_url: string;
  model: string;
  cloud_provider: string;
  api_base_url: string;
  api_key: string;
  api_model: string;
  temperature: number;
  extraction_model: string;
  refine_model: string;
  prompt_model: string;
}

const KEYS: Record<keyof Llm, string> = {
  backend: "ollama.backend",
  local_provider: "ollama.local_provider",
  base_url: "ollama.base_url",
  model: "ollama.model",
  cloud_provider: "ollama.cloud_provider",
  api_base_url: "ollama.api_base_url",
  api_key: "ollama.api_key",
  api_model: "ollama.api_model",
  temperature: "ollama.temperature",
  extraction_model: "ollama.extraction_model",
  refine_model: "ollama.refine_model",
  prompt_model: "ollama.prompt_model",
};

function Seg({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 rounded-md px-3 py-1.5 text-sm transition ${
        active ? "bg-accent-strong text-white" : "text-muted hover:text-text"
      }`}
    >
      {children}
    </button>
  );
}

export function LlmSettings() {
  const [v, setV] = useState<Llm | null>(null);
  const [providers, setProviders] = useState<{ local: ProviderInfo[]; cloud: ProviderInfo[] }>({ local: [], cloud: [] });
  const [localModels, setLocalModels] = useState<string[]>([]);
  const [cloudModels, setCloudModels] = useState<CloudModel[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [saved, setSaved] = useState(false);

  // load current values + providers
  useEffect(() => {
    api.getSettings().then((s) => {
      setV({
        backend: String(s[KEYS.backend] ?? "local"),
        local_provider: String(s[KEYS.local_provider] ?? "ollama"),
        base_url: String(s[KEYS.base_url] ?? "http://localhost:11434"),
        model: String(s[KEYS.model] ?? ""),
        cloud_provider: String(s[KEYS.cloud_provider] ?? "openrouter"),
        api_base_url: String(s[KEYS.api_base_url] ?? ""),
        api_key: String(s[KEYS.api_key] ?? ""),
        api_model: String(s[KEYS.api_model] ?? ""),
        temperature: Number(s[KEYS.temperature] ?? 0.45),
        extraction_model: String(s[KEYS.extraction_model] ?? ""),
        refine_model: String(s[KEYS.refine_model] ?? ""),
        prompt_model: String(s[KEYS.prompt_model] ?? ""),
      });
    });
    api.providers().then(setProviders).catch(() => {});
  }, []);

  const set = (patch: Partial<Llm>) => setV((cur) => (cur ? { ...cur, ...patch } : cur));

  // fetch local models when local config changes
  useEffect(() => {
    if (!v || v.backend !== "local") return;
    setLoadingModels(true);
    api.localModels(v.local_provider, v.base_url)
      .then(setLocalModels)
      .catch(() => setLocalModels([]))
      .finally(() => setLoadingModels(false));
  }, [v?.backend, v?.local_provider, v?.base_url]);

  // fetch cloud models when cloud config changes
  useEffect(() => {
    if (!v || v.backend !== "cloud" || !v.api_base_url) return;
    setLoadingModels(true);
    api.cloudModels(v.api_base_url, v.api_key)
      .then(setCloudModels)
      .catch(() => setCloudModels([]))
      .finally(() => setLoadingModels(false));
  }, [v?.backend, v?.api_base_url, v?.api_key]);

  if (!v) return <p className="text-sm text-faint">Loading…</p>;

  const save = async () => {
    await api.saveSettings(Object.fromEntries(Object.entries(KEYS).map(([k, path]) => [path, (v as any)[k]])));
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* backend toggle */}
      <div className="flex rounded-lg border border-border-strong p-0.5">
        <Seg active={v.backend === "local"} onClick={() => set({ backend: "local" })}>
          💻 Local
        </Seg>
        <Seg active={v.backend === "cloud"} onClick={() => set({ backend: "cloud" })}>
          ☁️ Cloud API
        </Seg>
      </div>

      {v.backend === "local" ? (
        <>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>Provider</span>
            <select
              className={inputCls}
              value={v.local_provider}
              onChange={(e) => {
                const p = providers.local.find((x) => x.id === e.target.value);
                set({ local_provider: e.target.value, base_url: p?.base_url ?? v.base_url });
              }}
            >
              {providers.local.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>Server URL</span>
            <input className={inputCls} value={v.base_url} onChange={(e) => set({ base_url: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>Model {loadingModels && <span className="text-faint">· loading…</span>}</span>
            <select className={inputCls} value={v.model} onChange={(e) => set({ model: e.target.value })}>
              {!localModels.includes(v.model) && v.model && <option value={v.model}>{v.model} (current)</option>}
              {!localModels.length && <option value="">— no models found at this URL —</option>}
              {localModels.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>

          {/* Per-phase model "orchestra" — speeds up extraction by running the
              high-volume Pass A on a fast small model. Empty = use Model above. */}
          <div className="rounded-lg border border-border bg-surface-2 p-3">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-accent">Extraction orchestra</div>
            <p className="mb-2 text-xs text-faint">
              Optional per-phase models (empty = use the Model above). Run the high-volume
              cast pass on a fast small model (e.g. qwen3.5:4b), the rest on your main model.
              Tip: set <code>OLLAMA_NUM_PARALLEL=6</code> on the Ollama server.
            </p>
            {([
              ["extraction_model", "Pass A — read cast (fast/small)"],
              ["refine_model", "Pass B — speaker refine"],
              ["prompt_model", "Style / portraits / intro lines"],
            ] as [keyof Llm, string][]).map(([key, label]) => (
              <label key={key} className="mb-2 flex flex-col gap-1 last:mb-0">
                <span className={labelCls}>{label}</span>
                <select className={inputCls} value={String(v[key])} onChange={(e) => set({ [key]: e.target.value } as Partial<Llm>)}>
                  <option value="">Default ({v.model || "main model"})</option>
                  {String(v[key]) && !localModels.includes(String(v[key])) && (
                    <option value={String(v[key])}>{String(v[key])} (current)</option>
                  )}
                  {localModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </>
      ) : (
        <>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>Provider</span>
            <select
              className={inputCls}
              value={v.cloud_provider}
              onChange={(e) => {
                const p = providers.cloud.find((x) => x.id === e.target.value);
                set({
                  cloud_provider: e.target.value,
                  api_base_url: e.target.value === "custom" ? v.api_base_url : p?.base_url ?? v.api_base_url,
                });
              }}
            >
              {providers.cloud.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>API base URL</span>
            <input
              className={inputCls}
              value={v.api_base_url}
              readOnly={v.cloud_provider !== "custom"}
              onChange={(e) => set({ api_base_url: e.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>API key</span>
            <input
              type="password"
              className={inputCls}
              value={v.api_key}
              onChange={(e) => set({ api_key: e.target.value })}
              placeholder="sk-…"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>Model {loadingModels && <span className="text-faint">· loading…</span>}</span>
            <CloudModelPicker
              value={v.api_model}
              models={cloudModels}
              loading={loadingModels}
              onChange={(id) => set({ api_model: id })}
            />
          </label>
        </>
      )}

      <label className="flex flex-col gap-1">
        <span className={labelCls}>Temperature · {v.temperature.toFixed(2)}</span>
        <input
          type="range"
          min={0}
          max={1.5}
          step={0.05}
          value={v.temperature}
          onChange={(e) => set({ temperature: parseFloat(e.target.value) })}
          className="w-full accent-[var(--color-accent)]"
        />
      </label>

      <div className="flex items-center justify-end gap-3">
        {saved && <span className="text-sm text-good">Saved ✓</span>}
        <button onClick={save} className="rounded-lg bg-accent-strong px-5 py-2 text-sm font-semibold text-white hover:bg-accent">
          Save LLM settings
        </button>
      </div>
    </div>
  );
}
