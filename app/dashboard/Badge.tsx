import styles from "./dashboard.module.css";

const VERDICT: Record<string, string> = {
  "CONFIRMED": styles.bConfirmed,
  "CONFIRMED-WITH-CAVEATS": styles.bConfirmed,
  "REFUTED": styles.bRefuted,
  "MIXED": styles.bRefuted,
  "INVALIDATED": styles.bInvalid,
  "FLAG_FOR_DECLARATION": styles.bFlag,
  "INCONCLUSIVE": styles.bInconcl,
  "CAN'T-CONFIRM": styles.bInconcl,
};

const STATUS: Record<string, string> = {
  COMPLETED: styles.bConfirmed,
  QUEUED: styles.bNeutral,
  STAGING: styles.bNeutral,
  RUNNING: styles.bNeutral,
  REFUSED: styles.bInvalid,
  FAILED: styles.bRefuted,
  TIMED_OUT: styles.bInconcl,
  DEDUPED: styles.bInconcl,
};

export function VerdictBadge({ verdict }: { verdict?: string }) {
  if (!verdict) {
    return <span className={`${styles.badge} ${styles.bInconcl}`}><span className={styles.dot} />pending</span>;
  }
  return (
    <span className={`${styles.badge} ${VERDICT[verdict] || styles.bInconcl}`}>
      <span className={styles.dot} />{verdict}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`${styles.badge} ${STATUS[status] || styles.bInconcl}`}>
      <span className={styles.dot} />{status}
    </span>
  );
}
