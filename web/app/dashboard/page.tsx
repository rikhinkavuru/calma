import { Suspense } from "react";
import { calma, type Verification } from "@/lib/calma";
import { getSession } from "@/lib/session";
import { Onboarding } from "./Onboarding";
import { Overview } from "./Overview";
import { OverviewSkeleton } from "./Skeletons";
import styles from "./dashboard.module.css";

export const dynamic = "force-dynamic";

// The page suspends behind its own boundary so the shell (sidebar + topbar)
// paints instantly while the (potentially slow, cold) Calma API call streams in
// under the overview skeleton.
export default function DashboardHome() {
  return (
    <Suspense fallback={<OverviewSkeleton />}>
      <OverviewData />
    </Suspense>
  );
}

async function OverviewData() {
  const session = await getSession();
  if (!session) return null; // unauthenticated: the layout renders the sign-in gate
  let items: Verification[] = [];
  let error: string | null = null;
  try {
    items = (await calma.listVerifications(session.tenantId)).data;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <div className={styles.main}>
        <h1 className={styles.h1}>Overview</h1>
        <div className={`${styles.notice} ${styles.noticeErr}`} style={{ marginTop: 16 }}>
          Could not reach the verifications API. Is it running ({process.env.CALMA_API_URL || "http://localhost:8000"})?<br />
          <span className={styles.mono}>{error}</span>
        </div>
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className={styles.main}>
        <h1 className={styles.h1}>Overview</h1>
        <p className={styles.sub} style={{ marginBottom: 24 }}>Re-executed results, recomputed to ground truth.</p>
        <Onboarding />
      </div>
    );
  }
  return <Overview items={items} />;
}
