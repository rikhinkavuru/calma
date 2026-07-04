import type { ValidityCard as Card } from "@/lib/verify";
import styles from "./ValidityCard.module.css";

// The no-reproduction validity report card (spike/validity_scan.py): leakage / trivial-baseline / misreport,
// graded, without running the repo. Rendered on shallow (deep=false) scans — the "check my repo" front door.

const GRADE_META: Record<string, { cls: string; icon: string; blurb: string }> = {
  PASS: { cls: styles.pass, icon: "✓", blurb: "no leakage, trivial baseline, or misreport found" },
  FAIL: { cls: styles.fail, icon: "✗", blurb: "a validity problem was found — see below" },
  INCOMPLETE: { cls: styles.incomplete, icon: "–", blurb: "nothing committed to check statically — connect data or run a deep verify" },
};

const CHECK_LABEL: Record<string, string> = {
  leakage: "Data leakage",
  "trivial-baseline": "Trivial baseline",
  misreport: "Misreport",
};

const STATUS_ICON: Record<string, string> = { pass: "✓", fail: "✗", "not-applicable": "–" };

export default function ValidityCard({ card }: { card: Card }) {
  const g = GRADE_META[card.grade] ?? GRADE_META.INCOMPLETE;
  return (
    <section className={styles.card} aria-label="Validity report card">
      <header className={styles.head}>
        <span className={`${styles.grade} ${g.cls}`}>
          <span className={styles.gradeIcon} aria-hidden>{g.icon}</span>
          {card.grade}
        </span>
        <div className={styles.headText}>
          <div className={styles.title}>Validity check</div>
          <div className={styles.blurb}>{g.blurb}</div>
        </div>
      </header>
      <ul className={styles.checks}>
        {card.checks.map((c) => (
          <li key={c.name} className={`${styles.check} ${styles[`s_${c.status.replace("-", "_")}`] ?? ""}`}>
            <span className={styles.checkIcon} aria-hidden>{STATUS_ICON[c.status] ?? "?"}</span>
            <div className={styles.checkBody}>
              <div className={styles.checkName}>
                {CHECK_LABEL[c.name] ?? c.name}
                <span className={styles.checkStatus}>{c.status}</span>
              </div>
              {c.findings.length > 0 && (
                <ul className={styles.findings}>
                  {c.findings.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
