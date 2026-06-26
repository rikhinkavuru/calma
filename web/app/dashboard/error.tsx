"use client";

import { useEffect } from "react";
import styles from "./dashboard.module.css";

/* Error boundary for the dashboard segment. A failed Calma API call (unreachable
   or cold) now renders a graceful, retryable view instead of a hard 500 / blank
   page. `reset()` re-renders the segment, which re-runs the server fetch. */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[dashboard] segment error:", error);
  }, [error]);

  return (
    <div className={styles.main}>
      <h1 className={styles.h1}>Couldn’t load the console</h1>
      <p className={styles.sub}>
        This view didn’t load. It’s usually the verifications API being unreachable or waking from
        cold — retrying often fixes it.
      </p>
      <div className={`${styles.notice} ${styles.noticeErr}`}>
        <span className={styles.mono}>{error.message || "Unknown error"}</span>
      </div>
      <button onClick={reset} className={styles.btn} style={{ marginTop: 4 }}>
        Try again
      </button>
    </div>
  );
}
