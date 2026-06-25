import Link from "next/link";
import { calma, type Verification } from "@/lib/calma";
import { getSession } from "@/lib/session";
import { StatusBadge, VerdictBadge } from "./Badge";
import styles from "./dashboard.module.css";

export const dynamic = "force-dynamic";

export default async function DashboardHome() {
  const session = await getSession();
  if (!session) return null; // unauthenticated: the layout renders the sign-in gate
  let items: Verification[] = [];
  let error: string | null = null;
  try {
    items = (await calma.listVerifications(session.tenantId)).data;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className={styles.main}>
      <div className={styles.row}>
        <div>
          <h1 className={styles.h1}>Verifications</h1>
          <p className={styles.sub}>Re-executed results, recomputed to ground truth.</p>
        </div>
        <Link href="/dashboard/submit" className={styles.btn}>+ New verification</Link>
      </div>

      {error ? (
        <div className={`${styles.notice} ${styles.noticeErr}`}>
          Could not reach the verifications API. Is it running ({process.env.CALMA_API_URL || "http://localhost:8000"})?<br />
          <span className={styles.mono}>{error}</span>
        </div>
      ) : items.length === 0 ? (
        <div className={styles.card}>
          <div className={styles.empty}>
            <h3>No verifications yet</h3>
            <p>Submit a result and Calma re-runs it, recomputes the number, and proves or breaks the claim.</p>
            <p style={{ marginTop: 14 }}>
              <Link href="/dashboard/submit" className={styles.btn}>Run your first verification →</Link>
            </p>
            <p className={styles.muted} style={{ marginTop: 10, fontSize: 13 }}>
              No bundle yet? The next page has a one-click demo on a sample backtest — no setup.
            </p>
          </div>
        </div>
      ) : (
        <div className={styles.card}>
          <table className={styles.table}>
            <thead>
              <tr><th>Verdict</th><th>Recipe</th><th>Recomputed</th><th>Status</th><th>Created</th><th>ID</th></tr>
            </thead>
            <tbody>
              {items.map((v) => (
                <tr key={v.verification_id}>
                  <td><Link href={`/dashboard/v/${v.verification_id}`} className={styles.rowlink}><VerdictBadge verdict={v.verdict} /></Link></td>
                  <td><Link href={`/dashboard/v/${v.verification_id}`} className={styles.rowlink}>{v.recipe.id}<span className={styles.muted}> @{v.recipe.version}</span></Link></td>
                  <td className={styles.mono}>{v.recomputed?.value ?? "—"}</td>
                  <td><StatusBadge status={v.status} /></td>
                  <td className={styles.muted}>{new Date(v.created_at).toLocaleString()}</td>
                  <td className={styles.mono}>{v.verification_id.slice(0, 8)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
