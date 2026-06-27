import Link from "next/link";
import { RECIPE_CATALOG } from "./recipeCatalog";
import styles from "../dashboard.module.css";
import { DemoButton } from "./DemoButton";
import { SubmitForm } from "./SubmitForm";

export const dynamic = "force-dynamic";

export default function SubmitPage() {
  return (
    <div className={styles.main}>
      <Link href="/dashboard" className={styles.back}>← Overview</Link>
      <h1 className={styles.h1} style={{ marginTop: 14 }}>New verification</h1>
      <p className={styles.sub}>
        Upload a bundle and Calma re-runs it offline, recomputes the headline number from the raw outputs,
        and proves or breaks the claim.
      </p>

      <div className={`${styles.notice} ${styles.noticeOk}`} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <span>
          <strong>First time?</strong> Run a real verification on a sample backtest — no bundle to build, no
          verify.yaml to write. You&apos;ll see the whole loop end-to-end in a few seconds.
        </span>
        <DemoButton />
      </div>

      <div className={styles.card} style={{ padding: 26 }}>
        <SubmitForm recipeGroups={RECIPE_CATALOG} />
      </div>
    </div>
  );
}
