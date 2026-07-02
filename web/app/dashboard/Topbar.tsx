import Link from "next/link";
import { FiBox, FiExternalLink, FiArrowLeft, FiPlus } from "react-icons/fi";
import { GITHUB_URL } from "../../components/contact";
import styles from "./dashboard.module.css";

export function Topbar({ user }: { user: { name: string; email: string; mode: "workos" | "dev" } }) {
  return (
    <header className={styles.topbar}>
      <div className={styles.workspace}>
        <FiBox />
        {user.mode === "dev" ? "Dev workspace" : user.name}
        {user.mode === "dev" && <span className={styles.devpill}>DEV</span>}
      </div>
      <div className={styles.topright}>
        <Link href="/" className={styles.toplink}>
          <FiArrowLeft /> Back to site
        </Link>
        <Link href={GITHUB_URL} className={styles.toplink}>
          Docs <FiExternalLink />
        </Link>
        <Link href="/dashboard/verify" className={`${styles.btn} ${styles.btnAmber} ${styles.topcta}`}>
          <FiPlus /> New scan
        </Link>
      </div>
    </header>
  );
}
