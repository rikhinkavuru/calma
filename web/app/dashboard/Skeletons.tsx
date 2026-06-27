import styles from "./dashboard.module.css";

/* Shared loading skeletons. TableSkeleton is reused by both the route-level
   loading.tsx (full-page transitions) and the inner <Suspense> on the
   verifications page (so the header paints instantly and only the data streams). */

export function HeaderSkeleton() {
  return (
    <div className={styles.row}>
      <div>
        <div className={`${styles.skel} ${styles.skelTitle}`} />
        <div className={`${styles.skel} ${styles.skelSub}`} />
      </div>
      <div className={`${styles.skel} ${styles.skelBtn}`} />
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className={styles.card} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={styles.skelRow}>
          <div className={`${styles.skel} ${styles.skelPill}`} />
          <div className={`${styles.skel} ${styles.skelCell}`} />
          <div className={`${styles.skel} ${styles.skelCellSm}`} />
          <div className={`${styles.skel} ${styles.skelPill}`} />
        </div>
      ))}
    </div>
  );
}

/* Overview home skeleton: header + the 5 stat cards + the recent table. Mirrors
   the real layout so the page doesn't reflow when data streams in. */
export function OverviewSkeleton() {
  return (
    <div className={styles.main} aria-busy="true" aria-label="Loading">
      <HeaderSkeleton />
      <div className={styles.panelGrid} style={{ marginTop: 4 }}>
        <div className={`${styles.skel} ${styles.skelPanel}`} />
        <div className={`${styles.skel} ${styles.skelPanel}`} />
      </div>
      <TableSkeleton />
    </div>
  );
}
