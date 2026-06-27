import { useEffect, useRef, useState } from "react";

export interface SfxAdd {
  kind: "prompt" | "file";
  prompt?: string;
  placement: string;
  file?: File;
}

export function SfxPopup({
  rect,
  onAdd,
  onClose,
}: {
  rect: { left: number; top: number; bottom: number };
  onAdd: (a: SfxAdd) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"prompt" | "file">("prompt");
  const [prompt, setPrompt] = useState("");
  const [placement, setPlacement] = useState("gap");
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const left = Math.min(rect.left, window.innerWidth - 340);
  const top = Math.min(rect.bottom + 8, window.innerHeight - 280);

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onClose]);

  const pickFile = (f: File | undefined) => f && onAdd({ kind: "file", file: f, placement });

  return (
    <>
      <div className="fixed inset-0 z-40" onMouseDown={onClose} />
      <div
        className="fixed z-50 w-[320px] rounded-xl border border-border-strong bg-surface p-3 shadow-2xl"
        style={{ left, top }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold text-text">Add sound effect</span>
          <div className="flex rounded-lg border border-border-strong p-0.5">
            {(["prompt", "file"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-md px-2 py-0.5 text-[11px] transition ${
                  tab === t ? "bg-elevated text-text" : "text-muted hover:text-text"
                }`}
              >
                {t === "prompt" ? "Generate" : "File"}
              </button>
            ))}
          </div>
        </div>

        <div className="mb-2 flex items-center gap-2 text-[11px] text-faint">
          <span>Placement</span>
          <select
            value={placement}
            onChange={(e) => setPlacement(e.target.value)}
            className="rounded-md border border-border-strong bg-bg px-2 py-1 text-text outline-none"
          >
            <option value="gap">In the pause after</option>
            <option value="over">Under the line</option>
          </select>
        </div>

        {tab === "prompt" ? (
          <div>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="describe the sound (English) — e.g. distant thunder rumble"
              className="h-16 w-full resize-none rounded-lg border border-border-strong bg-bg px-2 py-1.5 text-sm text-text outline-none focus:border-accent"
            />
            <div className="mt-2 flex justify-end">
              <button
                disabled={!prompt.trim()}
                onClick={() => onAdd({ kind: "prompt", prompt: prompt.trim(), placement })}
                className="rounded-lg bg-accent-strong px-3 py-1 text-xs font-semibold text-white hover:bg-accent disabled:opacity-50"
              >
                Add (generate)
              </button>
            </div>
          </div>
        ) : (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              pickFile(e.dataTransfer.files?.[0]);
            }}
            onClick={() => fileRef.current?.click()}
            className={`flex h-24 cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed text-center text-xs transition ${
              drag ? "border-accent bg-accent/10 text-accent" : "border-border-strong text-faint hover:text-muted"
            }`}
          >
            <span className="text-lg">🎵</span>
            Drag an audio file here, or click to choose
            <input
              ref={fileRef}
              type="file"
              accept="audio/*"
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0])}
            />
          </div>
        )}
      </div>
    </>
  );
}
