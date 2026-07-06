import Link from "next/link";
import { FiBox, FiArrowLeft, FiPlus } from "react-icons/fi";
import styles from "./dashboard.module.css";

export function Topbar({ user, tier }: {
  user: { name: string; email: string; mode: "workos" | "dev" }; tier?: string;
}) {
  return (
    <header className={styles.topbar}>
      <div className={styles.workspace}>
        <FiBox />
        {user.mode === "dev" ? "Dev workspace" : user.name}
        {user.mode === "dev" && <span className={styles.devpill}>DEV</span>}
        {tier && <span className={styles.tierPill} title={`You're on the ${tier} tier`}>{tier}</span>}
      </div>
      <div className={styles.topright}>
        <Link href="/" className={styles.toplink}>
          <FiArrowLeft /> Back to site
        </Link>
        <Link href="/docs" className={styles.toplink}>
          Docs
        </Link>
        <Link href="/dashboard/verify" className={`${styles.btn} ${styles.btnAmber} ${styles.topcta}`}>
          <FiPlus /> New scan
        </Link>
      </div>
    </header>
  );
}
