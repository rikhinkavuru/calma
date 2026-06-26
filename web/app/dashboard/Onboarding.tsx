"use client";

// WS7 — the empty state IS the onboarding (Vercel/Linear/Stripe: "empty states are the activation").
// A no-data user can: copy the one-line hook install, and "Load a sample verification" to SEE a
// Confirmed and a broken Caught — with the expandable diff — before they have any data of their own.
// Plus a dismissible, non-blocking progress checklist. No API calls: the sample data is baked in.
import { useEffect, useState } from "react";
import Link from "next/link";
import { CopyBlock, DiffCell } from "./diff";
import styles from "./dashboard.module.css";

const HOOK_INSTALL =
  "/plugin marketplace add rikhinkavuru/calma   # then: /plugin install calma";

type Sample = {
  metric: string;
  claimed: number | null;
  recomputed: number;
  outcome: "Confirmed" | "Caught";
  why: string;
  keyid: string;
};

const SAMPLES: Sample[] = [
  {
    metric: "accuracy",
    claimed: 0.91,
    recomputed: 0.91,
    outcome: "Confirmed",
    why: "reproduces and recomputes to the claim within the calibrated tolerance",
    keyid: "3d48e4df88f77082",
  },
  {
    metric: "sharpe",
    claimed: 2.6,
    recomputed: 1.42,
    outcome: "Caught",
    why: "the headline annualizes weekly returns with a 252-day factor (use 52)",
    keyid: "3d48e4df88f77082",
  },
];

const CHECKLIST = [
  { key: "hook", label: "Install the zero-touch Stop-hook" },
  { key: "first", label: "Receive your first verification" },
  { key: "proof", label: "Open a proof" },
  { key: "badge", label: "Embed a “Verified by Calma” badge" },
];

export function Onboarding() {
  const [showSample, setShowSample] = useState(false);
  const [dismissed, setDismissed] = useState(true); // default hidden until we read localStorage

  useEffect(() => {
    try {
      setDismissed(localStorage.getItem("calma.onboarding.dismissed") === "1");
    } catch {
      setDismissed(false);
    }
  }, []);

  function dismiss() {
    setDismissed(true);
    try {
      localStorage.setItem("calma.onboarding.dismissed", "1");
    } catch {
      /* ignore */
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.empty}>
        <h3>Catch your first wrong number</h3>
        <p>
          Calma re-executes a result in a sandbox, recomputes the headline number from the raw
          outputs, and proves or breaks the claim. Wire the guardrail, then submit a result:
        </p>

        <CopyBlock text={HOOK_INSTALL} label="install the Stop-hook (Claude Code)" />

        <p style={{ marginTop: 18, display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Link href="/dashboard/submit" className={styles.btn}>
            Run your first verification →
          </Link>
          <button
            type="button"
            className={styles.btnGhost}
            onClick={() => setShowSample((s) => !s)}
          >
            {showSample ? "Hide sample" : "Load a sample verification"}
          </button>
        </p>

        {showSample && (
          <div style={{ marginTop: 20, display: "grid", gap: 14 }}>
            <p className={styles.muted} style={{ fontSize: 13, margin: 0 }}>
              A real-shaped example — one clean pass, one catch. Click a card to expand the diff.
            </p>
            {SAMPLES.map((s) => (
              <SampleDiff key={s.metric} s={s} />
            ))}
          </div>
        )}

        {!dismissed && (
          <div style={{ marginTop: 26, borderTop: "1px solid rgba(0,0,0,0.08)", paddingTop: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong style={{ fontSize: 13 }}>Getting started</strong>
              <button
                type="button"
                className={styles.btnGhost}
                style={{ fontSize: 12, padding: "2px 8px" }}
                onClick={dismiss}
              >
                Dismiss
              </button>
            </div>
            <ul style={{ listStyle: "none", padding: 0, margin: "10px 0 0" }}>
              {CHECKLIST.map((c, i) => (
                <li
                  key={c.key}
                  className={styles.muted}
                  style={{ fontSize: 13, padding: "4px 0", display: "flex", gap: 8 }}
                >
                  <span aria-hidden>{i === 0 ? "▸" : "○"}</span>
                  {c.label}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

// the expandable visual diff — the product's "aha". Reused for the sample cards here; the same shape
// drives the real verification rows.
function SampleDiff({ s }: { s: Sample }) {
  const [open, setOpen] = useState(true);
  const match = s.claimed !== null && Math.abs(s.recomputed - s.claimed) < 1e-9;
  const badgeClass = s.outcome === "Confirmed" ? styles.bConfirmed : styles.bRefuted;
  const glyph = s.outcome === "Confirmed" ? "✓" : "✗";
  const delta = s.claimed === null ? null : s.recomputed - s.claimed;

  return (
    <div className={styles.card} style={{ margin: 0, cursor: "pointer" }} onClick={() => setOpen((o) => !o)}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span className={`${styles.badge} ${badgeClass}`}>
          {glyph} {s.outcome}
        </span>
        <span style={{ fontWeight: 600 }}>{s.metric}</span>
        <span className={styles.mono} style={{ marginLeft: "auto" }}>
          {s.claimed === null ? `recomputed ${s.recomputed}` : `${s.claimed} → ${s.recomputed}`}
        </span>
      </div>

      {open && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <DiffCell label="claimed" value={s.claimed === null ? "—" : String(s.claimed)} ok={match} />
            <DiffCell label="recomputed" value={String(s.recomputed)} ok={match} highlight />
          </div>
          {delta !== null && (
            <p className={styles.mono} style={{ fontSize: 13, margin: "10px 0 0" }}>
              Δ {delta > 0 ? "+" : ""}
              {Number(delta.toFixed(6))}
            </p>
          )}
          <p className={styles.muted} style={{ fontSize: 13, margin: "8px 0 0", lineHeight: 1.5 }}>
            {s.why}
          </p>
          <p className={styles.muted} style={{ fontSize: 12, margin: "10px 0 0" }}>
            Ceiling: proves the recompute, <em>not</em> input-data authenticity or semantic
            correctness. Signed by <span className={styles.mono}>{s.keyid}</span>.
          </p>
          <div style={{ marginTop: 10 }}>
            <CopyBlock text={`calma proof verify proof.json`} label="re-verify offline" small />
          </div>
        </div>
      )}
    </div>
  );
}

