"use client";

// Past scans. The backend job list (/api/jobs) is the source of truth for live status + verdicts; the local
// history index (lib/scan-history) backfills scans the backend has since forgotten (its job store is in-memory
// and wiped on redeploy) — those render as "expired" with just the repo + time. Merged, newest-first,
// searchable. Each row links to the full scan detail.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { FiPlus, FiSearch } from "react-icons/fi";
import type { JobSummary } from "@/lib/verify";
import { readScans } from "@/lib/scan-history";
import { StatusPill, VerdictSummary, repoLabel, timeAgo } from "./scan-ui";
import dash from "./dashboard.module.css";

type Row = JobSummary & { expired?: boolean };

export function ScansClient() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [local, setLocal] = useState<{ id: string; repo: string; ts: number }[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    setLocal(readScans());
    let alive = true;
    fetch("/api/jobs", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || `status ${r.status}`);
        return r.json();
      })
      .then((d) => { if (alive) setJobs(Array.isArray(d) ? d : []); })
      .catch((e) => { if (alive) { setErr(e instanceof Error ? e.message : String(e)); setJobs([]); } });
    return () => { alive = false; };
  }, []);

  const rows: Row[] = useMemo(() => {
    const backend = jobs || [];
    const seen = new Set(backend.map((j) => j.id));
    const expired: Row[] = local
      .filter((l) => !seen.has(l.id))
      .map((l) => ({ id: l.id, repo: l.repo, status: "expired", stage: "", counts: {}, n_claims: 0, created: l.ts, expired: true }));
    const all = [...backend, ...expired].sort((a, b) => (b.created || 0) - (a.created || 0));
    const needle = q.trim().toLowerCase();
    return needle ? all.filter((r) => repoLabel(r.repo).toLowerCase().includes(needle)) : all;
  }, [jobs, local, q]);

  const loading = jobs === null;

  return (
    <div className={dash.main}>
      <div className={dash.row}>
        <div>
          <h1 className={dash.h1}>Scans</h1>
          <p className={dash.sub}>Every repository you&apos;ve verified. Open one to see the three-way verdict on
            each number, the data-leakage check, and the full run log.</p>
        </div>
        <Link href="/dashboard/verify" className={`${dash.btn} ${dash.btnAmber}`}><FiPlus /> New scan</Link>
      </div>

      <div className={dash.card}>
        <div className={dash.cardHead}>
          <span className={dash.cardHeadTitle}>All scans{!loading && ` (${rows.length})`}</span>
          <label className={dash.searchInline}>
            <FiSearch />
            <input
              placeholder="Search repositories…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              spellCheck={false}
              autoCapitalize="off"
            />
          </label>
        </div>

        {loading ? (
          <TableSkeleton />
        ) : rows.length === 0 ? (
          <div className={dash.empty}>
            <h3>{q ? "No matching scans" : "No scans yet"}</h3>
            <p>{q ? "Try a different repository name." : "Verify your first repository to see it here."}</p>
            {!q && (
              <div style={{ marginTop: 18 }}>
                <Link href="/dashboard/verify" className={`${dash.btn} ${dash.btnAmber}`}><FiPlus /> Verify a repo</Link>
              </div>
            )}
            {err && <p className={dash.muted} style={{ marginTop: 14, fontSize: 12 }}>({err})</p>}
          </div>
        ) : (
          <table className={dash.table}>
            <thead>
              <tr><th>Repository</th><th>Verdicts</th><th>Status</th><th>When</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.expired ? (
                      <b>{repoLabel(r.repo)}</b>
                    ) : (
                      <Link href={`/dashboard/scans/${r.id}`} className={dash.rowlink}><b>{repoLabel(r.repo)}</b></Link>
                    )}
                  </td>
                  <td>{r.expired ? <span className={dash.muted}>expired</span> : <VerdictSummary counts={r.counts} nClaims={r.n_claims} />}</td>
                  <td><StatusPill status={r.status} /></td>
                  <td className={dash.muted}>{timeAgo(r.created)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div>
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className={dash.skelRow}>
          <div className={`${dash.skel} ${dash.skelCell}`} />
          <div className={`${dash.skel} ${dash.skelPill}`} />
          <div className={`${dash.skel} ${dash.skelCellSm}`} />
        </div>
      ))}
    </div>
  );
}
