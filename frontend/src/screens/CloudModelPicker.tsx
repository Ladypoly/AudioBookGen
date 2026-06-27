import { useMemo, useRef, useState } from "react";
import type { CloudModel } from "../lib/api";

const TIER_COLOR: Record<string, string> = {
  cheap: "#4ade80",
  medium: "#f4c361",
  expensive: "#f4707a",
  unknown: "#8b93a7",
};

const fmt = (n: number | null): string => {
  if (n == null) return "?";
  return `$${n.toFixed(2)}`; // always exactly 2 decimals, no float artifacts
};

function price(m: CloudModel): string {
  if (m.prompt == null && m.completion == null) return "";
  return `${fmt(m.prompt)} / ${fmt(m.completion)} per 1M`;
}

function Badge({ tier }: { tier: string }) {
  return (
    <span
      className="shrink-0 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase"
      style={{ background: `${TIER_COLOR[tier]}26`, color: TIER_COLOR[tier] }}
    >
      {tier}
    </span>
  );
}

export function CloudModelPicker({
  value,
  models,
  loading,
  onChange,
}: {
  value: string;
  models: CloudModel[];
  loading: boolean;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q ? models.filter((m) => m.id.toLowerCase().includes(q)) : models;
    return list.slice(0, 60);
  }, [models, query]);

  const current = models.find((m) => m.id === value);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-lg border border-border-strong bg-bg px-3 py-2 text-left text-sm text-text outline-none focus:border-accent"
      >
        <span className="min-w-0 flex-1 truncate">{value || "Select a model…"}</span>
        {current && <Badge tier={current.tier} />}
        <span className="text-faint">▾</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onMouseDown={() => setOpen(false)} />
          <div className="absolute z-40 mt-1 w-full overflow-hidden rounded-lg border border-border-strong bg-surface shadow-2xl">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={loading ? "loading models…" : `search ${models.length} models…`}
              className="w-full border-b border-border bg-bg px-3 py-2 text-sm text-text outline-none"
            />
            <div className="max-h-[300px] overflow-y-auto">
              {filtered.map((m) => (
                <button
                  key={m.id}
                  onClick={() => {
                    onChange(m.id);
                    setOpen(false);
                    setQuery("");
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface-2 ${
                    m.id === value ? "bg-elevated" : ""
                  }`}
                >
                  <span className="min-w-0 flex-1 truncate text-text">{m.id}</span>
                  <span className="shrink-0 text-[10px] text-faint">{price(m)}</span>
                  <Badge tier={m.tier} />
                </button>
              ))}
              {!filtered.length && (
                <p className="px-3 py-3 text-xs text-faint">{loading ? "loading…" : "no matches"}</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
