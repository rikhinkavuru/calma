// Client-side scan history. The backend's job list (GET /api/jobs) is authoritative for live status +
// verdict counts, but it lives in memory and is wiped on every backend redeploy. So each scan the user
// submits is also recorded here (id + repo + time) — the Scans list merges the two, showing a backend job's
// live verdicts when present and falling back to this record (marked "expired") when the backend has forgotten
// it. Purely a convenience index of the user's OWN submissions; it carries no verdict and gates nothing.
"use client";

export type LocalScan = { id: string; repo: string; ts: number };

const KEY = "calma_scans";
const MAX = 100;

export function readScans(): LocalScan[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr
      .filter((s): s is LocalScan => !!s && typeof s.id === "string" && typeof s.repo === "string")
      .slice(0, MAX);
  } catch {
    return [];
  }
}

export function recordScan(id: string, repo: string): void {
  if (typeof window === "undefined" || !id) return;
  try {
    const now = Math.floor(Date.now() / 1000);
    const existing = readScans().filter((s) => s.id !== id);
    const next = [{ id, repo: repo || "", ts: now }, ...existing].slice(0, MAX);
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* private mode / quota — history is best-effort */
  }
}
