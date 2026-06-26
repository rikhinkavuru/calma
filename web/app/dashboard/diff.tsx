"use client";

// Shared diff primitives for the verification visual diff (used by both the sample cards in the
// empty-state onboarding and the expandable real rows). The verdict-only colour signals match/mismatch.
import { useState } from "react";
import styles from "./dashboard.module.css";

export function DiffCell({
  label,
  value,
  ok,
  highlight,
}: {
  label: string;
  value: string;
  ok: boolean;
  highlight?: boolean;
}) {
  const border = ok ? "rgba(26,127,55,0.35)" : "rgba(196,50,10,0.35)";
  return (
    <div
      style={{
        border: `1px solid ${highlight ? border : "rgba(0,0,0,0.10)"}`,
        background: highlight ? (ok ? "rgba(231,246,236,0.5)" : "rgba(253,236,235,0.5)") : "transparent",
        borderRadius: 8,
        padding: "10px 12px",
      }}
    >
      <div className={styles.muted} style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 1 }}>
        {label}
      </div>
      <div className={styles.mono} style={{ fontSize: 20, marginTop: 4 }}>
        {value}
      </div>
    </div>
  );
}

export function CopyButton({
  text,
  idle = "Copy",
  done = "Copied",
  className,
}: {
  text: string;
  idle?: string;
  done?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={className ?? styles.btnGhost}
      style={{ fontSize: 12 }}
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(text).then(
          () => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1400);
          },
          () => {},
        );
      }}
    >
      {copied ? done : idle}
    </button>
  );
}

export function CopyBlock({ text, label, small }: { text: string; label?: string; small?: boolean }) {
  return (
    <div style={{ marginTop: small ? 0 : 12 }}>
      {label && (
        <div
          className={styles.muted}
          style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}
        >
          {label}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}>
        <code className={styles.pre} style={{ flex: 1, fontSize: small ? 12 : 13, margin: 0 }}>
          {text}
        </code>
        <CopyButton text={text} />
      </div>
    </div>
  );
}
