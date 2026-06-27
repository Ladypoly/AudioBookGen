import { useEffect, useMemo, useState } from "react";
import { api, type SettingField, type SettingsSchema } from "../lib/api";
import { LlmSettings } from "./LlmSettings";

function Field({
  field,
  value,
  onChange,
}: {
  field: SettingField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const base =
    "w-full rounded-lg border border-border-strong bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent";

  let input;
  if (field.kind === "bool") {
    input = (
      <button
        onClick={() => onChange(!value)}
        className={`relative h-6 w-11 rounded-full transition ${value ? "bg-accent-strong" : "bg-elevated"}`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${
            value ? "left-[22px]" : "left-0.5"
          }`}
        />
      </button>
    );
  } else if (field.kind === "choice" && field.choices) {
    input = (
      <select className={base} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        {field.choices.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    );
  } else if (field.kind === "int" || field.kind === "float") {
    input = (
      <input
        type="number"
        step={field.kind === "float" ? "0.01" : "1"}
        className={base}
        value={Number(value ?? 0)}
        onChange={(e) => onChange(field.kind === "float" ? parseFloat(e.target.value) : parseInt(e.target.value))}
      />
    );
  } else {
    input = (
      <input
        type={field.kind === "password" ? "password" : "text"}
        className={base}
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  return (
    <div className="flex items-center justify-between gap-6 py-2.5">
      <label className="text-sm text-muted">{field.label}</label>
      <div className="w-[280px] shrink-0">{input}</div>
    </div>
  );
}

export function Settings() {
  const [schema, setSchema] = useState<SettingsSchema | null>(null);
  const [section, setSection] = useState(0);
  const [dirty, setDirty] = useState<Record<string, unknown>>({});
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.settingsSchema().then(setSchema).catch(() => {});
  }, []);

  const current = useMemo(() => {
    const map: Record<string, unknown> = {};
    schema?.sections.forEach((s) => s.fields.forEach((f) => (map[f.path] = f.value)));
    return { ...map, ...dirty };
  }, [schema, dirty]);

  if (!schema) return <div className="px-8 py-7 text-sm text-faint">Loading settings…</div>;

  const active = schema.sections[section];
  const hasChanges = Object.keys(dirty).length > 0;

  const save = async () => {
    await api.saveSettings(dirty);
    setDirty({});
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
  };

  return (
    <div className="mx-auto max-w-5xl px-8 py-7">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Settings</h1>
      <div className="flex gap-6">
        {/* Left-nav of sections, inside the settings content window. */}
        <nav className="flex w-44 shrink-0 flex-col gap-1">
          {schema.sections.map((s, i) => (
            <button
              key={s.name}
              onClick={() => setSection(i)}
              className={`rounded-lg px-3 py-2 text-left text-sm transition ${
                i === section ? "bg-elevated text-text" : "text-muted hover:bg-surface-2"
              }`}
            >
              {s.name}
            </button>
          ))}
        </nav>

        {/* Section panel */}
        <div className="min-w-0 flex-1 rounded-[var(--radius-card)] border border-border bg-surface p-5">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-accent">{active.name}</h2>
          {active.name === "LLM" ? (
            <LlmSettings />
          ) : (
            <div className="divide-y divide-border">
              {active.fields.map((f) => (
                <Field
                  key={f.path}
                  field={f}
                  value={current[f.path]}
                  onChange={(v) => setDirty((d) => ({ ...d, [f.path]: v }))}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* LLM has its own Save inside the panel */}
      {active.name !== "LLM" && (
        <div className="mt-5 flex items-center justify-end gap-3">
          {saved && <span className="text-sm text-good">Saved ✓</span>}
          <button
            disabled={!hasChanges}
            onClick={save}
            className="rounded-lg bg-accent-strong px-5 py-2 text-sm font-semibold text-white transition enabled:hover:bg-accent disabled:opacity-40"
          >
            Save changes
          </button>
        </div>
      )}
    </div>
  );
}
