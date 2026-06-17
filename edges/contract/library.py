"""P2.3 -- the repo-shape library: fingerprints, nearest-shape priors, mined binding rules. Makes
drafting ONE-SHOT for repos whose shape was seen before, and turns the P2.2 counterexample corpus into a
priors library folded into the drafter's system prompt. Priors only SPEED the proposer; the data-regrade
(regrade_committed) still decides every grade on every run -- a seeded/ruled draft is subjected to the
data check exactly as a cold draft is. No engine calls here; it composes around P2.2's draft_with_repair.
"""
import hashlib
import json
import os
import re

from edges.common import store
from edges.contract import repo_scan
from edges.contract.loop import CE_LOG, draft_with_repair

SHAPES = os.path.join(os.path.dirname(__file__), "data", "shapes.jsonl")
RULES = os.path.join(os.path.dirname(__file__), "data", "binding_rules.json")


def _jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a | b) else 0.0


def _entrypoint_kind(repo_path):
    names = {os.path.basename(e["path"]) for e in repo_scan.entrypoint_candidates(repo_path)}
    for kind in ("run.sh", "gen_fixture.py", "main.py"):
        if kind in names:
            return kind
    if names:
        return "single-script"
    return "manual"


def _column_tokens(repo_path):
    toks = set()
    for h in repo_scan.scan_csv_heads(repo_path):
        for c in h["header"]:
            toks.add(c.strip().lower())
    return sorted(toks)


def _output_globs(repo_path):
    globs = set()
    for h in repo_scan.scan_csv_heads(repo_path):
        d = os.path.dirname(h["path"])
        globs.add((d + "/*.csv") if d else "*.csv")
    return sorted(globs)


def fingerprint(repo_path):
    """The shape key fields: frameworks + output_glob + entrypoint_kind + the union of header tokens."""
    return {"frameworks": repo_scan.fingerprint(repo_path),
            "output_glob": _output_globs(repo_path),
            "entrypoint_kind": _entrypoint_kind(repo_path),
            "artifact_columns": _column_tokens(repo_path)}


def shape_key(fp):
    """A stable hash of the salient fields (frameworks + entrypoint_kind + normalized column-token set)."""
    key = "%s|%s|%s" % (",".join(sorted(fp.get("frameworks", []))),
                        fp.get("entrypoint_kind", ""),
                        ",".join(sorted(fp.get("artifact_columns", []))))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _glob_for(path):
    d = os.path.dirname(path)
    return (d + "/*.csv") if d else "*.csv"


def _skeletonize(contract):
    """The reusable PRIORS, not the literal contract: null claimed_value/precision; generalize artifact
    paths to their glob; keep bindings + tags + conventions + split (the priors)."""
    sk = json.loads(json.dumps(contract))
    for m in sk.get("metrics", []):
        m["claimed_value"] = None
        m["claimed_precision"] = None
        m["artifact"] = _glob_for(m.get("artifact", ""))
    for a in sk.get("artifacts", []):
        a["path"] = _glob_for(a.get("path", ""))
    for b in sk.get("baselines", []):
        b["artifact"] = _glob_for(b.get("artifact", ""))
    return sk


def remember_shape(repo_path, contract, *, shapes_path=None, ts=None):
    """After a SUCCESSFUL draft (resolved=True), store the skeleton keyed by shape_key."""
    fp = fingerprint(repo_path)
    rec = {"shape_key": shape_key(fp), "fingerprint": fp, "skeleton": _skeletonize(contract)}
    if ts is not None:
        rec["ts"] = int(ts)
    store.append(shapes_path or SHAPES, rec)


def nearest_shape(repo_path, *, min_sim=0.5, shapes_path=None):
    """The best-matching stored skeleton by similarity (frameworks Jaccard + entrypoint match + column
    Jaccard), or None if nothing clears min_sim."""
    fp = fingerprint(repo_path)
    best = None
    for rec in store.iter_records(shapes_path or SHAPES):
        rfp = rec.get("fingerprint", {})
        g = _jaccard(fp["frameworks"], rfp.get("frameworks", []))
        c = _jaccard(fp["artifact_columns"], rfp.get("artifact_columns", []))
        e = 1.0 if fp["entrypoint_kind"] == rfp.get("entrypoint_kind") else 0.0
        sim = 0.4 * g + 0.4 * c + 0.2 * e
        if sim >= min_sim and (best is None or sim > best["similarity"]):
            best = {"skeleton": rec["skeleton"], "similarity": sim, "shape_key": rec["shape_key"]}
    return best


def seed_for(repo_path, *, shapes_path=None):
    """The skeleton to seed llm_draft with (nearest_shape's skeleton), or None."""
    hit = nearest_shape(repo_path, shapes_path=shapes_path)
    return hit["skeleton"] if hit else None


# --- rule mining (counterexample corpus -> reusable system-prompt rules) ------------------------
def _name_token(col):
    m = re.findall(r"[a-z]+", (col or "").lower())
    return m[0] if m else (col or "").lower()


_RULE_TEXT = {
    ("out_of_unit_range", "score"): "A column named like '%s' whose values exceed 1 is a logit/raw score, "
                                    "not a probability; for a metric needing a [0,1] score, bind the "
                                    "column whose values lie in [0,1].",
    ("out_of_unit_range", "prob"): "A column named like '%s' whose values exceed 1 is a logit/raw score, "
                                   "not a probability; bind the column whose values lie in [0,1].",
    ("return_too_large", "return"): "A column named like '%s' whose values are in the tens/hundreds is a "
                                    "price or percent, not a per-period return; bind the per-period "
                                    "(|r|<1) column.",
    ("return_too_large", "benchmark"): "A column named like '%s' in the tens/hundreds is a price/percent, "
                                       "not a per-period return; bind the per-period (|r|<1) column.",
    ("too_many_distinct", "label"): "A high-cardinality column named like '%s' is a continuous score, not "
                                    "a discrete label; bind the 0/1 (or <=20-distinct) column for "
                                    "label/accuracy metrics.",
    ("too_many_distinct", "prediction"): "A high-cardinality column named like '%s' is a continuous "
                                         "score, not a discrete prediction; bind the 0/1 column.",
    ("negative_duration", "duration"): "A column named like '%s' with negative values is not a "
                                       "duration/timing; bind a non-negative timing column.",
    ("low_density", "query"): "A sparsely-populated column named like '%s' is not a usable key; bind a "
                              ">=95%%-populated key column.",
}


def _rule_text(violation, tag, token):
    tmpl = _RULE_TEXT.get((violation, tag))
    if tmpl is None:
        return ("A column named like '%s' did not pass the %s role check; bind the column whose VALUES "
                "fit the %s role." % (token, tag, tag))
    return tmpl % token


def _action(violation):
    return {"out_of_unit_range": "rebind to an in-[0,1] column",
            "return_too_large": "rebind to a per-period return column",
            "too_many_distinct": "rebind to the discrete label column",
            "negative_duration": "rebind to a non-negative column",
            "low_density": "rebind to a populated key column"}.get(violation, "rebind by the values")


def mine_binding_rules(*, min_support=3, ce_log=None, rules_path=None):
    """Cluster the counterexample corpus by (violation, tag) and emit a rule per cluster seen >=
    min_support times. Persist with support counts. Returns the rule strings."""
    from collections import Counter, defaultdict
    ce_log = ce_log or CE_LOG
    buckets = defaultdict(list)
    corpus = 0
    for r in store.iter_records(ce_log):
        corpus += 1
        buckets[(r.get("violation"), r.get("tag"))].append(r)
    rules = []
    for (violation, tag), recs in sorted(buckets.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        if len(recs) < min_support:
            continue
        token = Counter(_name_token(r.get("bad_column")) for r in recs).most_common(1)[0][0]
        rules.append({"rule": _rule_text(violation, tag, token), "violation": violation, "tag": tag,
                      "column_pattern": token, "support": len(recs), "suggested_action": _action(violation)})
    import time
    payload = {"rules": rules, "generated_ts": int(time.time()), "corpus_size": corpus}
    json.dump(payload, open(rules_path or RULES, "w"), indent=2)
    return [r["rule"] for r in rules]


def binding_rules(*, rules_path=None):
    """Load the current mined rules (the extra_rules passed into llm_draft/draft_with_repair)."""
    path = rules_path or RULES
    if not os.path.exists(path):
        return []
    return [r["rule"] for r in json.load(open(path)).get("rules", [])]


def draft_oneshot(repo_path, *, budget=3, model=None, shapes_path=None, rules_path=None, ce_log=None,
                  drafts_log=None, ts=None):
    """The one-shot path: seed llm_draft with the nearest known skeleton + the mined binding rules, run
    draft_with_repair, and (on resolve) remember THIS shape for next time. Priors narrow the model's
    search; the data check still decides every grade."""
    seed = seed_for(repo_path, shapes_path=shapes_path)
    rules = binding_rules(rules_path=rules_path)
    contract, trace = draft_with_repair(repo_path, budget=budget, model=model, extra_rules=rules,
                                        seed_skeleton=seed, ce_log=ce_log, drafts_log=drafts_log, ts=ts)
    if trace["resolved"]:
        remember_shape(repo_path, contract, shapes_path=shapes_path, ts=ts)
    return contract, trace
