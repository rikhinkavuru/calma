"""WS5: proof as a product - `calma proof show` (glance + shareable links + the ceiling) and
`calma proof verify` (offline re-verify). Pure stdlib, offline. Run: python3 test_ws5_proof.py
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import calma as C   # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _run(fn, *a, **k):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


tmp = tempfile.mkdtemp(prefix="calma-ws5-")
try:
    # a minimal but valid ledger for a CONFIRMED accuracy claim.
    rd = os.path.join(tmp, ".calma", "run")
    os.makedirs(rd)
    led = {"repo_verdict": "REFUTED",
           "claims": [{"metric": "accuracy", "claimed_value": 0.99, "recomputed_value": 0.81,
                       "verdict": "REFUTED"}],
           "findings": [], "scope": {}}
    with open(os.path.join(rd, "ledger.json"), "w") as fh:
        json.dump(led, fh)

    # ---- proof show: human glance ----
    rc, out = _run(C.proof_show_cmd, tmp)
    truth(rc == 0, "proof show exits 0")
    truth("Caught" in out and "accuracy" in out, "proof show rolls the verdict into the 3-outcome (Caught)")
    truth("claimed 0.99" in out and "recomputed 0.81" in out, "proof show shows claimed vs recomputed")
    truth("ceiling" in out and "NOT input-data authenticity" in out,
          "proof show ALWAYS carries the data-authenticity ceiling")
    truth("re-verify offline:  calma proof verify" in out, "proof show names the offline re-verify command")
    truth("trycalma.ai/proof?" in out and "outcome=Caught" in out,
          "proof show emits the shareable proof permalink (trycalma.ai/proof)")
    truth("trycalma.ai/badge?" in out and "verified by calma" in out,
          "proof show emits the embeddable badge markdown (trycalma.ai/badge)")

    # ---- proof show --json ----
    rc, out = _run(C.proof_show_cmd, tmp, as_json=True)
    j = json.loads(out)
    truth(j["verdict"] == "REFUTED" and j["outcome"] == "Caught" and j["metric"] == "accuracy",
          "proof show --json carries verdict + outcome + metric")

    # ---- proof verify on a MISSING bundle: clean refusal (exit 2, never a false VALID) ----
    import contextlib
    _err = io.StringIO()
    with redirect_stdout(io.StringIO()), contextlib.redirect_stderr(_err):
        rc = C.proof_verify_cmd(os.path.join(tmp, "nope"))
    truth(rc == 2 and "no proof bundle" in _err.getvalue().lower(),
          "proof verify: missing bundle -> exit 2 + guidance on stderr")
    # _find_bundle resolves a dir to its bundle (or None) without raising.
    truth(C._find_bundle(tmp) is None, "_find_bundle: None when no bundle present (no crash)")

    # ---- a reproduction (no claim) still shows the ceiling + a badge ----
    led2 = {"repo_verdict": "CONFIRMED",
            "claims": [{"metric": "column_sum", "claimed_value": None, "recomputed_value": 4950.0,
                        "verdict": "CONFIRMED"}], "findings": [], "scope": {}}
    rd2 = os.path.join(tmp, "repro", ".calma", "run")
    os.makedirs(rd2)
    with open(os.path.join(rd2, "ledger.json"), "w") as fh:
        json.dump(led2, fh)
    rc, out = _run(C.proof_show_cmd, os.path.join(tmp, "repro"))
    truth(rc == 0 and "Confirmed" in out and "no claim" in out, "proof show: reproduction reads as Confirmed (no claim)")
    truth("ceiling" in out, "proof show: the ceiling is on every proof, including reproductions")

    # ---- the MEDIUM fix: a CONFIRMED verdict carrying an OPEN blocking finding (e.g. reproduces its
    #      number but loses to the trivial baseline) gates to exit 1 and MUST read Caught on proof show,
    #      NEVER green - via the real gate, not a verdict-only reconstruction. ----
    led3 = {"repo_verdict": "CONFIRMED",
            "claims": [{"metric": "total_return", "claimed_value": -0.324, "recomputed_value": -0.324,
                        "verdict": "CONFIRMED"}],
            "findings": [{"severity": "major", "status": "open", "dimension": "baseline",
                          "locator": "loses to buy-and-hold"}],
            "scope": {}}
    rd3 = os.path.join(tmp, "baseline", ".calma", "run")
    os.makedirs(rd3)
    with open(os.path.join(rd3, "ledger.json"), "w") as fh:
        json.dump(led3, fh)
    rc, out = _run(C.proof_show_cmd, os.path.join(tmp, "baseline"))
    truth("Caught" in out and "Confirmed" not in out,
          "proof show: CONFIRMED + open blocking finding reads Caught (the real gate), never green")
    rc, out = _run(C.proof_show_cmd, os.path.join(tmp, "baseline"), as_json=True)
    truth(json.loads(out)["outcome"] == "Caught", "proof show --json: open-blocker run rolls up to Caught")
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("ws5-proof: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
