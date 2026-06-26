"use client";

// WS7 — the verification row is not a dead cell: click it and it expands into the visual DIFF (the
// product's "aha"). Claimed vs recomputed side-by-side, matched/mismatched highlighted, the verdict
// rolled up to the 3 outcomes, the data-authenticity ceiling, a "Re-verify offline" line, and a
// "Copy badge" snippet that deep-links to the public proof page.
import { useState } from "react";
import Link from "next/link";
import type { Verification } from "@/lib/calma";
import { StatusBadge } from "./Badge";
import styles from "./dashboard.module.css";

// the deterministic 6 -> 3 roll-up, mirrored from the engine's verdict.outcome() (kept in sync by the
// reference docs). Anything unknown degrades to Can't-tell (fail-closed, never a green pass).
function outcome(verdict?: string): { name: string; glyph: string; cls: string } {
  const v = (verdict || "").toUpperCase();
  if (v === "CONFIRMED" || v === "CONFIRMED-WITH-CAVEATS")
    return { name: "Confirmed", glyph: "✓", cls: styles.bConfirmed };
  if (["REFUTED", "INVALIDATED", "FLAG_FOR_DECLARATION", "MIXED"].includes(v))
    return { name: "Caught", glyph: "✗", cls: styles.bRefuted };
  if (v === "INCONCLUSIVE" || v === "CAN'T-CONFIRM")
    return { name: "Can't tell", glyph: "?", cls: styles.bInconcl };
  return { name: verdict || "pending", glyph: "·", cls: styles.bInconcl };
}

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
  oc: { name: string; glyph: string; cls: string };
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
          <span className={`${styles.badge} ${oc.cls}`}>
            {oc.glyph} {oc.name}
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
          <span aria-hidden>{isOpen ? "▾ " : "▸ "}</span>
          {v.verification_id.slice(0, 8)}
        </td>
      </tr>
      {isOpen && (
        <tr>
          <td colSpan={6} style={{ background: "rgba(0,0,0,0.015)" }}>
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
                <CopyBadge md={`![verified by calma](https://trycalma.ai${badgeUrl})`} />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function DiffCell({ label, value, ok, highlight }: { label: string; value: string; ok: boolean; highlight?: boolean }) {
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

function CopyBadge({ md }: { md: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={styles.rowlink}
      style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: "inherit" }}
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(md).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        });
      }}
    >
      {copied ? "Badge copied ✓" : "Copy badge"}
    </button>
  );
}
