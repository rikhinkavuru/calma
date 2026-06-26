import styles from "./dashboard.module.css";
import { HeaderSkeleton, TableSkeleton } from "./Skeletons";

/* Instant skeleton shown while a dashboard segment renders on the server. The
   pages are `force-dynamic` and fetch the Calma API with `no-store`, which can
   be slow on a cold serverless instance. Without a loading boundary the App
   Router freezes on the previous page until that fetch resolves — the "slow and
   laggy when switching pages" feel. This Suspense fallback paints immediately
   (and is prefetchable), so navigation feels instant and the data streams in. */
export default function DashboardLoading() {
  return (
    <div className={styles.main} aria-busy="true" aria-label="Loading">
      <HeaderSkeleton />
      <TableSkeleton />
    </div>
  );
}
