// Calma web — connect a repo, verify the numbers. Vanilla JS over the spike API.
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const PILL = { "CONFIRMED": "CONFIRMED", "REFUTED": "REFUTED", "INVALIDATED": "INVALIDATED",
  "NON-DETERMINISTIC": "NONDET", "REPRODUCED-ONLY": "REPRO", "INCONCLUSIVE": "INCONCLUSIVE", "DISCOVERED": "DISCOVERED" };
const ORDER = ["REFUTED", "INVALIDATED", "CONFIRMED", "NON-DETERMINISTIC", "REPRODUCED-ONLY", "INCONCLUSIVE", "DISCOVERED"];
const PROBLEMS = ["REFUTED", "INVALIDATED", "NON-DETERMINISTIC"];   // "not correct" — surfaced by default
const CLEAN = ["CONFIRMED", "REPRODUCED-ONLY"];
const sumc = (counts, vs) => vs.reduce((a, v) => a + (counts[v] || 0), 0);
const defaultFilter = (job) => (sumc(job.counts || {}, [...PROBLEMS, ...CLEAN, "INCONCLUSIVE"]) > 0 ? "PROBLEMS" : "ALL");

let POLL = null, FILTER = "ALL", INSTALL = null;   // INSTALL = the GitHub App installation_id, when a connected repo is picked

// ---- deep-verify options show/hide ----
$("#deep").addEventListener("change", e => $("#deepopts").classList.toggle("hidden", !e.target.checked));

// ---- examples ----
$("#examples").addEventListener("click", e => {
  const c = e.target.closest(".chip"); if (!c) return;
  $("#repo").value = c.dataset.repo;
  if (c.dataset.deep) { $("#deep").checked = true; $("#deepopts").classList.remove("hidden");
    $("#entry").value = c.dataset.entry || ""; $("#pip").value = c.dataset.pip || ""; }
  start();
});

// ---- your repos ----
async function loadRepos() {
  try {
    const repos = await (await fetch("/api/repos")).json();
    if (!repos.length) return;
    const numberish = /benchmark|eval|leakage|mimicry|metric|result|model|stat|test|audit|atlas/i;
    repos.sort((a, b) => (numberish.test(b.name + b.description) ? 1 : 0) - (numberish.test(a.name + a.description) ? 1 : 0));
    const box = document.createElement("div");
    box.innerHTML = `<label class="f" style="margin-top:18px">Or pick one of your repositories</label>
      <div class="repolist">${repos.map(r => `
        <div class="repoitem" data-slug="${esc(r.slug)}">
          <div><b>${esc(r.name)}</b> <span class="muted" style="font-size:12px">${esc(r.description).slice(0, 70)}</span></div>
          <div><span class="tag ${r.visibility === "PRIVATE" ? "priv" : ""}">${esc(r.visibility.toLowerCase())}</span>
               <span class="tag">${esc(r.language || "?")}</span></div>
        </div>`).join("")}</div>`;
    box.addEventListener("click", e => { const it = e.target.closest(".repoitem"); if (it) { $("#repo").value = it.dataset.slug; INSTALL = null; window.scrollTo({ top: 0, behavior: "smooth" }); } });
    $("#repos").appendChild(box);
  } catch (_) { }
}

// ---- start a verify ----
$("#go").addEventListener("click", start);
$("#repo").addEventListener("keydown", e => { if (e.key === "Enter") start(); });

async function start() {
  const repo = $("#repo").value.trim();
  if (!repo) { $("#repo").focus(); return; }
  if (POLL) clearInterval(POLL);
  $("#go").disabled = true; $("#results").innerHTML = "";
  const body = {
    repo, discover: $("#discover").checked, deep: $("#deep").checked,
    runner: $("#runner").value, entry: $("#entry").value.trim() || null,
    pip_install: $("#pip").value.trim() ? $("#pip").value.trim().split(/\s+/) : null,
    installation_id: INSTALL,   // clone via the GitHub App token when a connected repo is picked
  };
  const { id } = await (await fetch("/api/verify", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })).json();
  POLL = setInterval(() => poll(id), 1100);
  poll(id);
}

async function poll(id) {
  const job = await (await fetch("/api/jobs/" + id)).json();
  renderJob(job);
  if (job.status === "done" || job.status === "error") {
    clearInterval(POLL); POLL = null; $("#go").disabled = false;
    if (job.status === "done") { FILTER = defaultFilter(job); renderResults(job); }
  }
}

function renderJob(job) {
  const deep = job.deep;
  const seq = ["cloning", ...(deep ? ["building", "running"] : []), "discovering", "checking data",
               ...(deep ? ["diffing"] : []), "done"];
  const cur = seq.indexOf(job.stage);
  const panel = $("#job"); panel.classList.remove("hidden");
  const running = job.status === "running" || job.status === "queued";
  panel.innerHTML = `
    <div class="row" style="justify-content:space-between">
      <div><b>${esc(job.repo)}</b> <span class="muted mono">${esc(job.id)}</span></div>
      <div>${running ? '<span class="spin"></span> ' + esc(job.stage) : (job.status === "error" ? '<span class="pill REFUTED">error</span>' : '<span class="pill CONFIRMED">done</span>')}</div>
    </div>
    <div class="stages" style="margin-top:12px">
      ${seq.map((s, i) => `<span class="stage ${i < cur || job.stage === "done" ? "done" : (i === cur ? "on" : "")}">${s}</span>`).join("")}
    </div>
    ${job.error ? `<div class="reason" style="margin-top:10px;color:var(--red)">${esc(job.error)}</div>` : ""}
    <div class="logbox mono">${(job.logs || []).map(l => `<div>${esc(l)}</div>`).join("")}</div>`;
}

function renderResults(job) {
  const claims = job.claims || [];
  const counts = job.counts || {};
  const g = { problems: sumc(counts, PROBLEMS), clean: sumc(counts, CLEAN),
              inconclusive: counts["INCONCLUSIVE"] || 0, discovered: counts["DISCOVERED"] || 0 };

  const run = job.run;
  const banner = run ? `<div class="banner ${run.ran ? "ok" : "warn"}">${run.ran
      ? `Re-ran <code>${esc(run.entry)}</code> · captured ${run.calls} computation(s) · <b>${g.problems} need attention</b>, ${g.clean} hold up.`
      : `Tried to re-run <code>${esc(run.entry)}</code> but it didn't execute${run.error ? `: <span class="mono">${esc(run.error).slice(0, 150)}</span>` : ""}.<br/>Showing the ${claims.length} numbers Calma found — give it a runnable entrypoint (and any data/deps) to deep-verify them.`}</div>` : "";

  // grouped summary: problems first, then clean / couldn't-verify / found
  const card = (n, label, color) => n ? `<div class="sum"><div class="n" style="color:${color}">${n}</div><div class="l">${label}</div></div>` : "";
  const cards = [card(g.problems, "needs attention", "var(--red)"), card(g.clean, "verified clean", "var(--green)"),
                card(g.inconclusive, "couldn't verify", "var(--slate)"), card(g.discovered, "found · not re-run", "var(--ink)")]
                .filter(Boolean).join("") || '<div class="sum"><div class="n">0</div><div class="l">no numeric claims found</div></div>';

  const present = ORDER.filter(v => counts[v]);
  const fdefs = [["PROBLEMS", "Needs attention (" + g.problems + ")"],
                 ...present.map(v => [v, v + " (" + counts[v] + ")"]), ["ALL", "All (" + claims.length + ")"]];
  const filters = fdefs.map(([f, label]) => `<span class="filt ${FILTER === f ? "on" : ""}" data-f="${f}">${label}</span>`).join("");

  // data-validity: leakage / contamination (no re-run) — surfaced prominently, it invalidates the numbers
  const leak = job.leakage || [];
  const leakPanel = leak.length ? `<div class="banner warn" style="border-color:#f1c0c0;background:#fdeef0">
    <b style="color:var(--red)">⚠ Data leakage — ${leak.length} dataset(s) contaminated</b>
    <div class="muted" style="margin:3px 0 8px">A leaked train/test split makes the held-out numbers invalid, even if they recompute perfectly.</div>
    ${leak.map(d => `<div style="margin-top:8px"><b>${esc(d.dataset)}</b> ${d.findings.map(f => `<span class="pill INVALIDATED">${esc(f.kind)} ${(100 * f.magnitude).toFixed(0)}%</span>`).join(" ")}
      <div class="muted" style="font-size:12px;margin-top:2px">${esc(d.findings[0].detail)}</div></div>`).join("")}</div>` : "";

  const res = $("#results");
  res.innerHTML = `${leakPanel}${banner}
    <div class="sumgrid">${cards}</div>
    ${job.truncated ? `<p class="muted">Showing 500 of ${job.truncated} discovered claims.</p>` : ""}
    <div class="card">
      <div class="pad" style="padding-bottom:0"><div class="filters">${filters}</div></div>
      <div id="tbl"></div>
    </div>`;
  res.querySelector(".filters").addEventListener("click", e => {
    const f = e.target.closest(".filt"); if (!f) return; FILTER = f.dataset.f; renderResults(job);
  });
  renderTable(claims, g);
}

function renderTable(claims, g) {
  const pool = FILTER === "PROBLEMS" ? claims.filter(c => PROBLEMS.includes(c.verdict))
            : FILTER === "ALL" ? claims : claims.filter(c => c.verdict === FILTER);
  const rows = pool.slice().sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict)).slice(0, 300);
  if (!rows.length) {
    let msg = "No claims for this filter.", clear = "";
    if (FILTER === "PROBLEMS") {
      if (g.clean) { clear = "clear"; msg = `✓ All ${g.clean} verified claim(s) hold up — nothing misreported, invalid, or non-reproducible.` + (g.discovered ? ` <span class="muted">(${g.discovered} more found but not re-run.)</span>` : ""); }
      else if (g.discovered) msg = `Nothing verified yet — ${g.discovered} claim(s) found. Turn on <b>Deep verify</b> with an entrypoint to check them.`;
      else msg = "No problems found.";
    }
    $("#tbl").innerHTML = `<div class="empty ${clear}">${msg}</div>`;
    return;
  }
  $("#tbl").innerHTML = `<table>
    <thead><tr><th>Metric</th><th>Claimed</th><th>Recomputed</th><th>Verdict</th><th>Where</th><th>Why</th></tr></thead>
    <tbody>${rows.map(c => {
      const d = c.diff || {};
      const recomp = d.recomputed != null ? (+d.recomputed).toPrecision(5) : (d.produced != null ? (+d.produced).toPrecision(5) : "—");
      const where = esc(c.context || c.location || c.source || "");
      const prov = provenanceTag(c.provenance);
      return `<tr>
        <td><b>${esc(c.metric)}</b></td>
        <td class="mono">${esc(c.claimed)}</td>
        <td class="mono">${recomp}${prov}</td>
        <td><span class="pill ${PILL[c.verdict] || "INCONCLUSIVE"}">${esc(c.verdict)}</span></td>
        <td class="muted" style="font-size:12px;max-width:230px">${where.slice(0, 90)}</td>
        <td class="reason">${esc(c.reason || "")}</td>
      </tr>`;
    }).join("")}</tbody></table>
    ${rows.length === 300 ? '<div class="empty" style="padding:14px">Showing first 300.</div>' : ""}`;
}

// how a claim was independently recomputed — the flywheel makes this visible
function provenanceTag(p) {
  if (!p || p === "catalog") return "";
  if (p === "synth") return '<div class="prov synth">✦ synthesized + validated</div>';
  if (p === "recipe") return '<div class="prov bank">✦ recipe catalog</div>';
  if (p && p.indexOf("store") === 0) return '<div class="prov bank">✦ banked formula</div>';
  return "";
}

// ---- Catalog view: everything Calma can recompute (curated + flywheel-banked) ----
function showView(which) {
  $("#verifyView").classList.toggle("hidden", which !== "verify");
  $("#catalogView").classList.toggle("hidden", which !== "catalog");
  $("#nav-verify").classList.toggle("active", which === "verify");
  $("#nav-catalog").classList.toggle("active", which === "catalog");
  if (which === "catalog") loadCatalog();
}
$("#nav-verify").addEventListener("click", () => showView("verify"));
$("#nav-catalog").addEventListener("click", () => showView("catalog"));

async function loadCatalog() {
  const cv = $("#catalogView");
  cv.innerHTML = '<h1>Formula catalog</h1><p class="sub">Loading…</p>';
  let data;
  try { data = await (await fetch("/api/catalog")).json(); }
  catch (_) { cv.innerHTML = '<h1>Formula catalog</h1><p class="sub">Could not load.</p>'; return; }
  const all = [...data.banked, ...data.curated];   // synthesized first — the flywheel's growth
  const c = data.counts;
  cv.innerHTML = `
    <h1>Formula catalog</h1>
    <p class="sub">Everything Calma can recompute — the curated trusted catalog plus formulas the flywheel synthesized, validated, and banked (store: <b>${esc(data.store)}</b>). The banked set grows every time a repo reports a metric we haven't seen.</p>
    <div class="sumgrid">
      <div class="sum"><div class="n">${c.total}</div><div class="l">metrics</div></div>
      <div class="sum"><div class="n">${c.recipes || 0}</div><div class="l">lifted recipes</div></div>
      <div class="sum"><div class="n">${c.curated}</div><div class="l">curated (clean)</div></div>
      <div class="sum"><div class="n" style="color:var(--purple)">${c.banked}</div><div class="l">✦ synthesized + banked</div></div>
    </div>
    <div class="catgrid">${all.map(catCard).join("")}</div>
    ${(data.recipes && data.recipes.length) ? `<h2 style="margin:32px 0 2px;font-size:16px">Lifted recipe catalog (${data.recipes.length})</h2>
      <p class="muted" style="margin:0 0 12px">The previous engine's trusted math, bound to captured inputs — quant risk, derivatives, credit, retrieval, forecasting, analytics, and more.</p>
      <div class="chips">${data.recipes.map(r => `<span class="tag">${esc(r)}</span>`).join(" ")}</div>` : ""}`;
}

function catCard(m) {
  const syn = m.kind === "synthesized";
  const aliases = (m.aliases || []).slice(0, 6).map(a => `<span class="tag">${esc(a)}</span>`).join(" ");
  const v = m.validation || {};
  const val = v.method ? esc(v.method) + (v.max_err != null ? ` (max_err ${(+v.max_err).toExponential(1)})` : "") : "";
  return `<div class="catcard ${syn ? "syn" : ""}">
    <div class="row" style="justify-content:space-between;align-items:start">
      <b>${esc(m.metric)}</b>
      <span class="cattag ${syn ? "syn" : "cur"}">${syn ? "✦ synthesized" : "curated"}</span>
    </div>
    ${aliases ? `<div style="margin:8px 0 2px">${aliases}</div>` : ""}
    ${m.definition ? `<div class="muted" style="font-size:12px;margin:7px 0">${esc(m.definition).slice(0, 150)}</div>` : ""}
    ${val ? `<div class="muted" style="font-size:11.5px;margin-top:4px">✓ ${val}</div>` : ""}
    ${m.source && m.source !== "trusted catalog" ? `<div class="muted mono" style="font-size:10.5px;margin-top:4px">${esc(m.source)}</div>` : ""}
  </div>`;
}

$("#repo").addEventListener("input", () => { INSTALL = null; });   // manual input ≠ an installation repo

(async () => {
  let cfg = {};
  try { cfg = await (await fetch("/api/config")).json(); } catch (_) { }
  if (!cfg.internal) $("#nav-catalog").style.display = "none";   // catalog is internal-only
  renderGhConnect(cfg.github || {});
})();

function renderGhConnect(gh) {
  const box = $("#ghconnect");
  if (!box) return;
  const icon = '<svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" style="vertical-align:-2px;margin-right:5px"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.69-.01-1.36-2.22.48-2.69-1.07-2.69-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.05-.49.05-.49.81.06 1.23.83 1.23.83.72 1.23 1.88.87 2.34.67.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 014 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>';
  box.innerHTML = `<a class="btn ghost" href="/connect/github" style="font-size:13px">${icon}${gh.connected ? "GitHub connected — add repos" : "Connect GitHub"}${gh.configured ? "" : " (setup)"}</a>
    <span class="muted" style="font-size:12px;margin-left:8px">${gh.connected ? "pick a repo below" : (gh.configured ? "install on your repos" : "one-time App registration — see CONNECT.md")}</span>`;
  if (gh.connected) loadInstallationRepos();
}

async function loadInstallationRepos() {
  try {
    const insts = await (await fetch("/api/installations")).json();
    if (!insts.length) return;
    const id = insts[0].installation_id;
    const repos = await (await fetch("/api/gh/repos?installation_id=" + encodeURIComponent(id))).json();
    if (!Array.isArray(repos) || !repos.length) return;
    const box = document.createElement("div");
    box.innerHTML = `<label class="f" style="margin-top:14px">Your connected repositories</label>
      <div class="repolist">${repos.map(r => `<div class="repoitem" data-slug="${esc(r.slug)}">
        <div><b>${esc(r.name)}</b> <span class="muted" style="font-size:12px">${esc(r.description).slice(0, 70)}</span></div>
        <div><span class="tag ${r.visibility === "private" ? "priv" : ""}">${esc(r.visibility)}</span></div></div>`).join("")}</div>`;
    box.addEventListener("click", e => { const it = e.target.closest(".repoitem"); if (it) { $("#repo").value = it.dataset.slug; INSTALL = id; window.scrollTo({ top: 0, behavior: "smooth" }); } });
    $("#repos").appendChild(box);
  } catch (_) { }
}

loadRepos();
