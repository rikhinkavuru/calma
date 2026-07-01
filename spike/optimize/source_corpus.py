#!/usr/bin/env python
"""optimize.source_corpus — the automated corpus-sourcing pipeline (guide §A.6, P4).

The scalable execution-based benchmarks all converge on the same shape: programmatic sourcing → cheap
pre-filters → LLM-judge triage → dry-run → human oracle. Calma already owns the last three (planner =
triage, the runner = dry-run, humans = the oracle); this is the missing SOURCING front door. It turns the
quarterly-refresh loop into a standing script that runs UNATTENDED to Stage 4 and only queues Stage-5 human
labels.

    Stage 1  search        GitHub/Exa by topic+lang+size + a 'has a reported number' heuristic
    Stage 2  cheap filters  permissive SPDX license + size bound + ≥1 extractable number  (PURE, offline)
    Stage 3  planner triage  planner.plan_repo — entrypoint/deps/targets resolvable? (best-effort)
    Stage 4  dry-run        one k=1 verify in the sandbox — did it run? capture anything? (best-effort)
    Stage 5  human label     emit a repos.yaml stub (tier + per-claim expect + dev/test) for a human

Network/keys (GITHUB_TOKEN / EXA_API_KEY / ANTHROPIC_API_KEY / a sandbox) gate the online stages EXACTLY like
the planner: absent → that stage no-ops and the pipeline degrades gracefully (offline it produces an empty
queue, never an error). The PURE stages (cheap filters, freshness classification, stub emission) are the
testable core and run anywhere.

Freshness (guide §A.5): because the planner is an LLM, `is_post_cutoff` tags repos whose commit date is
AFTER the planner model's knowledge cutoff — the decontaminated slice the planner cannot have memorized.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
if SPIKE not in sys.path:
    sys.path.insert(0, SPIKE)

# permissive SPDX ids we accept (reference-by-SHA, never redistribute contents — guide §A.2 licensing).
PERMISSIVE = {"mit", "bsd-3-clause", "bsd-2-clause", "apache-2.0", "isc", "0bsd", "unlicense", "mit-0"}

# a repo has an extractable reported number if its README hits a percentage/decimal near a known metric word.
_NUM_RE = re.compile(
    r"\d+\.\d+\s*%|\b\d+\.\d{2,}\b", re.I)
_METRIC_WORD_RE = re.compile(
    r"\b(accuracy|acc|sharpe|sortino|calmar|ndcg|bleu|rouge|meteor|precision|recall|f1|auc|auroc|"
    r"map|mrr|r2|rmse|mae|mape|correlation|pearson|spearman|perplexity|top-?[15]|exact.?match|pass@k)\b", re.I)

# per-domain GitHub search seeds (topic + language). Stage 1 expands these; kept declarative for auditing.
DOMAIN_QUERIES = {
    "finance": ["topic:quant-finance language:python", "topic:backtesting language:python",
                "topic:algorithmic-trading language:python"],
    "statistics": ["topic:statistics language:python statsmodels", "topic:econometrics language:python"],
    "ir": ["topic:information-retrieval language:python ndcg", "topic:learning-to-rank language:python"],
    "nlp": ["topic:machine-translation language:python bleu", "topic:summarization language:python rouge"],
    "deeplearning": ["topic:pytorch language:python accuracy example", "topic:image-classification language:python"],
    "genomics": ["topic:bioinformatics language:python precision recall", "topic:variant-calling language:python"],
    "ml": ["topic:scikit-learn language:python accuracy", "topic:machine-learning language:python classification"],
}


# ---- Stage 2: cheap filters (PURE — the testable core) --------------------------------------------
def has_reported_number(readme_text: str) -> bool:
    """A cheap proxy for 'has ≥1 machine-extractable reported number': a metric word AND a percentage/decimal."""
    t = readme_text or ""
    return bool(_METRIC_WORD_RE.search(t) and _NUM_RE.search(t))


def permissive_license(spdx: str) -> bool:
    return (spdx or "").strip().lower() in PERMISSIVE


def size_ok(size_kb, max_kb: int = 50_000) -> bool:
    try:
        return 0 < int(size_kb) <= max_kb
    except (TypeError, ValueError):
        return False


def cheap_filter(repo: dict, max_kb: int = 50_000):
    """(ok, reasons) for a candidate repo dict {license, size_kb, readme}. Cuts the long tail before spending
    LLM tokens on triage (guide §A.6 Stage 2)."""
    reasons = []
    if not permissive_license(repo.get("license") or ""):
        reasons.append("license %r not permissive" % repo.get("license"))
    if not size_ok(repo.get("size_kb"), max_kb):
        reasons.append("size %r KB out of bound (<=%d)" % (repo.get("size_kb"), max_kb))
    if not has_reported_number(repo.get("readme", "")):
        reasons.append("no extractable reported number in README")
    return (not reasons), reasons


def is_post_cutoff(commit_date: str, cutoff: str = "2025-10-01") -> bool:
    """True if the repo's commit date is AFTER the planner model's knowledge cutoff (the decontaminated,
    freshness-safe slice; guide §A.5). Dates as 'YYYY-MM-DD'; unknown → False (conservative)."""
    d = (commit_date or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return False
    return d > cutoff


# ---- Stage 5: emit a repos.yaml stub to QUEUE for a human oracle ----------------------------------
def repos_yaml_stub(repo: dict, tier: str = "T2", split: str = "dev") -> dict:
    """The Stage-5 hand-off: a repos.yaml entry a human completes (per-claim `expect`, final tier, split).
    Humans are the ORACLE, never the sourcer — the expensive, reliable step kept small."""
    return {
        "name": repo.get("name", "unnamed"),
        "source": {"kind": "git", "url": repo.get("url", ""), "commit": repo.get("commit", "")},
        "meta": {"domain": repo.get("domain", "unknown"), "tier": tier, "split": split,
                 "license": repo.get("license", "unknown"), "commit_date": repo.get("commit_date", "unknown"),
                 "post_cutoff": is_post_cutoff(repo.get("commit_date", ""))},
        "discover": True,
        "_stage5_todo": "human: set per-claim expect for the graded subset; confirm tier + dev/test split",
    }


# ---- Stage 1: programmatic sourcing (GATED, best-effort) ------------------------------------------
def github_search(query: str, per_page: int = 20, token: str | None = None) -> list:
    """GitHub repo search → [{name,url,commit_date-ish,license,size_kb,...}]. GATED on GITHUB_TOKEN; absent /
    any error → [] (the pipeline degrades gracefully offline, guide's best-effort discipline)."""
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        return []
    try:
        import urllib.parse  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415
        url = "https://api.github.com/search/repositories?q=%s&per_page=%d" % (
            urllib.parse.quote(query), per_page)
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
            data = json.loads(r.read())
        out = []
        for it in data.get("items", []):
            lic = ((it.get("license") or {}).get("spdx_id") or "").strip()
            out.append({"name": it.get("full_name", "").replace("/", "__"), "url": it.get("clone_url", ""),
                        "license": lic, "size_kb": it.get("size", 0),
                        "commit_date": (it.get("pushed_at", "") or "")[:10], "readme": ""})
        return out
    except Exception:  # noqa: BLE001
        return []


def triage(repo_dir: str):
    """Stage 3 — planner triage. Returns the planner's run plan (entrypoint/deps/targets) or None. Best-
    effort: no key / SDK → None (the LLM-judge that drops unsound instances — which Calma already built)."""
    try:
        import planner  # noqa: PLC0415
        return planner.plan_repo(repo_dir)
    except Exception:  # noqa: BLE001
        return None


def run(domains=None, per_query: int = 10, out_path: str | None = None) -> dict:
    """Run Stages 1-2 across the domain queries and emit Stage-5 stubs for survivors. Stages 3-4 (triage,
    dry-run) run only when a clone + keys are available; offline this returns an empty, well-formed queue."""
    domains = domains or list(DOMAIN_QUERIES)
    queued, seen = [], set()
    stats = {"searched": 0, "passed_cheap": 0}
    for dom in domains:
        for q in DOMAIN_QUERIES.get(dom, []):
            for repo in github_search(q, per_page=per_query):
                stats["searched"] += 1
                if repo["name"] in seen:
                    continue
                seen.add(repo["name"])
                repo["domain"] = dom
                ok, _reasons = cheap_filter(repo)
                if not ok:
                    continue
                stats["passed_cheap"] += 1
                queued.append(repos_yaml_stub(repo))
    result = {"stats": stats, "stage5_queue": queued}
    if out_path:
        with open(out_path, "w") as fh:
            json.dump(result, fh, indent=2)
    return result


def main():
    res = run()
    print("=== corpus sourcing (Stages 1-2; 3-4 need a clone+keys) ===")
    print("searched=%d  passed-cheap-filters=%d  queued-for-Stage-5=%d"
          % (res["stats"]["searched"], res["stats"]["passed_cheap"], len(res["stage5_queue"])))
    if not res["stats"]["searched"]:
        print("(no GITHUB_TOKEN / offline → empty queue; the pipeline degraded gracefully)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
