"use client";

// Connect a repo → verify the numbers, inside the WorkOS-gated dashboard. Submits to the authed proxy
// (/api/verify), polls the job, and renders the three-way verdict per claim + the data-validity layer
// (leakage) — the same loop as the spike SPA, but first-party and behind login.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Claim, GithubConfig, Job, Repo } from "@/lib/verify";
import { ISSUE_TIERS, ORDER, TIER_META, pillTier, tierCounts, verdictLabel, type PillTier } from "@/lib/verdict";
import { recordScan } from "@/lib/scan-history";
import { LogConsole } from "./LogConsole";
import { UpgradeModal } from "./UpgradeModal";
import dash from "./dashboard.module.css";
import s from "./verify.module.css";

// Same-origin connect route → 302s to GitHub's install URL. No hardcoded host, so it works on any deploy.
const CONNECT_URL = "/api/github/connect";

// job.failure_kind: the SUPERVISOR killed the isolated job (a resource/time budget, not the entrypoint's own
// failure — see runner/supervisor.py). Distinct from job.run.failure, which is the entrypoint's own
// classified failure and already carries its own hint string.
const FAILURE_KIND_HINT: Record<string, string> = {
  timeout: "exceeded the time budget for your tier and was stopped — a heavy dependency install or a slow "
    + "entrypoint can hit this; upgrading raises the ceiling, or point Calma at a lighter entrypoint.",
  memory: "ran out of memory for your tier and was stopped — needs a larger tier.",
  cpu: "exceeded the CPU budget and was stopped — needs a larger tier.",
  crashed: "the isolated process crashed unexpectedly.",
};

function pillClass(verdict: string): string {
  return s[pillTier(verdict)];
}

function num(x: unknown): string {
  return typeof x === "number" && Number.isFinite(x) ? Number(x).toPrecision(5) : "—";
}

export function VerifyClient() {
  const [repo, setRepo] = useState("");
  const [deep, setDeep] = useState(true);
  const [acquire, setAcquire] = useState(false);        // paid: run the repo's data-download pipeline
  const [entry, setEntry] = useState("");
  const [pip, setPip] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [gate, setGate] = useState<string | null>(null);  // upgrade-popup reason on a 402 tier gate
  const [busy, setBusy] = useState(false);
  // Defaults to "issues" (bad/inv/neu tiers) — a run with hundreds of discovered-but-unverified claims used
  // to dump ALL of them into one flat table by default, which reads as noise and buries the 2 real catches
  // that actually matter. Each tier chip toggles independently; "confirmed"/"unverifiable"/"not checked yet"
  // are collapsed (but their counts are always visible) until a human asks to see them.
  const [visibleTiers, setVisibleTiers] = useState<Set<PillTier>>(new Set(ISSUE_TIERS));
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Dev / promo code: unlock a higher tier (private repos, un-foolability, bigger budgets) before billing
  // exists. Reflects the currently-unlocked tier from the httpOnly cookie (via /api/dev-code).
  const [devTier, setDevTier] = useState<string | null>(null);
  const [devCode, setDevCode] = useState("");
  const [devMsg, setDevMsg] = useState<string | null>(null);
  const [devBusy, setDevBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch("/api/dev-code", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => { if (alive && d?.tier) setDevTier(d.tier); })
      .catch(() => { /* best-effort */ });
    return () => { alive = false; };
  }, []);

  async function unlockDev(e: React.FormEvent) {
    e.preventDefault();
    if (!devCode.trim() || devBusy) return;
    setDevBusy(true);
    setDevMsg(null);
    try {
      const res = await fetch("/api/dev-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: devCode.trim() }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d?.error || `status ${res.status}`);
      setDevTier(d.tier);
      setDevCode("");
      setDevMsg(`Dev mode on — ${d.tier} tier unlocked. Reconnect private repos below.`);
    } catch (e2) {
      setDevMsg(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setDevBusy(false);
    }
  }

  async function disableDev() {
    setDevBusy(true);
    setDevMsg(null);
    try {
      await fetch("/api/dev-code", { method: "DELETE" });
      setDevTier(null);
      setDevMsg("Dev mode off — back to your normal tier.");
    } catch { /* best-effort */ } finally {
      setDevBusy(false);
    }
  }

  // GitHub connect + repo picker
  const [cfg, setCfg] = useState<GithubConfig["github"] | null>(null);
  const [ghRepos, setGhRepos] = useState<Repo[]>([]);          // installation repos (GitHub App)
  const [ghInstId, setGhInstId] = useState<string | null>(null);   // the installation those repos belong to
  const [myRepos, setMyRepos] = useState<Repo[]>([]);          // the operator's `gh` repos (local dev)
  const [installationId, setInstallationId] = useState<string | null>(null);
  // The stateless proof minted at connect time (server.py _install_proof): the backend's in-memory
  // installation↔tenant binding is wiped on every redeploy, so this is what actually keeps the connection
  // alive across one — resent on every gh-repos/verify call alongside installation_id.
  const [installProof, setInstallProof] = useState<string | null>(null);
  const [reposErr, setReposErr] = useState<string | null>(null);

  // pick a repo: fill the field, and remember the installation when it's an App-connected repo (clears on
  // manual typing) so the backend clones via the short-lived installation token.
  function pick(slug: string, iid: string | null) {
    setRepo(slug);
    setInstallationId(iid);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // Open the GitHub App install in a POPUP so the dashboard stays visible underneath. The popup hands the
  // installation_id back via postMessage (see /api/github/setup) and closes — no full-tab redirect, no
  // "hit back to see the dashboard". Falls back to same-tab navigation if the popup is blocked.
  function openConnect() {
    const w = window.open(CONNECT_URL, "calma-github", "popup,width=1000,height=760");
    if (!w) window.location.href = CONNECT_URL;
  }

  // /api/gh/repos works from the App credentials + the installation_id alone — it does NOT depend on the
  // backend remembering the install (its in-memory map is wiped on every redeploy). So we persist the id
  // client-side and treat it as the source of truth: repos load on return visits, and the connected state
  // sticks. Returns whether repos came back (lets us drop a stale/revoked id).
  const loadInstallationRepos = useCallback(async (iid: string, proof?: string | null): Promise<{ ok: boolean; revoked: boolean }> => {
    setGhInstId(iid);
    setReposErr(null);
    try {
      const q = `installation_id=${encodeURIComponent(iid)}` + (proof ? `&proof=${encodeURIComponent(proof)}` : "");
      const res = await fetch(`/api/github?kind=gh-repos&${q}`, { cache: "no-store" });
      const r = await res.json();
      if (res.ok && Array.isArray(r)) { setGhRepos(r); return { ok: true, revoked: false }; }
      // a non-OK response: surface WHY (usually the backend is missing the GitHub App creds — CALMA_GH_*),
      // and only treat a true 404/revoked as a reason to forget the install — never a transient/empty result.
      const msg = (r && r.error) || `status ${res.status}`;
      setReposErr(String(msg));
      return { ok: false, revoked: res.status === 404 || /not.?found|revoked|suspend|410/i.test(String(msg)) };
    } catch (e) {
      setReposErr(e instanceof Error ? e.message : "the verification backend is unreachable");
      return { ok: false, revoked: false };   // transient → KEEP the connection
    }
  }, []);

  const LS_KEY = "calma_gh_installation_id";
  const LS_PROOF_KEY = "calma_gh_install_proof";

  function rememberInstall(iid: string, proof: string) {
    try {
      localStorage.setItem(LS_KEY, iid);
      if (proof) localStorage.setItem(LS_PROOF_KEY, proof); else localStorage.removeItem(LS_PROOF_KEY);
    } catch { /* private mode */ }
    setInstallationId(iid);
    setInstallProof(proof || null);
  }

  useEffect(() => {
    let alive = true;
    // 1) just installed? GitHub redirected here with ?installation_id=…&proof=… — adopt + remember it, tidy
    // the URL. `proof` is the stateless binding (see server.py _install_proof) that keeps this connection
    // alive across a backend redeploy, which wipes the server's in-memory installation map.
    const params = new URLSearchParams(window.location.search);
    // Re-run from a scan detail: /dashboard/verify?repo=owner/name prefills the field.
    const repoParam = params.get("repo");
    if (repoParam) setRepo(repoParam);
    let iid = params.get("installation_id");
    let proof = params.get("proof") || "";
    if (iid || repoParam) {
      if (iid) rememberInstall(iid, proof);
      window.history.replaceState({}, "", "/dashboard/verify");
    }
    // 2) else reuse a remembered install (survives backend redeploys via the proof, not backend memory).
    if (!iid) {
      try { iid = localStorage.getItem(LS_KEY); proof = localStorage.getItem(LS_PROOF_KEY) || ""; }
      catch { iid = null; proof = ""; }
    }
    if (iid) {
      setInstallationId(iid);
      setInstallProof(proof || null);
      const adopted = iid;
      loadInstallationRepos(adopted, proof).then((st) => {
        // only forget the install if GitHub says it's truly gone (revoked/404) — NOT on a transient backend
        // error or an empty repo list, which used to silently drop a valid connection (the "asks to connect
        // again" bug).
        if (st.revoked) {
          try { localStorage.removeItem(LS_KEY); localStorage.removeItem(LS_PROOF_KEY); } catch { /**/ }
          setInstallationId(null); setInstallProof(null);
        }
      });
    }
    (async () => {
      try {
        const c: GithubConfig = await (await fetch("/api/github?kind=config", { cache: "no-store" })).json();
        if (alive) setCfg(c.github);
        if (!iid && c.github?.connected) {                 // backend still remembers an install (no proof needed)
          const insts = await (await fetch("/api/github?kind=installations", { cache: "no-store" })).json();
          const bid = Array.isArray(insts) && insts[0]?.installation_id;
          if (bid && alive) { setInstallationId(bid); loadInstallationRepos(bid); }
        }
      } catch { /* config is best-effort */ }
      try {                                                 // operator's gh repos (local dev only; [] in prod)
        const mine = await (await fetch("/api/github?kind=repos", { cache: "no-store" })).json();
        if (alive && Array.isArray(mine)) setMyRepos(mine);
      } catch (e) { if (alive) setReposErr(e instanceof Error ? e.message : String(e)); }
    })();
    return () => { alive = false; };
  }, [loadInstallationRepos]);

  // The connect popup posts the installation_id + proof back here (so the dashboard updates in place). Adopt
  // it the same way as the ?installation_id URL param — same-origin messages only.
  useEffect(() => {
    function onMsg(e: MessageEvent) {
      if (e.origin !== window.location.origin) return;
      const iid = e.data && e.data.source === "calma-github" ? String(e.data.installation_id || "") : "";
      if (iid) {
        const proof = String(e.data.proof || "");
        rememberInstall(iid, proof);
        loadInstallationRepos(iid, proof);
      }
    }
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [loadInstallationRepos]);

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
    setVisibleTiers(new Set(ISSUE_TIERS));
    try {
      const res = await fetch("/api/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo: repo.trim(),
          deep,
          acquire_data: acquire,
          entry: entry.trim() || null,
          pip_install: pip.trim() ? pip.trim().split(/\s+/) : null,
          installation_id: installationId,
          installation_proof: installProof,
        }),
      });
      const data = await res.json();
      // a tier gate (402) → the upgrade popup with the backend's plain-language reason, not an inline error.
      if (res.status === 402) {
        setGate(data?.error || "This is a paid feature — upgrade to unlock it.");
        setBusy(false);
        return;
      }
      if (!res.ok) throw new Error(data?.error || `status ${res.status}`);
      recordScan(data.id, repo.trim());   // durable local index — survives a backend redeploy for the Scans tab
      poll(data.id);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
      setBusy(false);
    }
  }

  const counts = job?.counts || {};
  const byTier = tierCounts(counts);
  const issueTotal = ISSUE_TIERS.reduce((n, t) => n + byTier[t], 0);
  const leak = job?.leakage || [];
  const connected = !!installationId || !!cfg?.connected;   // a known install (client-remembered or backend)

  function toggleTier(t: PillTier) {
    setVisibleTiers((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  }

  const claims: Claim[] = (job?.claims || [])
    .filter((c) => visibleTiers.has(pillTier(c.verdict)))
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
          Deep verify (re-run the code to recompute the numbers)
        </label>
        {deep && (
          <label title="Runs the repo's own data-download scripts (numbered NN_*.py or a `make data` target) before verifying — for repos whose datasets aren't bundled. A paid capability.">
            <input type="checkbox" checked={acquire} onChange={(e) => setAcquire(e.target.checked)} />
            Download the repo&apos;s data <span className={dash.muted} style={{ fontSize: 11 }}>(Pro)</span>
          </label>
        )}
      </div>

      {/* Advanced: entrypoint + deps are auto-detected/inferred; this is the manual override. */}
      {deep && (
        <details className={s.advanced}>
          <summary className={s.advancedSummary}>Advanced settings</summary>
          <div className={s.advancedBody}>
            <label className={s.advField}>
              <span>Entrypoint</span>
              <input
                className={`${dash.input} ${s.entry}`}
                placeholder="auto-detected, e.g. eval.py"
                value={entry}
                onChange={(e) => setEntry(e.target.value)}
                spellCheck={false}
              />
            </label>
            <label className={s.advField}>
              <span>Extra dependencies</span>
              <input
                className={`${dash.input} ${s.entry}`}
                placeholder="auto-inferred, e.g. scikit-learn pandas"
                value={pip}
                onChange={(e) => setPip(e.target.value)}
                spellCheck={false}
              />
            </label>
          </div>
        </details>
      )}

      {/* GitHub connect: install the App (interactive redirect) + state hint */}
      <div className={s.connect}>
        <button type="button" className={`${dash.btn} ${dash.btnGhost ?? ""} ${s.ghBtn}`} onClick={openConnect}>
          <GithubMark />
          {connected ? "GitHub connected — add repos" : "Connect GitHub"}
          {cfg && !cfg.configured ? " (setup)" : ""}
        </button>
        <span className={dash.muted} style={{ fontSize: 12 }}>
          {connected
            ? "pick a connected repo below"
            : cfg?.configured === false
              ? "one-time App registration (see spike/connect/CONNECT.md) — or paste a repo / local path above"
              : "install the Calma App on your repos — or paste a repo / local path above"}
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
        /^that GitHub installation is not connected/i.test(reposErr) ? (
          // The backend's per-tenant binding is a stateless proof minted at connect time (server.py
          // _install_proof) — a connection made before that existed, or before the CURRENT signing secret,
          // has no valid proof and reads as "not connected" even though the GitHub App install is real and
          // still active. One click through Connect re-mints a fresh proof; no need to uninstall/reinstall
          // the App on GitHub's side.
          <div className={`${dash.notice} ${dash.noticeWarn}`} style={{ marginTop: 4 }}>
            <p style={{ margin: "0 0 8px" }}>
              Your GitHub connection needs to be refreshed — the server can no longer verify it, even though
              the App is still installed.
            </p>
            <button type="button" className={dash.btn} onClick={openConnect}>
              Reconnect GitHub
            </button>
          </div>
        ) : (
          <p className={dash.muted} style={{ fontSize: 12 }}>
            Couldn’t list repos ({reposErr}). Paste a repo or local path above.
          </p>
        )
      )}

      {err && <div className={`${dash.notice} ${dash.noticeErr}`}>{err}</div>}

      {busy && !job && <p className={dash.muted}>Cloning and preparing the repo…</p>}
      {job?.status === "error" && (
        <div className={`${dash.notice} ${dash.noticeErr}`}>
          {job.failure_kind && FAILURE_KIND_HINT[job.failure_kind] ? (
            <>
              {FAILURE_KIND_HINT[job.failure_kind]}
              {job.error && (
                <details style={{ marginTop: 6 }}>
                  <summary style={{ cursor: "pointer", fontSize: 12 }}>raw error</summary>
                  <span className={s.mono}>{job.error}</span>
                </details>
              )}
            </>
          ) : (
            job.error || "verification failed"
          )}
        </div>
      )}

      {/* Live e2e log: every step from clone → build → run → recompute, streamed as it happens. This is the
          window into a long deep verify (a heavy install, the run's own output) — and the post-mortem when a
          job is stopped for a budget. */}
      {job && (job.status === "running" || job.status === "queued" || (job.logs?.length ?? 0) > 0) && (
        <LogConsole job={job} />
      )}

      {job?.status === "done" && (
        <>
          {job.run && (
            <div className={`${s.banner} ${job.run.ran ? s.bannerOk : s.bannerWarn}`}>
              {job.run.ran ? (
                <>
                  Re-ran <code>{job.run.entry}</code> · captured {job.run.calls} computation(s) ·{" "}
                  <b>{issueTotal} need attention</b>, {byTier.ok} confirmed.
                </>
              ) : (
                <>
                  Tried to re-run <code>{job.run.entry}</code> but it didn&apos;t execute
                  {job.run.failure?.hint ? (
                    <> — {job.run.failure.hint}</>
                  ) : job.run.error ? (
                    <>
                      {" "}— <span className={s.mono}>{job.run.error}</span>
                    </>
                  ) : null}
                  .
                  {(job.run.error || job.run.error_full) && (
                    <details>
                      <summary className={dash.muted} style={{ cursor: "pointer", fontSize: 12 }}>
                        {job.run.failure?.hint ? "raw error" : "full error output"}
                      </summary>
                      <pre className={s.mono}>{job.run.error_full || job.run.error}</pre>
                    </details>
                  )}
                  <br />
                  {job.run.failure?.kind === "missing-data" ? (
                    <>
                      This repo downloads its data at runtime rather than bundling it. Turn on{" "}
                      <b>Download the repo&apos;s data</b> above to run its acquisition pipeline first (a Pro
                      capability), or connect the data — then Calma can recompute the {job.n_claims} numbers below.
                    </>
                  ) : (
                    <>
                      Showing the {job.n_claims} numbers Calma found — give it a runnable entrypoint (and any
                      data/deps) to deep-verify them.
                    </>
                  )}
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

          {job.n_claims > 0 ? (
            <>
              {/* Tier chips: each toggles its own rows independently. Defaults to "issues" only (caught /
                  invalidated / unstable) — a big repo can discover hundreds of claims, and dumping all of
                  them into one flat table by default buried the 2 that actually matter. The count is always
                  visible even when a tier is collapsed, so "confirmed: 40" / "not checked yet: 300" reads as
                  real information, not a void. */}
              <div className={s.filters}>
                {TIER_META.map(({ tier, label }) => {
                  const n = byTier[tier];
                  const on = visibleTiers.has(tier);
                  return (
                    <button
                      key={tier}
                      type="button"
                      className={`${s.filter} ${on ? s.filterOn : ""}`}
                      onClick={() => toggleTier(tier)}
                      disabled={n === 0}
                    >
                      <span className={`${s.pill} ${s[tier]}`} style={{ marginRight: 6 }}>{n}</span>
                      {label}
                    </button>
                  );
                })}
                {visibleTiers.size < TIER_META.length && (
                  <button type="button" className={s.filter} onClick={() => setVisibleTiers(new Set(TIER_META.map((t) => t.tier)))}>
                    show all ({job.n_claims})
                  </button>
                )}
              </div>

              {claims.length === 0 ? (
                <p className={dash.muted} style={{ margin: "4px 0 12px" }}>
                  {issueTotal === 0
                    ? `No issues found — ${byTier.ok} claim(s) confirmed. Click a tier above to see the rest.`
                    : "Nothing in the selected tiers — click one above to show its rows."}
                </p>
              ) : (
                <>
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
                            <td><span className={`${s.pill} ${pillClass(c.verdict)}`}>{verdictLabel(c.verdict)}</span></td>
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
              )}
            </>
          ) : (
            <p className={dash.muted}>No reported numbers found in this repo.</p>
          )}
        </>
      )}

      {/* Dev / promo code — pre-billing unlock for private repos + paid features. Collapsed by default. */}
      <details className={s.advanced} style={{ marginTop: 32 }}>
        <summary className={s.advancedSummary}>
          {devTier ? `Dev mode: ${devTier} tier unlocked` : "Have a dev code?"}
        </summary>
        <div className={s.advancedBody}>
          {devTier ? (
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <span className={dash.muted} style={{ fontSize: 13 }}>
                All <b>{devTier}</b>-tier features are on (private repos, un-foolability, bigger budgets).
              </span>
              <button type="button" className={dash.btn} onClick={disableDev} disabled={devBusy}>
                Turn off
              </button>
            </div>
          ) : (
            <form onSubmit={unlockDev} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <input
                className={`${dash.input} ${s.entry}`}
                placeholder="dev code"
                value={devCode}
                onChange={(e) => setDevCode(e.target.value)}
                spellCheck={false}
                autoCapitalize="off"
              />
              <button className={dash.btn} type="submit" disabled={devBusy || !devCode.trim()}>
                {devBusy ? "…" : "Unlock"}
              </button>
            </form>
          )}
          {devMsg && (
            <p className={dash.muted} style={{ fontSize: 12, marginTop: 8 }}>{devMsg}</p>
          )}
        </div>
      </details>

      <UpgradeModal reason={gate} onClose={() => setGate(null)} />
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
