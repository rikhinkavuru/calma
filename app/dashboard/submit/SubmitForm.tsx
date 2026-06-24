"use client";
import { useFormStatus } from "react-dom";
import { submitAction } from "../actions";
import styles from "../dashboard.module.css";

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button type="submit" className={styles.btn} disabled={pending}>
      {pending ? "Re-executing & recomputing…" : "Submit & verify"}
    </button>
  );
}

export function SubmitForm() {
  return (
    <form action={submitAction}>
      <div className={styles.field}>
        <label className={styles.label}>Bundle (.tar.gz)</label>
        <input className={styles.file} type="file" name="bundle" accept=".gz,.tgz,application/gzip" required />
        <p className={styles.hint}>A gzipped tar with a <code>verify.yaml</code> contract + your entrypoint. The run is offline (network off); recompute happens host-side.</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div className={styles.field}>
          <label className={styles.label}>Recipe</label>
          <input className={styles.input} name="recipe_id" defaultValue="trading.total_return" />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Recipe version</label>
          <input className={styles.input} name="recipe_version" defaultValue="1.0.0" />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Entrypoint</label>
          <input className={styles.input} name="entrypoint" defaultValue="gen.py" />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Trust</label>
          <select className={styles.input} name="trust" defaultValue="own-code">
            <option value="own-code">own-code</option>
            <option value="untrusted-third-party">untrusted-third-party</option>
          </select>
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Claimed metric (optional)</label>
          <input className={styles.input} name="metric" placeholder="total_return" />
        </div>
        <div className={styles.field}>
          <label className={styles.label}>Claimed value (optional)</label>
          <input className={styles.input} name="value" type="number" step="any" placeholder="0.0077" />
        </div>
      </div>

      <SubmitButton />
    </form>
  );
}
