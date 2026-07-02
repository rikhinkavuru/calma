"use client";

// The no-signup demo: ONE button, ONE fixed sample repo (demo-repo/ in this monorepo). Submits to the
// unauthenticated /api/demo/verify proxy, polls the job, and renders the same three-way verdict table as
// the dashboard — so a visitor can watch the real engine catch a real wrong number before creating an
// account. No repo field: the point is "try it", not "configure it".
import { useCallback, useEffect, useRef, useState } from "react";
import type { Claim, Job } from "@/lib/verify";
import s from "../dashboard/verify.module.css";

const ORDER = ["REFUTED", "INVALIDATED", "CONFIRMED", "NON-DETERMINISTIC", "REPRODUCED-ONLY", "INCONCLUSIVE", "DISCOVERED"];
const PROBLEMS = ["REFUTED", "INVALIDATED", "NON-DETERMINISTIC"];

function pillClass(verdict: string): string {
  if (verdict === "CONFIRMED") return s.ok;
  if (PROBLEMS.includes(verdict)) return s.bad;
  return s.idle;
}

function num(x: unknown): string {
  return typeof x === "number" && Number.isFinite(x) ? Number(x).toPrecision(5) : "—";
}

export function DemoClient() {
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/demo/verify/${id}`, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || `status ${res.status}`);
      setJob(data as Job);
      if (data.status === "done" || data.status === "error") {
        setBusy(false);
        return;
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
      return;
    }
    timer.current = setTimeout(() => poll(id), 1200);
  }, []);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  async function run() {
    if (busy) return;
    setErr(null);
    setJob(null);
    setBusy(true);
    try {
      const res = await fetch("/api/demo/verify", { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || `status ${res.status}`);
      poll(data.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const claims: Claim[] = (job?.claims || [])
    .slice()
    .sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict));
  const running = busy && (!job || job.status === "queued" || job.status === "running");

  return (
    <div>
      <button className="btn-primary" onClick={run} disabled={running} type="button">
        {running ? (job?.stage || "starting…") : "Run the demo"}
        {!running && <span className="arrow" aria-hidden="true"> →</span>}
      </button>
      <p className="micro" style={{ marginTop: 10 }}>
        Runs a tiny seeded sklearn classifier (
        <a href="https://github.com/rikhinkavuru/calma/tree/main/demo-repo" target="_blank" rel="noreferrer">
          demo-repo
        </a>
        ) that claims 94.2% accuracy in its README. Watch what Calma actually recomputes.
      </p>

      {err && <div className={`${s.banner} ${s.bannerBad}`}>{err}</div>}

      {job && job.claims?.length > 0 && (
        <table className={s.table} style={{ marginTop: 18 }}>
          <thead>
            <tr>
              <th>Metric</th><th>Claimed</th><th>Recomputed</th><th>Verdict</th><th>Where</th><th>Why</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((c) => {
              const d = c.diff || {};
              const recomp = d.recomputed != null ? num(d.recomputed) : num(d.produced);
              return (
                <tr key={c.id}>
                  <td><b>{c.metric}</b></td>
                  <td className={s.mono}>{c.claimed}</td>
                  <td className={s.mono}>{recomp}</td>
                  <td><span className={`${s.pill} ${pillClass(c.verdict)}`}>{c.verdict}</span></td>
                  <td className={s.where}>{(c.context || c.location || c.source || "").slice(0, 90)}</td>
                  <td className={s.why}>{c.reason}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {job?.status === "done" && (!job.claims || job.claims.length === 0) && (
        <p className="micro" style={{ marginTop: 14 }}>No claims came back — try again in a moment.</p>
      )}
    </div>
  );
}

export default DemoClient;
