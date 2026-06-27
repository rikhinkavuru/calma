"use client";

// WS7 — the verification row is not a dead cell: click it and it expands into the visual DIFF (the
// product's "aha"). Claimed vs recomputed side-by-side, matched/mismatched highlighted, the verdict
// rolled up to the 3 outcomes, the data-authenticity ceiling, a "Re-verify offline" line, and a
// "Copy badge" snippet that deep-links to the public proof page.
import { useState } from "react";
import Link from "next/link";
import type { Verification } from "@/lib/calma";
import { StatusBadge } from "./Badge";
import { CopyButton, DiffCell } from "./diff";
import { outcome, type Outcome } from "./outcome";
import styles from "./dashboard.module.css";

export function VerificationRows({ items }: { items: Verification[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className={styles.card}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Verdict</th>
            <th>Recipe</th>
            <th>Recomputed</th>
            <th>Status</th>
            <th>Created</th>
            <th>ID</th>
          </tr>
        </thead>
        <tbody>
          {items.map((v) => {
            const oc = outcome(v.verdict || v.repo_verdict);
            const isOpen = open === v.verification_id;
            return (
              <RowGroup
                key={v.verification_id}
                v={v}
                oc={oc}
                isOpen={isOpen}
                onToggle={() => setOpen(isOpen ? null : v.verification_id)}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RowGroup({
  v,
  oc,
  isOpen,
  onToggle,
}: {
  v: Verification;
  oc: Outcome;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const claimed = v.claim?.value;
  const recomputed = v.recomputed?.value;
  const match = v.recomputed?.within_tolerance === true;
  const delta =
    claimed !== undefined && recomputed !== undefined ? recomputed - claimed : undefined;
  const metric = v.claim?.metric || v.recipe?.id || "";
  const label = `${metric}${recomputed !== undefined ? ` ${recomputed}` : ""}`.trim() || oc.name;
  const badgeUrl = `/badge?outcome=${encodeURIComponent(oc.name)}&label=${encodeURIComponent(label)}`;
  const proofUrl =
    `/proof?outcome=${encodeURIComponent(oc.name)}&metric=${encodeURIComponent(metric)}` +
    (claimed !== undefined ? `&claimed=${claimed}` : "") +
    (recomputed !== undefined ? `&recomputed=${recomputed}` : "");

  return (
    <>
      <tr onClick={onToggle} style={{ cursor: "pointer" }}>
        <td>
          <span className={styles.verdict}>
            <i className={`${styles.vdot} ${oc.key === "ok" ? styles.vdotOk : oc.key === "bad" ? styles.vdotBad : styles.vdotIdle}`} />
            {oc.name}
          </span>
        </td>
        <td>
          {v.recipe.id}
          <span className={styles.muted}> @{v.recipe.version}</span>
        </td>
        <td className={styles.mono}>{recomputed ?? "—"}</td>
        <td>
          <StatusBadge status={v.status} />
        </td>
        <td className={styles.muted}>{new Date(v.created_at).toLocaleString()}</td>
        <td className={styles.mono}>
          <span aria-hidden className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ""}`}>›</span>{" "}
          {v.verification_id.slice(0, 8)}
        </td>
      </tr>
      {isOpen && (
        <tr>
          <td colSpan={6} style={{ background: "var(--surface-2)" }}>
            <div style={{ padding: "6px 4px 14px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, maxWidth: 520 }}>
                <DiffCell label="claimed" value={claimed === undefined ? "— (reproduction)" : String(claimed)} ok={match} />
                <DiffCell label="recomputed" value={recomputed === undefined ? "—" : String(recomputed)} ok={match} highlight />
              </div>
              {delta !== undefined && (
                <p className={styles.mono} style={{ fontSize: 13, margin: "10px 0 0" }}>
                  Δ {delta > 0 ? "+" : ""}
                  {Number(delta.toFixed(6))}
                  {v.recomputed?.abs_diff !== undefined ? `  ·  |diff| ${v.recomputed.abs_diff}` : ""}
                </p>
              )}
              {v.reason && (
                <p className={styles.muted} style={{ fontSize: 13, margin: "8px 0 0", lineHeight: 1.5 }}>
                  {v.reason}
                </p>
              )}
              {v.execution && (
                <p className={styles.muted} style={{ fontSize: 12, margin: "8px 0 0" }}>
                  isolation: {v.execution.isolation_tier || "?"} · determinism:{" "}
                  {v.execution.determinism_mode || "?"}
                </p>
              )}
              <p className={styles.muted} style={{ fontSize: 12, margin: "10px 0 0" }}>
                Ceiling: proves the recompute, <em>not</em> input-data authenticity or semantic
                correctness.
              </p>
              <div style={{ display: "flex", gap: 14, marginTop: 12, flexWrap: "wrap", fontSize: 13 }}>
                <Link href={`/dashboard/v/${v.verification_id}`} className={styles.rowlink}>
                  Open full proof →
                </Link>
                <Link href={proofUrl} className={styles.rowlink}>
                  Public permalink →
                </Link>
                <CopyButton
                  text={`![verified by calma](https://trycalma.ai${badgeUrl})`}
                  idle="Copy badge"
                  done="Badge copied ✓"
                  className={styles.rowlink}
                />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

