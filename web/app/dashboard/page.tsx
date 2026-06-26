import { Suspense } from "react";
import Link from "next/link";
import { calma, type Verification } from "@/lib/calma";
import { getSession } from "@/lib/session";
import { Onboarding } from "./Onboarding";
import { VerificationRows } from "./VerificationRows";
import { TableSkeleton } from "./Skeletons";
import styles from "./dashboard.module.css";

export const dynamic = "force-dynamic";

// The page shell renders instantly; only the data table suspends behind its own
// boundary, so the header + "New verification" button paint immediately while the
// (potentially slow, cold) Calma API call streams in under the table skeleton.
export default function DashboardHome() {
  return (
    <div className={styles.main}>
      <div className={styles.row}>
        <div>
          <h1 className={styles.h1}>Verifications</h1>
          <p className={styles.sub}>Re-executed results, recomputed to ground truth.</p>
        </div>
        <Link href="/dashboard/submit" className={styles.btn}>+ New verification</Link>
      </div>

      <Suspense fallback={<TableSkeleton />}>
        <VerificationsTable />
      </Suspense>
    </div>
  );
}

async function VerificationsTable() {
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
    <>
      {error ? (
        <div className={`${styles.notice} ${styles.noticeErr}`}>
          Could not reach the verifications API. Is it running ({process.env.CALMA_API_URL || "http://localhost:8000"})?<br />
          <span className={styles.mono}>{error}</span>
        </div>
      ) : items.length === 0 ? (
        <Onboarding />
      ) : (
        <VerificationRows items={items} />
      )}
    </>
  );
}
