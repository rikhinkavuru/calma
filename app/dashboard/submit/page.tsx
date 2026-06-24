import Link from "next/link";
import styles from "../dashboard.module.css";
import { SubmitForm } from "./SubmitForm";

export const dynamic = "force-dynamic";

export default function SubmitPage() {
  return (
    <div className={styles.main}>
      <Link href="/dashboard" className={styles.back}>← Verifications</Link>
      <h1 className={styles.h1} style={{ marginTop: 14 }}>New verification</h1>
      <p className={styles.sub}>
        Upload a bundle and Calma re-runs it offline, recomputes the headline number from the raw outputs,
        and proves or breaks the claim.
      </p>
      <div className={styles.card} style={{ padding: 26 }}>
        <SubmitForm />
      </div>
    </div>
  );
}
