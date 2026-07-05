"use client";

// Small shared display helpers for the scan surfaces (Overview, Scans list, Scan detail): a compact verdict
// summary, a run-status pill, and a relative timestamp. Kept in one place so the three views read identically.
import { tierCounts } from "@/lib/verdict";
import dash from "./dashboard.module.css";

export function timeAgo(tsSeconds: number | undefined): string {
  if (!tsSeconds) return "—";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - tsSeconds));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(tsSeconds * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const STATUS: Record<string, { label: string; cls: string }> = {
  done: { label: "Done", cls: dash.stDone },
  running: { label: "Running", cls: dash.stRunning },
  queued: { label: "Queued", cls: dash.stRunning },
  error: { label: "Failed", cls: dash.stError },
  expired: { label: "Expired", cls: dash.stIdle },
};

export function StatusPill({ status }: { status: string }) {
  const m = STATUS[status] || { label: status || "—", cls: dash.stIdle };
  return (
    <span className={`${dash.statusPill} ${m.cls}`}>
      <span className={dash.statusDot} />
      {m.label}
    </span>
  );
}

// The live sub-stage of an in-flight run ("run 1/2 · 15m elapsed"), shown beside the Running pill so a long
// deep verify visibly moves instead of reading as hung. Nothing for a finished/idle job.
export function RunProgress({ status, progress, stage }: { status: string; progress?: string; stage?: string }) {
  if (status !== "running" && status !== "queued") return null;
  const text = (progress && progress.trim()) || (stage && stage !== "running" && stage !== "queued" ? stage : "");
  if (!text) return null;
  return <span className={dash.muted} style={{ fontSize: 12, marginLeft: 8, whiteSpace: "nowrap" }}>{text}</span>;
}

// A compact one-cell verdict summary: catches first (the actionable ones), then confirmed, then a muted tail
// for the honest-uncertainty + not-yet-checked rows. Empty → an em dash.
export function VerdictSummary({ counts, nClaims }: { counts?: Record<string, number>; nClaims?: number }) {
  const t = tierCounts(counts || {});
  const issues = t.bad + t.inv + t.neu;
  const rest = t.warn + t.idle;
  const total = issues + t.ok + rest;
  if (!total) return <span className={dash.muted}>{nClaims ? `${nClaims} found` : "—"}</span>;
  return (
    <span className={dash.vsum}>
      {issues > 0 && <span className={`${dash.badge} ${dash.badgeBad}`}><span className={dash.dot} />{issues} to review</span>}
      {t.ok > 0 && <span className={`${dash.badge} ${dash.badgeOk}`}><span className={dash.dot} />{t.ok} confirmed</span>}
      {issues === 0 && t.ok === 0 && rest > 0 && (
        <span className={`${dash.badge} ${dash.badgeIdle}`}><span className={dash.dot} />{rest} unverified</span>
      )}
      {(issues > 0 || t.ok > 0) && rest > 0 && <span className={dash.muted}>+{rest}</span>}
    </span>
  );
}

// Short repo label — strip a github URL down to owner/name, keep a bare owner/name as-is.
export function repoLabel(repo: string): string {
  if (!repo) return "—";
  return repo
    .replace(/^https?:\/\/github\.com\//i, "")
    .replace(/\.git$/i, "")
    .replace(/\/$/, "");
}
