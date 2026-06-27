import Link from "next/link";
import { FiBox, FiExternalLink, FiArrowLeft } from "react-icons/fi";
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
        <Link href="/install" className={styles.toplink}>
          Docs <FiExternalLink />
        </Link>
        <Link href="/" className={styles.toplink}>
          <FiArrowLeft /> Back to site
        </Link>
      </div>
    </header>
  );
}
