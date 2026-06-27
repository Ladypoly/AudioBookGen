import { useEffect, useMemo, useRef, useState } from "react";
import { api, pickFolder, isElectron, type JobView, type SetupStatus } from "../lib/api";

function Row({ ok, label, value }: { ok: boolean; label: string; value?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${ok ? "bg-good shadow-[0_0_6px] shadow-good/60" : "bg-bad"}`} />
      <span className="text-text">{label}</span>
      {value && <span className="ml-auto truncate font-mono text-xs text-faint">{value}</span>}
    </div>
  );
}

export function SetupWizard({ jobs, onClose }: { jobs: JobView[]; onClose: () => void }) {
  const [st, setSt] = useState<SetupStatus | null>(null);
  const [installId, setInstallId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const refresh = () => api.setupStatus().then(setSt).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const installJob = useMemo(() => jobs.find((j) => j.id === installId), [jobs, installId]);
  const log = (installJob?.meta?.log as string[] | undefined) ?? [];
  const installing = installJob?.state === "running" || installJob?.state === "pending";

  // re-probe when the install finishes
  useEffect(() => {
    if (installJob && (installJob.state === "done" || installJob.state === "failed")) {
      if (installJob.state === "failed") setErr(installJob.error ?? "Install failed");
      refresh();
    }
  }, [installJob?.state]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log.length]);

  const chooseDir = async () => {
    const dir = await pickFolder();
    if (!dir) return;
    setErr(null);
    setBusy(true);
    try {
      setSt(await api.setComfyDir(dir));
    } catch (e: any) {
      setErr(String(e?.message ?? e).replace(/^\d+ [^:]+:\s*/, ""));
    } finally {
      setBusy(false);
    }
  };

  const install = async () => {
    setErr(null);
    try {
      const { job_id } = await api.installNode();
      setInstallId(job_id);
    } catch (e: any) {
      setErr(String(e?.message ?? e));
    }
  };

  const ready = st?.comfy_dir_valid && st?.node_installed;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[88vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl">
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-base font-semibold">Set up AudioBookGen</h2>
          <button onClick={onClose} className="text-faint hover:text-text">✕</button>
        </header>

        <div className="flex flex-col gap-4 overflow-y-auto p-5">
          <p className="text-xs text-muted">
            AudioBookGen drives <b>Ollama</b> (LLM) and <b>ComfyUI</b> (image / voice / audio). It can't run the
            GPU stages without ComfyUI and the <code>tts_audio_suite</code> node.
          </p>

          {/* Ollama */}
          <section className="rounded-lg border border-border bg-surface-2 p-3">
            <Row ok={!!st?.ollama} label={st?.ollama ? "Ollama detected" : "Ollama not found (localhost:11434)"} />
            {!st?.ollama && (
              <p className="mt-1 text-xs text-faint">
                Optional if you use a cloud LLM. Otherwise install Ollama and <code>ollama pull</code> a model.
              </p>
            )}
          </section>

          {/* ComfyUI path */}
          <section className="rounded-lg border border-border bg-surface-2 p-3">
            <Row
              ok={!!st?.comfy_dir_valid}
              label={st?.comfy_dir_valid ? "ComfyUI folder set" : "ComfyUI folder not set / invalid"}
              value={st?.comfy_dir}
            />
            <div className="mt-2 flex items-center gap-2">
              <button
                onClick={chooseDir}
                disabled={busy || !isElectron()}
                className="rounded-md border border-border-strong px-3 py-1 text-xs text-muted hover:text-text disabled:opacity-40"
              >
                Choose ComfyUI folder…
              </button>
              {!isElectron() && <span className="text-xs text-faint">Set the path in Settings (browser dev mode)</span>}
            </div>
          </section>

          {/* node */}
          <section className="rounded-lg border border-border bg-surface-2 p-3">
            <Row
              ok={!!st?.node_installed}
              label={st?.node_installed ? "tts_audio_suite installed" : "tts_audio_suite not installed"}
            />
            {!st?.node_installed && st?.comfy_dir_valid && (
              <div className="mt-2">
                {!st?.git_available && (
                  <p className="mb-2 text-xs text-warn">git not found on PATH — install Git for Windows, then retry.</p>
                )}
                <button
                  onClick={install}
                  disabled={installing || !st?.git_available}
                  className="rounded-md bg-accent-strong px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent disabled:opacity-50"
                >
                  {installing ? "Installing…" : "Install tts_audio_suite"}
                </button>
                <p className="mt-1 text-xs text-faint">Clones the node and pip-installs its deps (several minutes).</p>
              </div>
            )}
            {(installing || log.length > 0) && (
              <div ref={logRef} className="mt-2 max-h-40 overflow-y-auto rounded bg-bg p-2 font-mono text-[10px] leading-snug text-faint">
                {log.map((l, i) => <div key={i} className="whitespace-pre-wrap">{l}</div>)}
              </div>
            )}
          </section>

          {err && <p className="text-xs text-bad">{err}</p>}
        </div>

        <footer className="flex items-center justify-between border-t border-border px-5 py-3">
          <button onClick={refresh} className="text-xs text-faint hover:text-text">Re-check</button>
          <button
            onClick={onClose}
            className={`rounded-md px-4 py-1.5 text-sm font-semibold ${ready ? "bg-accent-strong text-white hover:bg-accent" : "border border-border-strong text-muted hover:text-text"}`}
          >
            {ready ? "Done" : "Continue anyway"}
          </button>
        </footer>
      </div>
    </div>
  );
}
