"""Validate the pure-stdlib WS2 kernels against the FROZEN, scipy/numpy-anchored reference vectors
(assets/overfitting_reference_vectors.json) at rel-tol 1e-9 - and prove the validation path imports NO
reference library (numpy/scipy/sklearn). Mirrors the freeze-once / stdlib-forever contract. Pure stdlib.
Run: python3 test_overfitting_vectors.py
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import numeric as N  # noqa: E402

VECTORS = os.path.join(HERE, "..", "..", "assets", "overfitting_reference_vectors.json")
MANIFEST = VECTORS.replace(".json", ".manifest.json")
_n = _fail = 0


def approx(got, want, atol, rtol, label):
    global _n, _fail
    _n += 1
    if not (abs(got - want) <= atol + rtol * abs(want)):
        _fail += 1
        print("  FAIL [%s] got %r want %r (atol %g rtol %g)" % (label, got, want, atol, rtol))


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


KINDS = {
    "deflated_sharpe": lambda a: N.deflated_sharpe_ratio(
        a["sr"], a["n_obs"], a["skew"], a["kurt_excess"], a["n_trials"], a["var_sr"]),
    "pbo_cscv": lambda a: N.pbo_cscv(a["matrix"], a["n_splits"]),
}

doc = json.load(open(VECTORS))
truth(doc["n_cases"] == len(doc["cases"]) and doc["cases"], "frozen vector file is non-empty + self-consistent")
seen = set()
for case in doc["cases"]:
    seen.add(case["kind"])
    approx(KINDS[case["kind"]](case["args"]), case["expected"], case["atol"], case["rtol"], case["id"])
truth(seen == set(KINDS), "every dispatch kind is exercised by the frozen vectors")

# ---- manifest: versions recorded + the frozen cases match the pinned sha256 (tamper-evident) ----
man = json.load(open(MANIFEST))
gw = man.get("generated_with", {})
truth(all(gw.get(k) for k in ("python", "numpy", "scipy", "sklearn")),
      "manifest records the pinned python/numpy/scipy/sklearn versions")
truth(man.get("pbo_noise_seed") == 7919, "manifest records the pinned PBO noise seed")
_blob = json.dumps(doc["cases"], sort_keys=True, separators=(",", ":")).encode()
truth(hashlib.sha256(_blob).hexdigest() == man.get("cases_sha256"),
      "frozen cases hash matches the manifest (the vectors were not edited post-freeze)")

# ---- the load-bearing CI property: the validation path imports NO reference library ----
truth("numpy" not in sys.modules and "scipy" not in sys.modules and "sklearn" not in sys.modules,
      "CI validation imports NO reference lib (stdlib + numeric only)")

print("overfitting_vectors: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
