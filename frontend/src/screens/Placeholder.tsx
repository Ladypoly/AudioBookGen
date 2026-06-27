export function Placeholder({ title, note }: { title: string; note: string }) {
  return (
    <div className="mx-auto max-w-6xl px-8 py-7">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <div className="mt-6 flex flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed border-border-strong py-20 text-center">
        <p className="text-sm text-muted">{note}</p>
      </div>
    </div>
  );
}
