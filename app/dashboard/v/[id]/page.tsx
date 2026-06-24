import Link from "next/link";
import { calma, type Verification } from "@/lib/calma";
import { getSession } from "@/lib/session";
import { StatusBadge, VerdictBadge } from "../../Badge";
import styles from "../../dashboard.module.css";

export const dynamic = "force-dynamic";

export default async function Detail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const s = (await getSession())!;
  let v: Verification | null = null;
  let proof: Record<string, unknown> | null = null;
  let error: string | null = null;
  try {
    v = await calma.getVerification(s.tenantId, id);
    try { proof = await calma.getProof(s.tenantId, id); } catch { /* proof may not exist yet */ }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error || !v) {
    return (
      <div className={styles.main}>
        <Link href="/dashboard" className={styles.back}>← Verifications</Link>
        <div className={`${styles.notice} ${styles.noticeErr}`} style={{ marginTop: 16 }}>{error || "Not found"}</div>
      </div>
    );
  }

  const r = v.recomputed || {};
  const ex = v.execution || {};
  return (
    <div className={styles.main}>
      <Link href="/dashboard" className={styles.back}>← Verifications</Link>
      <div className={styles.row} style={{ marginTop: 14 }}>
        <div>
          <h1 className={styles.h1}>{v.recipe.id} <span className={styles.muted}>@{v.recipe.version}</span></h1>
          <p className={styles.sub}><span className={styles.mono}>{v.verification_id}</span></p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <VerdictBadge verdict={v.verdict} />
          <StatusBadge status={v.status} />
        </div>
      </div>

      <div className={styles.detailGrid}>
        <div className={styles.kv}>
          <div className={styles.kvLabel}>Claimed{v.claim?.metric ? ` · ${v.claim.metric}` : ""}</div>
          <div className={styles.kvValue}>{v.claim?.value ?? "—"}</div>
        </div>
        <div className={styles.kv}>
          <div className={styles.kvLabel}>Recomputed (ground truth)</div>
          <div className={styles.kvValue}>{r.value ?? "—"}</div>
        </div>
        <div className={styles.kv}>
          <div className={styles.kvLabel}>Absolute difference</div>
          <div className={styles.kvValue}>{r.abs_diff ?? "—"}</div>
        </div>
        <div className={styles.kv}>
          <div className={styles.kvLabel}>Within tolerance</div>
          <div className={styles.kvValue}>{r.within_tolerance === undefined ? "—" : r.within_tolerance ? "yes" : "no"}</div>
        </div>
      </div>

      {v.reason && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Reason</div>
          <div className={styles.pre}>{v.reason}</div>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionTitle}>Execution</div>
        <div className={styles.pre}>
          isolation_tier : {ex.isolation_tier || "—"}{"\n"}
          tier_verified  : {String(ex.tier_verified)}{"\n"}
          network_run    : {ex.network_run || "—"}{"\n"}
          determinism    : {ex.determinism_mode || "—"}
        </div>
      </div>

      {v.validity && Object.keys(v.validity).length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Validity</div>
          <div className={styles.pre}>{JSON.stringify(v.validity, null, 2)}</div>
        </div>
      )}

      {proof && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Evidence bundle</div>
          <details>
            <summary className={styles.mono} style={{ cursor: "pointer", color: "#77776e" }}>
              {v.proof?.uri || "view"}
            </summary>
            <div className={styles.pre} style={{ marginTop: 8 }}>{JSON.stringify(proof, null, 2)}</div>
          </details>
        </div>
      )}
    </div>
  );
}
