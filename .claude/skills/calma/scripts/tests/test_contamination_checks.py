"""Tests for contamination_checks.py: exact eval-in-corpus memorization (exact magnitude), the
heuristic near-duplicate minhash detector, the held-out scope-guard, and the verdict promotion
(INVALIDATED / CAN'T-CONFIRM / CAVEAT) verified through real ledgers that ledger.validate_obj + gate
accept. Pure stdlib. Run: python3 test_contamination_checks.py
"""
import copy
import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import contamination_checks as CN  # noqa: E402
import ledger as L  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _write(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def _writelines(path, lines):
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def _kind(findings, k):
    return next((f for f in findings if f.get("contamination_kind") == k), None)


# ====================================================================================
# (1) exact memorization: 4 of 10 eval prompts are verbatim in the corpus -> magnitude EXACTLY 0.40
# ====================================================================================
dM = tempfile.mkdtemp()
_evals = ["what is the capital of france", "compute 17 times 23", "who wrote pride and prejudice",
          "what year did the berlin wall fall", "translate hello into spanish", "what is photosynthesis",
          "name the largest planet", "what is the boiling point of water", "define entropy in physics",
          "how many continents are there"]
_write(os.path.join(dM, "eval.csv"), ["prompt", "pred", "label"],
       [[p, 1, 1] for p in _evals])
# corpus contains 4 of the eval prompts verbatim (+ unrelated filler)
_writelines(os.path.join(dM, "corpus.txt"),
            [_evals[0], _evals[2], _evals[5], _evals[8], "some unrelated pretraining document text here",
             "another corpus document about cooking recipes and gardening tips"])
cM = {"corpus": {"manifest": "corpus.txt", "eval_col": "prompt"}, "artifacts": [],
      "metrics": [{"metric_id": "accuracy", "artifact": "eval.csv", "headline": True, "claimed_value": 0.9,
                   "binding": {"prediction": "pred", "label": "label"}}]}
fM = CN.run_checks(cM, dM, "c1", claim_text="90% accuracy on the held-out benchmark")
_mem = _kind(fM, "memorization")
truth(_mem is not None and abs(_mem["magnitude"] - 0.40) < 1e-12,
      "memorization magnitude EXACTLY 0.40 (got %r)" % (_mem and _mem["magnitude"]))
truth(_mem and _mem["severity"] == "blocker" and _mem["validity_class"] == "authoritative",
      "exact eval-in-corpus -> authoritative blocker")
truth(_mem and _mem["reverify"]["kind"] == "artifact-recheck",
      "contamination finding re-verifies by artifact-recheck (contamination is an EXEC dim)")
truth("contamination" in L.DIMENSIONS and "contamination" in L.EXEC_DIMENSIONS,
      "the 'contamination' dimension is registered (DIMENSIONS + EXEC_DIMENSIONS)")

# whitespace-canonicalization: a reformatted-whitespace copy still hashes as an exact hit
dW = tempfile.mkdtemp()
_write(os.path.join(dW, "eval.csv"), ["prompt", "pred", "label"], [["  what   is   the  capital of  france  ", 1, 1]])
_writelines(os.path.join(dW, "corpus.txt"), ["what is the capital of france"])
cW = dict(cM, corpus={"manifest": "corpus.txt", "eval_col": "prompt"})
fW = CN.run_checks(cW, dW, "c1", claim_text="held-out accuracy")
truth(_kind(fW, "memorization") is not None, "whitespace-only reformatting is still an exact memorization hit")

# (2) NOT-APPLICABLE: no corpus block -> silent
truth(CN.run_checks({"metrics": []}, dM, "c1") == [] and CN.family_status({"metrics": []}, []) == "not-applicable",
      "no corpus block -> contamination NOT-APPLICABLE, silent")
truth(CN.family_status(cM, fM) == "flagged", "corpus + a finding -> family 'flagged'")

# clean eval (no overlap) -> no finding, family 'checked'
dCln = tempfile.mkdtemp()
_write(os.path.join(dCln, "eval.csv"), ["prompt", "pred", "label"], [["genuinely novel held-out question number %d" % i, 1, 1] for i in range(10)])
_writelines(os.path.join(dCln, "corpus.txt"), ["totally different corpus text about astronomy and chemistry"])
cCln = dict(cM, corpus={"manifest": "corpus.txt", "eval_col": "prompt"})
fCln = CN.run_checks(cCln, dCln, "c1", claim_text="held-out accuracy")
truth(fCln == [], "a clean eval (no corpus overlap) fires no contamination findings")
truth(CN.family_status(cCln, fCln) == "checked", "corpus, no finding -> family 'checked'")


# ====================================================================================
# (3) near-duplicate (HEURISTIC minhash): a one-word edit of a ~50-word corpus item -> soft minor
# ====================================================================================
dN = tempfile.mkdtemp()
_corpus_long = ("the quick brown fox jumps over the lazy dog and then runs along the winding river bank "
                "past the old stone mill before sunset on a calm autumn evening in the quiet green valley "
                "where the farmers gather their crops and the children play near the wooden fence by the road")
_neardup = _corpus_long.replace("sunset", "dusk")   # one word changed -> minhash est >= 0.80, not exact
_write(os.path.join(dN, "eval.csv"), ["prompt", "pred", "label"], [[_neardup, 1, 1]])
_writelines(os.path.join(dN, "corpus.txt"), [_corpus_long])
cN = dict(cM, corpus={"manifest": "corpus.txt", "eval_col": "prompt"})
fN = CN.run_checks(cN, dN, "c1", claim_text="held-out accuracy")
_nd = _kind(fN, "near-duplicate")
truth(_nd is not None and _nd["severity"] == "minor" and _nd["validity_class"] == "soft",
      "near-duplicate (minhash) -> heuristic soft minor (got %r)" % (fN))
truth(_kind(fN, "memorization") is None, "a near-dup that is not byte-identical is NOT an exact memorization hit")


# ====================================================================================
# held-out scope-guard
# ====================================================================================
truth(CN.contamination_status(cM, "90% on the held-out benchmark") == "held-out", "'held-out' -> held-out")
truth(CN.contamination_status(cM, "zero-shot accuracy 0.9") == "held-out", "'zero-shot' -> held-out")
truth(CN.contamination_status(cM, "few-shot in-context accuracy") == "allowed", "'few-shot in-context' -> allowed")
truth(CN.contamination_status(cM, "accuracy 0.9") == "indeterminate", "no held-out/allowed language -> indeterminate")


# ====================================================================================
# apply_validity - the verdict lattice, verified through real ledgers
# ====================================================================================
def _confirmed_claim():
    vi = {"gap": 0.0, "effective_budget": 1e-9, "binding_status": "independently-bound",
          "determinism_mode": "controlled-to-bit", "container_present": True, "band_coverage_ok": True,
          "sufficient_k": True, "exit_codes": [0], "claim_outside_ci": False, "claim_confirmed_target": True}
    c = {"id": "c1", "headline": True, "verdict": V.verdict(vi), "input_binding_status": "independently-bound",
         "verdict_inputs": vi, "waivable": False, "metric": "accuracy", "claimed_value": 0.9, "recomputed_value": 0.9}
    assert c["verdict"] == V.CONFIRMED
    return c


def _ledger(claims, findings):
    led = {"schema": "calma/ledger@1", "claims": claims, "findings": findings,
           "scope": {"isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"}, "repo_verdict": None}
    led["repo_verdict"] = L.compute_repo_verdict(led)
    return led


# (A) exact memorization + HELD-OUT claim -> INVALIDATED, exit 1, valid ledger
clA, fdA = [_confirmed_claim()], copy.deepcopy(fM)
CN.apply_validity(clA, fdA, cM, "90% accuracy on the held-out benchmark")
truth(clA[0]["verdict"] == V.INVALIDATED, "held-out + exact contamination -> INVALIDATED (got %s)" % clA[0]["verdict"])
truth(clA[0].get("driving_dimension") == "contamination", "INVALIDATED driving_dimension = contamination")
ledA = _ledger(clA, fdA)
truth(L.validate_obj(ledA)[0] == 1 and ledA["repo_verdict"] == V.INVALIDATED, "contamination-INVALIDATED ledger validates (not clean)")
truth(L.gate(ledA)[0] == 1, "contamination INVALIDATED gates to exit 1")

# (B) exact memorization + ALLOWED (few-shot/in-context) claim -> CAVEAT, exit 0
clB, fdB = [_confirmed_claim()], copy.deepcopy(fM)
CN.apply_validity(clB, fdB, cM, "few-shot in-context accuracy 0.9")
truth(clB[0]["verdict"] == V.CAVEATS, "contamination-allowed claim -> CONFIRMED-WITH-CAVEATS (got %s)" % clB[0]["verdict"])
truth(all(f["severity"] == "minor" for f in fdB if f["dimension"] == "contamination"),
      "allowed: authoritative findings demoted to minor (gate stays exit 0)")
truth(L.gate(_ledger(clB, fdB))[0] == 0, "contamination-allowed CAVEAT ledger is CLEAN (exit 0)")

# (C) exact memorization + INDETERMINATE scope -> CAN'T-CONFIRM, exit 1, 'declare held-out' fix
clC, fdC = [_confirmed_claim()], copy.deepcopy(fM)
CN.apply_validity(clC, fdC, cM, "accuracy 0.9")
truth(clC[0]["verdict"] == V.INCONCLUSIVE, "indeterminate scope -> CAN'T-CONFIRM (got %s)" % clC[0]["verdict"])
truth(any("held-out" in (f.get("unblock") or "") for f in fdC), "the fix tells the author to declare the eval is held-out")
truth(L.gate(_ledger(clC, fdC))[0] == 1, "contamination CAN'T-CONFIRM gates to exit 1")

# (D) heuristic near-dup -> CAVEAT, exit 0 (never INVALIDATED, even on a held-out claim)
clD, fdD = [_confirmed_claim()], copy.deepcopy(fN)
CN.apply_validity(clD, fdD, cN, "zero-shot held-out accuracy 0.9")
truth(clD[0]["verdict"] == V.CAVEATS, "heuristic near-dup -> CAVEAT, never INVALIDATED (got %s)" % clD[0]["verdict"])
truth(L.gate(_ledger(clD, fdD))[0] == 0, "soft near-dup caveat is exit 0")

# (E) no contamination findings -> verdict untouched
clE = [_confirmed_claim()]
CN.apply_validity(clE, [], cCln, "held-out accuracy 0.9")
truth(clE[0]["verdict"] == V.CONFIRMED, "no contamination findings -> headline verdict unchanged")


# ====================================================================================
# end-to-end through calma._assemble_ledger (the real wiring)
# ====================================================================================
import calma as C  # noqa: E402

_diff = {"metrics": [{"metric_id": "accuracy", "headline": True, "claimed": 0.9, "recomputed": 0.9,
                      "verdict": V.CONFIRMED, "verdict_inputs": _confirmed_claim()["verdict_inputs"],
                      "reason": "matches within budget", "recompute_error": None}],
         "baseline": None}
_run_res = {"exit_code": 0, "run_dir": os.path.join(dM, ".calma", "r"), "base": dM,
            "isolation_tier": "tier0", "determinism_mode": "controlled-to-bit"}
_led = C._assemble_ledger(cM, _diff, _run_res, claim_text="90% accuracy on the held-out benchmark")
truth(_led["repo_verdict"] == V.INVALIDATED, "e2e: _assemble_ledger wires contamination -> repo INVALIDATED (got %s)"
      % _led["repo_verdict"])
truth(L.validate_obj(_led)[0] == 1, "e2e: the assembled contamination-INVALIDATED ledger validates")
truth(_led["scope"]["families"].get("contamination") == "flagged", "e2e: scope.families.contamination = flagged")

# e2e clean: no overlap -> CONFIRMED, contamination 'checked'
_run_clean = dict(_run_res, base=dCln)
_led_clean = C._assemble_ledger(dict(cCln, metrics=cM["metrics"]), _diff, _run_clean, claim_text="held-out accuracy 0.9")
truth(_led_clean["repo_verdict"] == V.CONFIRMED and _led_clean["scope"]["families"].get("contamination") == "checked",
      "e2e: a clean eval -> CONFIRMED with contamination 'checked' (got %s)" % _led_clean["repo_verdict"])

# ====================================================================================
# security / robustness (adversarial audit 2026-06-16): path containment, 64-hex content, DoS bound
# ====================================================================================
import time as _time  # noqa: E402

# (sec-1) path traversal: a manifest pointing outside the contract base must be REFUSED (no file read)
dSec = tempfile.mkdtemp()
truth(CN._load_corpus({"corpus": {"manifest": "/etc/hosts"}}, dSec) == (None, None),
      "absolute-path manifest -> refused (no out-of-base read)")
truth(CN._load_corpus({"corpus": {"manifest": "../../../etc/hosts"}}, dSec) == (None, None),
      "..-traversal manifest -> refused")
truth(CN._safe_join(dSec, "ok.txt").startswith(os.path.realpath(dSec)), "_safe_join keeps in-base paths")
_raised = False
try:
    CN._safe_join(dSec, "../escape")
except ValueError:
    _raised = True
truth(_raised, "_safe_join raises on a traversal attempt")

# (sec-2) 64-hex content asymmetry: a literal 64-hex eval item that appears verbatim in the corpus is
# now an exact hit (previously a false-clean miss because the hex line was read only as a precomputed hash)
dHex = tempfile.mkdtemp()
_hx = "a" * 64
_write(os.path.join(dHex, "eval.csv"), ["prompt", "pred", "label"], [[_hx, 1, 1]])
_writelines(os.path.join(dHex, "corpus.txt"), [_hx])
cHex = dict(cM, corpus={"manifest": "corpus.txt", "eval_col": "prompt"})
truth(_kind(CN.run_checks(cHex, dHex, "c1", claim_text="held-out"), "memorization") is not None,
      "a literal 64-hex eval item matching a same-string corpus line is flagged (no 64-hex false-clean)")

# (sec-3) DoS bound: an adversarial near-identical corpus (shared body, unique suffix) used to be O(N^2);
# the degenerate-band short-circuit keeps it near-linear. Bound the wall-clock as a regression guard.
dDoS = tempfile.mkdtemp()
_body = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod "
_nn = 3000
_write(os.path.join(dDoS, "eval.csv"), ["prompt", "pred", "label"],
       [[_body + "u%d" % i, 1, 1] for i in range(_nn)])
_writelines(os.path.join(dDoS, "corpus.txt"), [_body + "c%d" % i for i in range(_nn)])
cDoS = dict(cM, corpus={"manifest": "corpus.txt", "eval_col": "prompt"})
_t0 = _time.time()
CN.check_near_dup(cDoS, dDoS, "c1")
truth(_time.time() - _t0 < 5.0, "near-dup over a %dx%d near-identical corpus stays bounded (degenerate-band guard)" % (_nn, _nn))

print("contamination_checks: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
