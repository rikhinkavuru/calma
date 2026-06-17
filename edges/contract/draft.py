"""P2.1 -- the LLM contract drafter for messy real repos. AUGMENT the heuristic draft; never invent a
grade. The model emits the contract schema ONLY; _sanitize() strips any grade/verdict it slips in and
drops out-of-vocab metric_ids / tags / phantom artifacts. The first engine.verify is P2.2's job.

A2 imports draft_contract + recipes as READ-ONLY libraries (allowed -- not in the firewall's forbidden
set). It never imports verdict/ledger/compare/recompute/numeric."""
import json
import os
import sys

_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                        ".claude", "skills", "calma", "scripts"))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
import draft_contract as DC  # noqa: E402  (read-only library; NOT the verdict core)

from edges.common import llm, store  # noqa: E402
from edges.contract import repo_scan  # noqa: E402
from edges.contract.schema import CONTRACT_SCHEMA  # noqa: E402

DRAFTS_LOG = os.path.join(os.path.dirname(__file__), "data", "drafts.jsonl")

_ENGINE_METRIC_IDS = None


def _engine_metric_ids():
    """The closed metric vocabulary: every metric_id the engine recognizes (recipes registry first; the
    union of METRIC_BY_TAGS + CLAIM_METRIC_HINTS as a fallback)."""
    global _ENGINE_METRIC_IDS
    if _ENGINE_METRIC_IDS is None:
        ids = {mid for _tags, mid in DC.METRIC_BY_TAGS}
        ids |= {mid for _w, mid in DC.CLAIM_METRIC_HINTS}
        try:
            import recipes as R
            ids |= set(R.ids())
        except Exception:
            pass
        _ENGINE_METRIC_IDS = ids
    return _ENGINE_METRIC_IDS


# the legal `tag` values (TAG_PATTERNS + the string-key tags + generic-numeric tags + the schema extras)
_ALLOWED_TAGS = ({tag for _pat, tag in DC.TAG_PATTERNS} | set(DC.STRING_KEY_TAGS)
                 | set(DC._GENERIC_NUMERIC_TAGS)
                 | {"price", "score", "prob", "prediction", "label", "reference", "before", "after",
                    "duration", "hits", "relevance", "rank", "correct", "sample_a", "sample_b", "flag",
                    "timestamp", "left_key", "joined_key"})


def assemble_inputs(repo_path):
    """The model's evidence packet (pure-stdlib, no LLM): file tree, frameworks, entrypoint candidates,
    data-file heads, and the VERBATIM heuristic DC.draft() output as the starting point."""
    heur = DC.draft(repo_path)
    return {
        "repo_path": repo_path,
        "file_tree": repo_scan.file_tree(repo_path),
        "framework_signatures": repo_scan.fingerprint(repo_path),
        "entrypoint_candidates": repo_scan.entrypoint_candidates(repo_path),
        "data_file_heads": repo_scan.scan_csv_heads(repo_path),
        "heuristic_draft": heur,
        "heuristic_notes": heur.get("_draft_notes", {}),
    }


def _render_user(inputs, *, seed_skeleton=None, redraft_block=None):
    """Fill the USER template deterministically (repo-relative paths only). Optional seed_skeleton (P2.3)
    and redraft_block (P2.2 counterexamples) are appended when present."""
    tree = "\n".join("  " + p for p in inputs["file_tree"])
    ents = "\n".join("  - %s  -- %s" % (e["path"], e["why"]) for e in inputs["entrypoint_candidates"]) \
        or "  (none detected)"
    heads = []
    for h in inputs["data_file_heads"]:
        lines = ["%s  (~%d rows)" % (h["path"], h["approx_rows"]),
                 "  columns: %s" % h["header"]]
        for k, row in enumerate(h["rows_preview"], 1):
            lines.append("  row %d: %s" % (k, row))
        heads.append("\n".join(lines))
    heads_rendered = "\n\n".join(heads) or "(no CSV data files found)"

    body = _USER_TEMPLATE.format(
        repo_path=os.path.basename(inputs["repo_path"].rstrip("/")) or inputs["repo_path"],
        framework_signatures=inputs["framework_signatures"],
        file_tree_rendered=tree,
        entrypoint_candidates_rendered=ents,
        data_file_heads_rendered=heads_rendered,
        metric_vocab=_metric_vocab_block(),
        allowed_tags=", ".join(sorted(_ALLOWED_TAGS)),
        heuristic_draft_json=json.dumps(_strip_for_prompt(inputs["heuristic_draft"]), indent=2),
        heuristic_notes_json=json.dumps(inputs["heuristic_notes"], indent=2, default=str))
    if seed_skeleton is not None:
        body += "\n\n" + _SEED_BLOCK.format(seed_skeleton_json=json.dumps(seed_skeleton, indent=2))
    if redraft_block:
        body += "\n\n" + redraft_block
    return body


def _metric_vocab_block():
    """The closed list of engine metric_ids the model MUST choose from (e.g. 'auc', not 'roc_auc';
    'log_loss', not 'binary_cross_entropy'). Deterministic (sorted)."""
    return ", ".join(sorted(_engine_metric_ids()))


def _strip_for_prompt(heur):
    """Show the heuristic draft WITHOUT its grade fields, so the model is never primed to echo a grade."""
    h = json.loads(json.dumps(heur, default=str))
    for m in h.get("metrics", []):
        m.pop("binding_status", None)
        m.pop("claim_confirmed", None)
        m.pop("binding_source", None)
    h.pop("_draft_notes", None)
    return h


def llm_draft(repo_path, *, model=None, extra_rules=(), seed_skeleton=None, drafts_log=None, ts=None):
    """The augmented draft. assemble_inputs() -> structured() with CONTRACT_SCHEMA + the system prompt.
    Returns a sanitized, schema-valid contract dict. `extra_rules` (P2.3) folds mined binding rules into
    the system prompt; `seed_skeleton` (P2.3) seeds the user message with a known-shape skeleton."""
    inputs = assemble_inputs(repo_path)
    system = SYSTEM_PROMPT
    if extra_rules:
        system = system + "\n\nLearned binding rules (apply these):\n" + \
            "\n".join("- " + r for r in extra_rules)
    raw = llm.structured(_render_user(inputs, seed_skeleton=seed_skeleton), schema=CONTRACT_SCHEMA,
                         model=model or llm.SONNET, system=system, tool_name="emit")
    contract = _sanitize(raw, inputs)
    rec = {"repo_fingerprint": repo_scan.fingerprint(repo_path), "model": model or llm.SONNET,
           "n_metrics": len(contract.get("metrics", [])),
           "headline_metric": next((m["metric_id"] for m in contract.get("metrics", [])
                                    if m.get("headline")), None),
           "had_extra_rules": bool(extra_rules)}
    if ts is not None:
        rec["ts"] = int(ts)
    store.append(drafts_log or DRAFTS_LOG, rec)
    return contract


def _sanitize(contract, inputs):
    """Deterministic post-LLM scrub (the firewall's belt-and-suspenders): strip any grade the model
    emitted; drop out-of-vocab metric_ids; null out out-of-vocab tags; drop artifacts not in the scanned
    data; drop a split that references a missing file/column."""
    vocab = _engine_metric_ids()
    data_paths = {h["path"] for h in inputs["data_file_heads"]}
    for m in contract.get("metrics", []):
        m.pop("binding_status", None)
        m.pop("claim_confirmed", None)
        m.pop("binding_source", None)
    contract["metrics"] = [m for m in contract.get("metrics", [])
                           if m.get("metric_id") in vocab and m.get("artifact") in data_paths]
    contract["artifacts"] = [a for a in contract.get("artifacts", []) if a.get("path") in data_paths]
    for a in contract["artifacts"]:
        for _col, spec in list((a.get("columns") or {}).items()):
            t = (spec or {}).get("tag")
            if t is not None and t not in _ALLOWED_TAGS:
                spec["tag"] = None                      # unknown tag -> untagged, never invented
    sp = contract.get("split")
    if sp and not (set(filter(None, [sp.get("train"), sp.get("test"), sp.get("file")])) <= data_paths):
        contract.pop("split", None)
    # drop any top-level grade/verdict the model invented (defense in depth)
    for k in ("verdict", "confidence", "binding_status", "claim_confirmed"):
        contract.pop(k, None)
    return contract


SYSTEM_PROMPT = """You draft a Calma `verify.yaml` "contract" for a code repository. A contract tells a
DETERMINISTIC verifier (a) how to re-run the repo, (b) which output columns carry which quantities, and
(c) which headline numbers to recompute. You PROPOSE this structure. A separate deterministic checker then
RE-DERIVES every binding's trustworthiness FROM THE ACTUAL DATA and recomputes every number. You will
never be believed on assertion; you are believed only when the data agrees. So your job is to make the
contract STRUCTURALLY CORRECT -- point each binding at the column whose VALUES actually match the role.

You are given a heuristic draft as a starting point. AUGMENT and CORRECT it. Keep what is right; fix
mis-bindings; add the entrypoint, artifacts, bindings, conventions, and the train/test split the
heuristics missed. Prefer editing the heuristic draft over drafting from scratch.

HARD RULES (a violation is silently stripped, costing you the binding):
1. Emit ONLY the contract schema. Do NOT emit a verdict, a confidence, a "binding_status", a
   "claim_confirmed", or any grade. You CANNOT grade a binding -- the data checker does, and it is the
   only thing that can reach the trusted grade "independently-bound".
2. Use ONLY engine metric_ids (the recompute vocabulary the checker knows). Never invent a metric_id.
   If no engine metric fits a number, omit that metric (an omission is honest; an invented id is dropped).
3. Use ONLY the listed `tag` values for columns. A tag is a SEMANTIC role, not a column name.
4. Point each metric `binding` at the column whose VALUES fit the role, not the one whose NAME looks
   right. A column named "score" whose values exceed 1 is NOT a probability (it is a logit/raw score);
   if the metric needs a probability in [0,1], bind the column whose values lie in [0,1]. A column named
   "return" whose values are in the hundreds is a price or a percent, not a per-period return. Read the
   provided data heads and CHOOSE BY THE VALUES.
5. Set `headline: true` on exactly one primary metric. Set `claimed_value` only when the repo states a
   number for that metric; otherwise null. Never set `claimed_precision` (leave null).
6. Declare `split` ONLY when a real train/test partition exists. If none exists, omit split -- the leakage
   family then abstains, which is correct. Same for keys/features/trials/frictions/corpus: declare a block
   only when it genuinely applies; a wrong declaration is worse than an omission.

How the data checker grades a binding (so you can aim for the strong grade):
- "independently-bound" (trusted): the column's VALUES pass the role's sanity check -- a score/prob lies
  in [0,1]; a return is mostly |r|<1 and roughly centered; a label/prediction has few distinct values; a
  duration/before/after is non-negative; a generic numeric value column is clean and finite and is the
  ONLY column bound to that role in its file.
- "plausibly-bound": the column is bound but its values VIOLATE the role's expectation (out of range,
  non-finite, ambiguous). This caps the metric below trusted and yields an inconclusive result.
- "author-asserted": no column matched / the tag is missing.
Aim every binding at "independently-bound" by choosing the right column. You do not write the grade; you
earn it by binding correctly.

Return exactly one tool call to `emit` with the contract."""


_USER_TEMPLATE = """Repo: {repo_path}
Detected frameworks: {framework_signatures}

File tree (truncated):
{file_tree_rendered}

Entrypoint candidates (ranked):
{entrypoint_candidates_rendered}

Output data files (header + first rows; CHOOSE BINDINGS BY THESE VALUES):
{data_file_heads_rendered}

VALID metric_ids (use EXACTLY one of these per metric -- e.g. 'auc' not 'roc_auc', 'log_loss' not
'binary_cross_entropy'; if none fits a number, omit that metric):
{metric_vocab}

VALID column tags (the only legal `tag` values): {allowed_tags}

Heuristic starting draft (AUGMENT/CORRECT this -- keep what is right, fix mis-bindings, add what's missing):
{heuristic_draft_json}

Heuristic notes (what the heuristics flagged as uncertain or missing):
{heuristic_notes_json}

Produce the corrected contract now. Bind each metric to the column whose VALUES fit the role. Use only
engine metric_ids and the allowed tags. Do not emit any grade or verdict."""


_SEED_BLOCK = """Known-shape skeleton (a repo of this framework/output shape was successfully drafted
before; ADAPT its bindings/conventions/split to THIS repo's actual files and column values -- do not copy
paths blindly):
{seed_skeleton_json}"""
