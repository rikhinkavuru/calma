"use client";
import { useFormStatus } from "react-dom";
import { submitAction } from "../actions";
import type { RecipeGroup } from "./recipeCatalog";
import styles from "../dashboard.module.css";

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className={styles.btn} disabled={pending}>
      {pending ? "Re-executing & recomputing…" : "Submit & verify"}
    </button>
  );
}

export function SubmitForm({ recipeGroups }: { recipeGroups: RecipeGroup[] }) {
  return (
    <form action={submitAction}>
      <div className={styles.field}>
        <label className={styles.label}>Bundle (.tar.gz)</label>
        <input className={styles.file} type="file" name="bundle" accept=".gz,.tgz,application/gzip" required />
        <p className={styles.hint}>
          A gzipped tar of your result: a <code>verify.yaml</code> contract plus the entrypoint that produces
          the raw outputs. Don&apos;t hand-write it — run <code>calma draft ./your-repo</code> to generate one
          (see the <a href="/install">CLI guide</a>), or click <strong>Run the demo</strong> above to try a sample first.
          The run is offline (network off); recompute happens host-side.
        </p>
      </div>

      <div className={styles.field}>
        <label className={styles.label}>Recipe — the metric to recompute</label>
        <select className={styles.input} name="recipe_id" defaultValue="trading.total_return">
          {recipeGroups.map((g) => (
            <optgroup key={g.title} label={g.title}>
              {g.options.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <p className={styles.hint}>
          What Calma recomputes from your raw outputs. Unsure which one? <a href="/recipes">Browse the catalog</a>.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div className={styles.field}>
          <label className={styles.label}>Claimed metric (optional)</label>
          <input className={styles.input} name="metric" placeholder="total_return" />
          <p className={styles.hint}>The number your result reported. Leave both blank to just recompute it.</p>
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Claimed value (optional)</label>
          <input className={styles.input} name="value" type="number" step="any" placeholder="0.0077" />
          <p className={styles.hint}>Calma diffs this against the recomputed value to prove or break it.</p>
        </div>
      </div>

      <details style={{ marginTop: 8, marginBottom: 18 }}>
        <summary className={styles.label} style={{ cursor: "pointer" }}>Advanced (sensible defaults — most runs don&apos;t need these)</summary>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 12 }}>
          <div className={styles.field}>
            <label className={styles.label}>Entrypoint</label>
            <input className={styles.input} name="entrypoint" defaultValue="gen.py" />
            <p className={styles.hint}>The script inside the bundle that produces the outputs (also pinned by verify.yaml).</p>
          </div>
          <div className={styles.field}>
            <label className={styles.label}>Trust</label>
            <select className={styles.input} name="trust" defaultValue="own-code">
              <option value="own-code">own-code</option>
              <option value="untrusted-third-party">untrusted-third-party</option>
            </select>
            <p className={styles.hint}>Use untrusted-third-party for code you didn&apos;t write — it runs under stricter isolation.</p>
          </div>
          <div className={styles.field}>
            <label className={styles.label}>Recipe version</label>
            <input className={styles.input} name="recipe_version" defaultValue="1.0.0" />
            <p className={styles.hint}>Pins the exact recipe definition; leave at the default unless you need an older one.</p>
          </div>
        </div>
      </details>

      <SubmitButton />
    </form>
  );
}
