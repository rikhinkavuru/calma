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

let POLL = null, FILTER = "ALL";

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
    box.addEventListener("click", e => { const it = e.target.closest(".repoitem"); if (it) { $("#repo").value = it.dataset.slug; window.scrollTo({ top: 0, behavior: "smooth" }); } });
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
  const seq = ["cloning", "discovering", ...(deep ? ["building", "running", "diffing"] : []), "done"];
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

  const res = $("#results");
  res.innerHTML = `${banner}
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
      <div class="sum"><div class="n">${c.curated}</div><div class="l">curated</div></div>
      <div class="sum"><div class="n" style="color:var(--purple)">${c.banked}</div><div class="l">✦ synthesized + banked</div></div>
    </div>
    <div class="catgrid">${all.map(catCard).join("")}</div>`;
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

loadRepos();
