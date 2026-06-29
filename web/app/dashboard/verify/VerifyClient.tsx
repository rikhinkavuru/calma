"use client";

// Connect a repo → verify the numbers, inside the WorkOS-gated dashboard. Submits to the authed proxy
// (/api/verify), polls the job, and renders the three-way verdict per claim + the data-validity layer
// (leakage) — the same loop as the spike SPA, but first-party and behind login.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Claim, Job } from "@/lib/verify";
import dash from "../dashboard.module.css";
import s from "./verify.module.css";

const PROBLEMS = ["REFUTED", "INVALIDATED", "NON-DETERMINISTIC"];
const ORDER = ["REFUTED", "INVALIDATED", "CONFIRMED", "NON-DETERMINISTIC", "REPRODUCED-ONLY", "INCONCLUSIVE", "DISCOVERED"];

function pillClass(verdict: string): string {
  if (verdict === "CONFIRMED") return s.ok;
  if (PROBLEMS.includes(verdict)) return s.bad;
  return s.idle;
}

function num(x: unknown): string {
  return typeof x === "number" && Number.isFinite(x) ? Number(x).toPrecision(5) : "—";
}

export function VerifyClient() {
  const [repo, setRepo] = useState("");
  const [deep, setDeep] = useState(true);
  const [entry, setEntry] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"PROBLEMS" | "ALL">("ALL");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/verify/${id}`, { cache: "no-store" });
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!repo.trim() || busy) return;
    setErr(null);
    setJob(null);
    setBusy(true);
    setFilter("ALL");
    try {
      const res = await fetch("/api/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo: repo.trim(), deep, entry: entry.trim() || null }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || `status ${res.status}`);
      poll(data.id);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
      setBusy(false);
    }
  }

  const counts = job?.counts || {};
  const problems = PROBLEMS.reduce((n, v) => n + (counts[v] || 0), 0);
  const clean = counts.CONFIRMED || 0;
  const leak = job?.leakage || [];

  const claims: Claim[] = (job?.claims || [])
    .filter((c) => (filter === "PROBLEMS" ? PROBLEMS.includes(c.verdict) : true))
    .slice()
    .sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict))
    .slice(0, 300);

  return (
    <div className={dash.main}>
      <h1 className={dash.h1}>Verify a repo</h1>
      <p className={dash.sub}>
        Connect a repo. Calma re-runs it and recomputes every number it reports — from the raw outputs, not
        the claim — then checks the data for leakage. CONFIRMED / REFUTED / INVALIDATED.
      </p>

      <form className={s.form} onSubmit={submit}>
        <input
          className={`${dash.input} ${s.repo}`}
          placeholder="owner/name, a GitHub URL, or a local path"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          spellCheck={false}
          autoCapitalize="off"
        />
        <button className={`${dash.btn} ${dash.btnAmber}`} type="submit" disabled={busy || !repo.trim()}>
          {busy ? "Verifying…" : "Verify"}
        </button>
      </form>
      <div className={s.opts}>
        <label>
          <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} />
          Deep verify (re-run the entrypoint)
        </label>
        {deep && (
          <input
            className={`${dash.input} ${s.entry}`}
            placeholder="entrypoint, e.g. eval.py (optional)"
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            spellCheck={false}
          />
        )}
      </div>

      {err && <div className={`${dash.notice} ${dash.noticeErr}`}>{err}</div>}

      {busy && !job && <p className={dash.muted}>Cloning and preparing the repo…</p>}
      {job && job.status !== "done" && job.status !== "error" && (
        <p className={dash.muted}>
          {job.stage}… <span className={dash.mono}>{job.repo}</span>
        </p>
      )}
      {job?.status === "error" && (
        <div className={`${dash.notice} ${dash.noticeErr}`}>{job.error || "verification failed"}</div>
      )}

      {job?.status === "done" && (
        <>
          {job.run && (
            <div className={`${s.banner} ${job.run.ran ? s.bannerOk : s.bannerWarn}`}>
              {job.run.ran ? (
                <>
                  Re-ran <code>{job.run.entry}</code> · captured {job.run.calls} computation(s) ·{" "}
                  <b>{problems} need attention</b>, {clean} hold up.
                </>
              ) : (
                <>
                  Tried to re-run <code>{job.run.entry}</code> but it didn&apos;t execute
                  {job.run.error ? (
                    <>
                      {" "}— <span className={s.mono}>{job.run.error}</span>
                    </>
                  ) : null}
                  .
                  {job.run.error_full && job.run.error_full !== job.run.error && (
                    <details>
                      <summary className={dash.muted} style={{ cursor: "pointer", fontSize: 12 }}>
                        full error output
                      </summary>
                      <pre className={s.mono}>{job.run.error_full}</pre>
                    </details>
                  )}
                  <br />
                  Showing the {job.n_claims} numbers Calma found — give it a runnable entrypoint (and any
                  data/deps) to deep-verify them.
                </>
              )}
            </div>
          )}

          {leak.length > 0 && (
            <div className={`${s.banner} ${s.bannerBad}`}>
              <b>⚠ Data leakage — {leak.length} dataset(s) contaminated.</b> A leaked train/test split makes
              the held-out numbers invalid, even when they recompute perfectly.
              {leak.map((d) => (
                <div key={d.dataset} style={{ marginTop: 6 }}>
                  <b>{d.dataset}</b>{" "}
                  {d.findings.map((f, i) => (
                    <span key={i} className={`${s.pill} ${s.bad}`} style={{ marginRight: 6 }}>
                      {f.kind} {Math.round(100 * f.magnitude)}%
                    </span>
                  ))}
                </div>
              ))}
            </div>
          )}

          <div className={s.cards}>
            <div className={s.sum}><div className={s.n} style={{ color: "var(--bad-fg)" }}>{problems}</div><div className={s.l}>need attention</div></div>
            <div className={s.sum}><div className={s.n} style={{ color: "var(--ok-fg)" }}>{clean}</div><div className={s.l}>hold up</div></div>
            <div className={s.sum}><div className={s.n}>{counts.DISCOVERED || 0}</div><div className={s.l}>found · not re-run</div></div>
            <div className={s.sum}><div className={s.n}>{job.n_claims}</div><div className={s.l}>claims total</div></div>
          </div>

          {job.n_claims > 0 ? (
            <>
              <div className={s.filters}>
                <button className={`${s.filter} ${filter === "ALL" ? s.filterOn : ""}`} onClick={() => setFilter("ALL")}>
                  All ({job.n_claims})
                </button>
                <button className={`${s.filter} ${filter === "PROBLEMS" ? s.filterOn : ""}`} onClick={() => setFilter("PROBLEMS")}>
                  Problems ({problems})
                </button>
              </div>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>Metric</th><th>Claimed</th><th>Recomputed</th><th>Verdict</th><th>Where</th><th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {claims.map((c) => {
                    const d = c.diff || {};
                    const recomp = d.recomputed != null ? num(d.recomputed) : num(d.produced);
                    const adv = c.validity?.advisory || [];
                    return (
                      <tr key={c.id}>
                        <td><b>{c.metric}</b></td>
                        <td className={s.mono}>{c.claimed}</td>
                        <td className={s.mono}>{recomp}</td>
                        <td><span className={`${s.pill} ${pillClass(c.verdict)}`}>{c.verdict}</span></td>
                        <td className={s.where}>{(c.context || c.location || c.source || "").slice(0, 90)}</td>
                        <td className={s.why}>
                          {c.reason}
                          {adv.length > 0 && <div className={s.adv}>⚠ validity: {adv.join("; ")}</div>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {job.truncated ? (
                <p className={dash.muted} style={{ marginTop: 8 }}>
                  Showing {job.claims.length} of {job.truncated} discovered claims.
                </p>
              ) : null}
            </>
          ) : (
            <p className={dash.muted}>No reported numbers found in this repo.</p>
          )}
        </>
      )}
    </div>
  );
}
