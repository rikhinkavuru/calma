"""calma.registry_site - D1: a self-contained, DEPLOYABLE static site for a Calma catch-history
registry. Renders the hash-chained, SSHSIG-signed registry (HEAD.json + entries/) into a single
index.html anyone can host (GitHub Pages, S3, Netlify, a plain file://) so a public, trusted
catch-record accumulates and is browsable + independently verifiable.

This is the credibility flywheel's surface: every catch that gets published becomes a public,
tamper-evident row; the value of a Calma stamp grows with the length of the chain. The page leads with
the chain-verification STATUS (re-derived offline at build time) and ships the raw registry alongside,
so a visitor never has to trust the rendered HTML - they re-run `calma registry verify` (or stock
`ssh-keygen -Y verify`) over the bytes.

Distinct from the live marketing UI (`app/registry`): this is a zero-dependency static artifact a
THIRD PARTY can deploy from the registry alone, the way report.py ships a self-contained replay bundle.

Renders ONLY the redaction whitelist (registry.ALLOWED_FIELDS) - never code, data, or positions; the
entry derivation already enforced that boundary, this is display-only and re-escapes everything.

Library: build_site(reg_dir, out_dir=None) -> out_dir; render_index(reg_dir) -> html_str.
"""
import html
import json
import os
import shutil

import pathsafe as PS
import registry as REG

_CSS = """
:root{--ink:#0A0A0B;--mut:#71717A;--mut2:#A1A1AA;--paper:#FAFAF7;--line:#E4E1D8;--amber:#B8821B;
--green:#2F7D43;--red:#B23A33;--card:#fff}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:48px 24px 80px}
.mono{font-family:ui-monospace,Menlo,"SF Mono",Consolas,monospace}
.brand{font-family:ui-monospace,Menlo,monospace;font-weight:700;letter-spacing:3px;font-size:15px}
.brand .dot{color:var(--amber)}
h1{font-size:26px;margin:18px 0 4px;letter-spacing:-.01em}
.sub{color:var(--mut);margin:0 0 22px}
.status{display:inline-flex;align-items:center;gap:10px;padding:10px 16px;border-radius:10px;
border:2px solid;font-family:ui-monospace,Menlo,monospace;font-weight:700;margin:6px 0 4px}
.ok{color:var(--green);border-color:var(--green);background:#EAF3EC}
.bad{color:var(--red);border-color:var(--red);background:#F6E9E8}
.counts{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}
.chip{font-family:ui-monospace,Menlo,monospace;font-size:13px;border:1px solid var(--line);
border-radius:999px;padding:6px 13px;background:var(--card)}
.chip b{color:var(--ink)}
table{width:100%;border-collapse:collapse;margin:14px 0;background:var(--card);border:1px solid var(--line);
border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:11px 13px;border-bottom:1px solid var(--line);font-size:14px;vertical-align:top}
th{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);background:#FBFAF6}
td.mono{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;word-break:break-all}
.v{font-family:ui-monospace,Menlo,monospace;font-weight:700;font-size:12px;padding:3px 8px;border-radius:6px}
.v-REFUTED,.v-INVALIDATED,.v-MIXED{color:var(--red);background:#F6E9E8}
.v-CONFIRMED,.v-CONFIRMED-WITH-CAVEATS{color:var(--green);background:#EAF3EC}
.v-INCONCLUSIVE{color:var(--amber);background:#F6EFDD}
.gap{color:var(--red)}
.verify{background:#0A0A0B;color:#E4E1D8;border-radius:10px;padding:18px 20px;margin:22px 0;
font-family:ui-monospace,Menlo,monospace;font-size:13px;line-height:1.7;overflow-x:auto}
.verify .c{color:#4ADE80}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);color:var(--mut);font-size:12px;
font-family:ui-monospace,Menlo,monospace;line-height:1.7}
a{color:var(--amber)}
"""


def _esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def _fmt(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return _esc(v)
    f = float(v)
    if f != f:
        return "NaN"
    return ("%d" % f) if f == int(f) and abs(f) < 1e15 else ("%.6g" % f)


def render_index(reg_dir):
    """The self-contained index.html for a registry dir. Re-verifies the chain offline at build time
    and renders the redacted entries newest-first. Pure string build; no network."""
    ok, checks, summary = REG.verify_chain(reg_dir)
    head = REG.read_head(reg_dir) or {}
    entries = [w.get("entry", {}) for _n, w in REG.load_entries(reg_dir)]
    n = len(entries)
    verdicts = summary.get("verdicts") or {}

    P = ["<!doctype html><html lang=en><head><meta charset=utf-8>",
         "<meta name=viewport content='width=device-width,initial-scale=1'>",
         "<title>Calma catch-history registry</title><style>%s</style></head><body><div class=wrap>" % _CSS,
         "<div class=brand>CALMA<span class=dot>.</span> &nbsp;CATCH-HISTORY REGISTRY</div>",
         "<h1>A public, tamper-evident record of every verified result</h1>",
         "<p class=sub>Each row is a hash-chained, signed verdict. Redacted by construction: the claim, "
         "the recomputed number, and content hashes &mdash; never code, data, or positions.</p>"]

    # the verification status leads (re-derived from the bytes at build time)
    cls, word = ("ok", "CHAIN VERIFIED") if ok else ("bad", "CHAIN BROKEN")
    P.append("<div class='status %s'>%s &middot; %d entr%s</div>"
             % (cls, word, n, "y" if n == 1 else "ies"))
    if not ok:
        P.append("<ul>")
        for name, cok, detail in checks:
            if not cok:
                P.append("<li class=gap>%s &mdash; %s</li>" % (_esc(name), _esc(detail)))
        P.append("</ul>")

    # verdict tally
    P.append("<div class=counts>")
    for v, c in sorted(verdicts.items()):
        P.append("<span class=chip><b>%d</b> %s</span>" % (c, _esc(v)))
    if head.get("id"):
        P.append("<span class=chip>HEAD <b>%s</b></span>" % _esc(str(head["id"])[:12]))
    P.append("</div>")

    # the entries, newest first
    P.append("<table><thead><tr><th>#</th><th>date</th><th>target</th><th>metric</th>"
             "<th>claimed &rarr; recomputed</th><th>verdict</th></tr></thead><tbody>")
    for e in reversed(entries):
        vd = e.get("verdict", "")
        claimed, rec = e.get("claimed"), e.get("recomputed")
        if claimed is not None and rec is not None:
            num = "%s &rarr; <span class=gap>%s</span>" % (_fmt(claimed), _fmt(rec))
        elif e.get("kind") == "engagement-opened":
            num = "<span class=mono>(engagement opened)</span>"
        else:
            num = "&mdash;"
        P.append("<tr><td class=mono>%s</td><td class=mono>%s</td><td>%s</td><td class=mono>%s</td>"
                 "<td class=mono>%s</td><td><span class='v v-%s'>%s</span></td></tr>"
                 % (_esc(e.get("seq")), _esc(e.get("date")), _esc(e.get("target")),
                    _esc(e.get("metric")), num, _esc(vd or "?"), _esc(vd or "?")))
    P.append("</tbody></table>")

    # independent re-verification instructions (don't trust this HTML - check the bytes)
    P.append("<div class=verify><b>Don&#39;t trust this page &mdash; verify the bytes.</b><br><br>"
             "<span class=c>$</span> calma registry verify ./registry"
             "&nbsp;&nbsp;# re-hash every entry, walk the chain, check every SSHSIG<br>"
             "<span class=c>$</span> ssh-keygen -Y verify -f registry/entries/&lt;n&gt;.json ..."
             "&nbsp;&nbsp;# zero-install, stock OpenSSH (see each entry&#39;s allowed_signers)<br><br>"
             "The raw registry (HEAD.json + entries/) ships next to this file &mdash; re-run the audit "
             "offline on a fresh machine.</div>")

    P.append("<div class=foot>generated by <b>calma registry site</b> &middot; the verdict is computed "
             "by deterministic code, not a model &middot; hash-chained + SSHSIG-signed, "
             "offline-verifiable<br>github.com/rikhinkavuru/calma</div>")
    P.append("</div></body></html>")
    return "".join(P)


_DEPLOY_README = """\
# Calma catch-history registry (static site)

Generated by `calma registry site`. This directory is a SELF-CONTAINED, deployable site:

  index.html            the browsable, tamper-evident catch-record (open it, or host it)
  registry/             the raw HEAD.json + entries/ - the source of truth, re-verifiable offline

## Deploy

Any static host works (the site is one HTML file + the raw JSON, no build step, no server):

  GitHub Pages : commit this dir to a `gh-pages` branch (or /docs) and enable Pages
  Netlify/S3   : drop this dir in
  local        : open index.html

## Trust model

Don't trust the HTML - verify the bytes:

  calma registry verify ./registry          # re-hash + walk the chain + check every SSHSIG
  ssh-keygen -Y verify ...                   # zero-install, stock OpenSSH (per-entry allowed_signers)

The page is regenerated from `registry/` on every build, so it can never drift from the signed chain.
Rebuild after publishing new catches:  calma registry site ./registry --out <this-dir>
"""


def build_site(reg_dir, out_dir=None):
    """Write the deployable site: index.html + a copy of the raw registry (HEAD + entries) + a deploy
    README. out_dir defaults to <reg_dir>/site. Returns out_dir. Idempotent (rebuilds clean)."""
    reg_dir = os.path.realpath(reg_dir)
    if not os.path.isfile(REG._head_path(reg_dir)):
        raise ValueError("not a registry (no HEAD.json): %s" % reg_dir)
    # L2: contain --out (no parent/traversal escape), not just out != source
    out_dir = PS.guard_out_dir(out_dir or os.path.join(reg_dir, "site"), reg_dir)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.html"), "w") as fh:
        fh.write(render_index(reg_dir))
    with open(os.path.join(out_dir, "README.md"), "w") as fh:
        fh.write(_DEPLOY_README)
    # ship the raw, re-verifiable source next to the rendered page
    raw = os.path.join(out_dir, "registry")
    if os.path.isdir(raw):
        shutil.rmtree(raw)
    os.makedirs(os.path.join(raw, "entries"))
    shutil.copy2(REG._head_path(reg_dir), os.path.join(raw, "HEAD.json"))
    for n in REG.list_entry_files(reg_dir):
        shutil.copy2(os.path.join(REG._entries_dir(reg_dir), n),
                     os.path.join(raw, "entries", n))
    return out_dir
