"use client";

// Connect a repo → verify the numbers, inside the WorkOS-gated dashboard. Submits to the authed proxy
// (/api/verify), polls the job, and renders the three-way verdict per claim + the data-validity layer
// (leakage) — the same loop as the spike SPA, but first-party and behind login.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Claim, GithubConfig, Job, Repo } from "@/lib/verify";
import dash from "./dashboard.module.css";
import s from "./verify.module.css";

const PROBLEMS = ["REFUTED", "INVALIDATED", "NON-DETERMINISTIC"];
const ORDER = ["REFUTED", "INVALIDATED", "CONFIRMED", "NON-DETERMINISTIC", "REPRODUCED-ONLY", "INCONCLUSIVE", "DISCOVERED"];

// Browser-facing URL of the verification service's GitHub-App install flow (an interactive redirect, so it
// can't be proxied). dev = the local spike server; prod = the deployed verify service.
const CONNECT_URL = process.env.NEXT_PUBLIC_VERIFY_CONNECT_URL || "http://localhost:8787/connect/github";

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

  // GitHub connect + repo picker
  const [cfg, setCfg] = useState<GithubConfig["github"] | null>(null);
  const [ghRepos, setGhRepos] = useState<Repo[]>([]);          // installation repos (GitHub App)
  const [ghInstId, setGhInstId] = useState<string | null>(null);   // the installation those repos belong to
  const [myRepos, setMyRepos] = useState<Repo[]>([]);          // the operator's `gh` repos (local dev)
  const [installationId, setInstallationId] = useState<string | null>(null);
  const [reposErr, setReposErr] = useState<string | null>(null);

  // pick a repo: fill the field, and remember the installation when it's an App-connected repo (clears on
  // manual typing) so the backend clones via the short-lived installation token.
  function pick(slug: string, iid: string | null) {
    setRepo(slug);
    setInstallationId(iid);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const c: GithubConfig = await (await fetch("/api/github?kind=config", { cache: "no-store" })).json();
        if (alive) setCfg(c.github);
        if (c.github?.connected) {
          const insts = await (await fetch("/api/github?kind=installations", { cache: "no-store" })).json();
          const iid = Array.isArray(insts) && insts[0]?.installation_id;
          if (iid) {
            const r = await (await fetch(`/api/github?kind=gh-repos&installation_id=${encodeURIComponent(iid)}`, { cache: "no-store" })).json();
            if (alive && Array.isArray(r)) { setGhRepos(r); setGhInstId(iid); }
          }
        }
      } catch { /* config/connect is best-effort */ }
      try {
        const mine = await (await fetch("/api/github?kind=repos", { cache: "no-store" })).json();
        if (alive && Array.isArray(mine)) setMyRepos(mine);
      } catch (e) { if (alive) setReposErr(e instanceof Error ? e.message : String(e)); }
    })();
    return () => { alive = false; };
  }, []);

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
        body: JSON.stringify({ repo: repo.trim(), deep, entry: entry.trim() || null, installation_id: installationId }),
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
          onChange={(e) => { setRepo(e.target.value); setInstallationId(null); }}
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

      {/* GitHub connect: install the App (interactive redirect to the verify service) + state hint */}
      <div className={s.connect}>
        <a className={`${dash.btn} ${dash.btnGhost ?? ""} ${s.ghBtn}`} href={CONNECT_URL}>
          <GithubMark />
          {cfg?.connected ? "GitHub connected — add repos" : "Connect GitHub"}
          {cfg && !cfg.configured ? " (setup)" : ""}
        </a>
        <span className={dash.muted} style={{ fontSize: 12 }}>
          {cfg?.connected
            ? "pick a connected repo below"
            : cfg?.configured
              ? "install the Calma App on your repos"
              : "one-time App registration (see spike/connect/CONNECT.md) — or paste a repo / local path above"}
        </span>
      </div>

      {ghRepos.length > 0 && (
        <RepoList
          title="Your connected repositories"
          repos={ghRepos}
          selected={repo}
          onPick={(slug) => pick(slug, ghInstId)}
        />
      )}
      {myRepos.length > 0 && (
        <RepoList
          title={ghRepos.length ? "Other repositories" : "Or pick one of your repositories"}
          repos={myRepos}
          selected={repo}
          onPick={(slug) => pick(slug, null)}
        />
      )}
      {reposErr && ghRepos.length === 0 && myRepos.length === 0 && (
        <p className={dash.muted} style={{ fontSize: 12 }}>
          Couldn’t list repos ({reposErr}). Paste a repo or local path above.
        </p>
      )}

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

function RepoList({ title, repos, selected, onPick }: {
  title: string; repos: Repo[]; selected: string; onPick: (slug: string) => void;
}) {
  return (
    <div className={s.repos}>
      <div className={s.reposHead}>{title}</div>
      <div className={s.repoList}>
        {repos.slice(0, 60).map((r) => (
          <button
            type="button"
            key={r.slug}
            className={`${s.repoItem} ${selected === r.slug ? s.repoItemOn : ""}`}
            onClick={() => onPick(r.slug)}
          >
            <span className={s.repoName}>
              <b>{r.name}</b>
              {r.description ? <span className={s.repoDesc}>{r.description.slice(0, 80)}</span> : null}
            </span>
            <span className={s.repoTags}>
              {r.visibility ? (
                <span className={`${s.tag} ${/priv/i.test(r.visibility) ? s.tagPriv : ""}`}>
                  {r.visibility.toLowerCase()}
                </span>
              ) : null}
              {r.language ? <span className={s.tag}>{r.language}</span> : null}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function GithubMark() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style={{ verticalAlign: -2, marginRight: 6 }} aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.69-.01-1.36-2.22.48-2.69-1.07-2.69-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.05-.49.05-.49.81.06 1.23.83 1.23.83.72 1.23 1.88.87 2.34.67.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 014 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}
