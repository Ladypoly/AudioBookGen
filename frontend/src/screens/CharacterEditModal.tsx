import { useEffect, useState } from "react";
import { api, type CharacterView, type VariantView } from "../lib/api";
import { AGE_BANDS, AGE_LABEL, GENDERS, GENDER_LABEL, ROLES } from "../lib/labels";

const inputCls =
  "w-full rounded-lg border border-border-strong bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent";

function Select({
  value,
  options,
  labels,
  onChange,
}: {
  value: string;
  options: string[];
  labels?: Record<string, string>;
  onChange: (v: string) => void;
}) {
  return (
    <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => (
        <option key={o} value={o}>
          {labels?.[o] ?? o}
        </option>
      ))}
    </select>
  );
}

function emptyVariant(): VariantView {
  return {
    age_band: "child",
    label: "",
    appearance_description: "",
    portrait_prompt: "",
    portrait_path: null,
    voice_sample: null,
    custom_voice: false,
    voice_hint: "",
  };
}

export function CharacterEditModal({
  c,
  others,
  onClose,
  onSaved,
}: {
  c: CharacterView;
  others: CharacterView[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(c.display_name);
  const [gender, setGender] = useState(c.gender_guess);
  const [age, setAge] = useState(c.age_band);
  const [role, setRole] = useState(c.role_importance);
  const [voiceHint, setVoiceHint] = useState(c.voice_hint);
  const [desc, setDesc] = useState(c.appearance_description);
  const [traits, setTraits] = useState(c.vocal_traits.join(", "));
  const [sampleLine, setSampleLine] = useState(c.sample_line);
  const [ttsWorkflow, setTtsWorkflow] = useState(c.tts_workflow);
  const [workflows, setWorkflows] = useState<{ workflows: string[]; default_tts: string } | null>(null);
  useEffect(() => { api.listWorkflows().then(setWorkflows).catch(() => {}); }, []);
  const [variants, setVariants] = useState<VariantView[]>(c.variants);
  const [saving, setSaving] = useState(false);
  const [mergeId, setMergeId] = useState("");
  const [merging, setMerging] = useState(false);
  const [mergeErr, setMergeErr] = useState<string | null>(null);

  const doMerge = async () => {
    if (!mergeId) return;
    const other = others.find((o) => o.character_id === mergeId);
    if (!other) return;
    if (!window.confirm(`Merge "${other.display_name}" into "${name}"?\n\nIts script lines move to ${name}, and "${other.display_name}" is deleted. This cannot be undone.`))
      return;
    setMerging(true);
    setMergeErr(null);
    try {
      await api.mergeCharacter(c.character_id, mergeId);
      onSaved();
    } catch (e: any) {
      setMergeErr(String(e?.message ?? e));
      setMerging(false);
    }
  };

  const setVariant = (i: number, patch: Partial<VariantView>) =>
    setVariants((vs) => vs.map((v, j) => (j === i ? { ...v, ...patch } : v)));

  const save = async () => {
    setSaving(true);
    try {
      await api.updateCharacter(c.character_id, {
        display_name: name,
        gender_guess: gender,
        age_band: age,
        role_importance: role,
        voice_hint: voiceHint,
        appearance_description: desc,
        vocal_traits: traits.split(",").map((t) => t.trim()).filter(Boolean),
        sample_line: sampleLine,
        tts_workflow: ttsWorkflow,
        variants,
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="flex max-h-[88vh] w-[620px] max-w-[94vw] flex-col rounded-2xl border border-border bg-surface shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-lg font-semibold">Edit character</h2>
          <button onClick={onClose} className="text-faint transition hover:text-text">
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="grid grid-cols-2 gap-3">
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-faint">Name</span>
              <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-faint">Gender</span>
              <Select value={gender} options={GENDERS} labels={GENDER_LABEL} onChange={setGender} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-faint">Age</span>
              <Select value={age} options={AGE_BANDS} labels={AGE_LABEL} onChange={setAge} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-faint">Role</span>
              <Select value={role} options={ROLES} onChange={setRole} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-faint">Voice hint</span>
              <input className={inputCls} value={voiceHint} onChange={(e) => setVoiceHint(e.target.value)} />
            </label>
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-faint">Appearance description</span>
              <textarea
                className={`${inputCls} h-20 resize-none`}
                value={desc}
                onChange={(e) => setDesc(e.target.value)}
              />
            </label>
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-faint">Vocal traits (comma-separated)</span>
              <input className={inputCls} value={traits} onChange={(e) => setTraits(e.target.value)} />
            </label>
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-faint">
                Voice sample line — spoken to make the ~10s clone reference
              </span>
              <textarea
                className={`${inputCls} h-24 resize-none`}
                value={sampleLine}
                placeholder="The in-character intro this voice will speak (written at extraction; edit freely)."
                onChange={(e) => setSampleLine(e.target.value)}
              />
            </label>
            <label className="col-span-2 flex flex-col gap-1">
              <span className="text-xs text-faint">
                Voice engine — overrides the default for this character (e.g. OmniVoice for the narrator)
              </span>
              <select className={inputCls} value={ttsWorkflow} onChange={(e) => setTtsWorkflow(e.target.value)}>
                <option value="">
                  Default{workflows ? ` (${workflows.default_tts})` : ""}
                </option>
                {workflows?.workflows.map((w) => (
                  <option key={w} value={w}>{w}</option>
                ))}
              </select>
            </label>
          </div>

          {/* Age variants */}
          <div className="mt-5">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-accent">Age variations</span>
              <button
                onClick={() => setVariants((vs) => [...vs, emptyVariant()])}
                className="rounded-md border border-border-strong px-2 py-1 text-xs text-muted transition hover:text-text"
              >
                + Add age
              </button>
            </div>
            {!variants.length && (
              <p className="text-xs text-faint">
                No age variations. Add one to give this character a separate look + voice at another age
                (shows as slide-dots on the card).
              </p>
            )}
            <div className="flex flex-col gap-3">
              {variants.map((v, i) => (
                <div key={i} className="rounded-lg border border-border bg-surface-2 p-3">
                  <div className="flex items-center gap-2">
                    <div className="w-40">
                      <Select
                        value={v.age_band}
                        options={AGE_BANDS}
                        labels={AGE_LABEL}
                        onChange={(val) => setVariant(i, { age_band: val })}
                      />
                    </div>
                    <input
                      placeholder="label (e.g. as a child)"
                      className={inputCls}
                      value={v.label}
                      onChange={(e) => setVariant(i, { label: e.target.value })}
                    />
                    <button
                      onClick={() => setVariants((vs) => vs.filter((_, j) => j !== i))}
                      className="shrink-0 text-faint transition hover:text-bad"
                      title="Remove"
                    >
                      🗑
                    </button>
                  </div>
                  <textarea
                    placeholder="appearance at this age (optional — defaults to the main description)"
                    className={`${inputCls} mt-2 h-16 resize-none`}
                    value={v.appearance_description}
                    onChange={(e) => setVariant(i, { appearance_description: e.target.value })}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Merge */}
          {others.length > 0 && (
            <div className="mt-5 rounded-lg border border-border bg-surface-2 p-3">
              <span className="text-xs font-semibold uppercase tracking-wide text-accent">Merge</span>
              <p className="mt-1 text-xs text-faint">
                Fold another character into <b className="text-muted">{name}</b>. Its script lines move here and it’s deleted.
              </p>
              <div className="mt-2 flex items-center gap-2">
                <select className={`${inputCls} flex-1`} value={mergeId} onChange={(e) => setMergeId(e.target.value)}>
                  <option value="">Choose a character…</option>
                  {others.map((o) => (
                    <option key={o.character_id} value={o.character_id}>
                      {o.display_name} ({o.spoken_lines} lines)
                    </option>
                  ))}
                </select>
                <button
                  onClick={doMerge}
                  disabled={!mergeId || merging}
                  className="shrink-0 rounded-lg border border-bad/50 px-3 py-2 text-sm text-bad transition hover:bg-bad/10 disabled:opacity-50"
                >
                  {merging ? "Merging…" : "Merge in"}
                </button>
              </div>
              {mergeErr && <p className="mt-1 text-xs text-bad">{mergeErr}</p>}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-3 border-t border-border px-6 py-4">
          <button onClick={onClose} className="rounded-lg border border-border-strong px-4 py-2 text-sm text-muted transition hover:text-text">
            Cancel
          </button>
          <button
            disabled={saving || !name.trim()}
            onClick={save}
            className="rounded-lg bg-accent-strong px-5 py-2 text-sm font-semibold text-white transition hover:bg-accent disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
