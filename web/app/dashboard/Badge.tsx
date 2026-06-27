import styles from "./dashboard.module.css";

// Subtle dot colour by status — kept restrained (one accent at a time) so the
// console reads mostly monochrome. Unknown statuses fall back to neutral.
const STATUS_DOT: Record<string, string> = {
  COMPLETED: "#3a9c57",
  FAILED: "#cf5424",
  REFUSED: "#cf5424",
  TIMED_OUT: "#b3aa9b",
  DEDUPED: "#b3aa9b",
  QUEUED: "#c79049",
  STAGING: "#c79049",
  RUNNING: "#c79049",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={styles.statusCell}>
      <i className={styles.vdot} style={{ backgroundColor: STATUS_DOT[status] || "#b3aa9b" }} />
      {status.toLowerCase()}
    </span>
  );
}
