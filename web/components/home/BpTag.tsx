export function BpTag({ label, n, total = 6 }: { label: string; n: number; total?: number }) {
  return (
    <div className="bp-tag">
      <span className="bp-tag__l"><b>›</b>{label}</span>
      <span className="bp-tag__r">[ <b>{n}</b> / {total} ]</span>
    </div>
  );
}
